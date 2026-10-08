"""Mô-đun tra cứu tài liệu và trí tuệ nhân tạo (Local AI & Internet Knowledge)
Chạy trực tiếp trên máy TrimUI Brick Pro, không phụ thuộc vào máy chủ Xiaozhi.
Tự động lấy thông tin từ tài liệu nội bộ và tự tìm kiếm trên Internet khi cần.
"""

import datetime
import html
import json
import math
import os
import re
import ssl
import sys
import time
import unicodedata
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

# Danh sách từ dừng tiếng Việt cơ bản để tối ưu tìm kiếm từ khoá
# Wikimedia yêu cầu User-Agent tự giới thiệu; UA giả trình duyệt bị giới hạn chặt hơn.
WIKI_USER_AGENT = "XiaozhiTrimUI-LocalAI/1.0 (TrimUI Brick Pro handheld; offline-first assistant) python-urllib"

STOP_WORDS = set(
    "la cua va cac mot nhung cho toi minh tao may gi nao the de co duoc hay o trong tren duoi voi ve".split()
)


def normalize_vietnamese(text: str) -> str:
    """Chuyển văn bản tiếng Việt sang dạng không dấu để so khớp linh hoạt."""
    text = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def extract_tokens(text: str) -> set:
    """Tách các từ khoá có nghĩa sau khi lọc từ dừng."""
    norm = normalize_vietnamese(text)
    words = re.findall(r"[a-z0-9]+", norm)
    return set(words) - STOP_WORDS


def get_ssl_context():
    """Tạo SSL context tương thích với môi trường Linux TrimUI."""
    ctx = ssl.create_default_context()
    # Kiểm tra CA certs nếu có sẵn trong pylibs của app
    ca_candidates = [
        Path(__file__).resolve().parent.parent / "pylibs" / "certifi" / "cacert.pem",
        Path("/etc/ssl/certs/ca-certificates.crt"),
    ]
    for ca in ca_candidates:
        if ca.is_file():
            try:
                ctx.load_verify_locations(cafile=str(ca))
                return ctx
            except Exception:
                pass
    # Nếu không có file chứng chỉ chuẩn trên hệ điều hành nhúng, bỏ qua xác thực hostname để không lỗi kết nối
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class KnowledgeBase:
    """Tra cứu tài liệu lưu sẵn trong máy (thư mục knowledge/documents)."""

    def __init__(self, root: Path | None = None):
        if root is None:
            self.root = Path(__file__).resolve().parent / "knowledge" / "documents"
        else:
            self.root = Path(root)

    def search(self, question: str, limit: int = 3) -> list[dict]:
        query_tokens = extract_tokens(question)
        if not query_tokens:
            return []

        chunks = []
        if not self.root.exists():
            return []

        for path in sorted(self.root.rglob("*")):
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in (".txt", ".md"):
                continue
            try:
                content = path.read_text(encoding="utf-8-sig", errors="ignore")
            except Exception:
                continue

            # Lấy tiêu đề tài liệu (dòng bắt đầu bằng # đầu tiên)
            first_line = content.splitlines()[0] if content.splitlines() else ""
            doc_title = first_line.lstrip("#").strip() if first_line.startswith("#") else ""

            # Tách thành các đoạn văn bản (paragraphs)
            for paragraph in re.split(r"\n\s*\n", content):
                paragraph = paragraph.strip()
                if not paragraph:
                    continue
                # Chia nhỏ đoạn quá dài
                for start in range(0, len(paragraph), 800):
                    body = paragraph[start : start + 1000].strip()
                    if body:
                        doc_name = str(path.relative_to(self.root))
                        combined_text = f"{doc_title} {body}" if doc_title else body
                        chunks.append((doc_name, body, extract_tokens(combined_text), combined_text.lower()))

        if not chunks:
            return []

        total_docs = len(chunks)
        ranked = []
        q_norm = normalize_vietnamese(question)
        for source, body, doc_words, combined_lower in chunks:
            overlap = query_tokens & doc_words
            if not overlap:
                continue
            # Tính điểm BM25 / TF-IDF xấp xỉ
            score = 0.0
            for term in overlap:
                doc_freq = sum(1 for _, _, words, _ in chunks if term in words)
                idf = math.log(1 + (total_docs - doc_freq + 0.5) / (doc_freq + 0.5))
                score += max(0.2, idf)

            coverage = len(overlap) / len(query_tokens)
            
            # Thưởng điểm nếu có cụm từ chính xác (exact phrase matching)
            phrase_bonus = 1.0
            for i in range(len(question.split()) - 1):
                pair = " ".join(normalize_vietnamese(question).split()[i : i + 2])
                if pair in normalize_vietnamese(combined_lower):
                    phrase_bonus += 0.5

            final_score = (score * phrase_bonus * (coverage ** 1.2)) / (1 + len(doc_words) / 120)
            ranked.append({
                "source": source,
                "text": body,
                "coverage": round(coverage, 3),
                "score": round(final_score, 3),
            })

        ranked.sort(key=lambda x: x["score"], reverse=True)
        return ranked[:limit]


class InternetKnowledge:
    """Tự động tìm kiếm và thu thập thông tin từ Internet."""

    @staticmethod
    def fetch_url(url: str, timeout: int = 8, headers: dict | None = None) -> bytes:
        hdrs = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; Handheld) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        if headers:
            hdrs.update(headers)
        req = Request(url, headers=hdrs)
        ctx = get_ssl_context()
        # Wi-Fi máy cầm tay hay rớt vài giây → thử lại 1 lần với lỗi mạng/5xx
        # (đo 2026-10-08: cả loạt câu hỏi thất bại khi Wi-Fi chập chờn). Lỗi 4xx thì không thử lại.
        for attempt in range(2):
            try:
                with urlopen(req, timeout=timeout, context=ctx) as resp:
                    return resp.read(524288)  # Tối đa 512KB để bảo vệ RAM máy
            except HTTPError as e:
                if e.code < 500 or attempt:
                    raise
            except (URLError, OSError):
                if attempt:
                    raise
            time.sleep(0.8)

    @classmethod
    def search_weather(cls, query: str) -> dict | None:
        """Nhận diện câu hỏi thời tiết và tra cứu trực tuyến."""
        norm = normalize_vietnamese(query)
        if not any(k in norm for k in ("thoi tiet", "nhiet do", "troi mua", "troi nang", "do am")):
            return None

        # Bản đồ địa danh Việt Nam phổ biến
        locations = {
            "ha noi": "Hanoi",
            "hanoi": "Hanoi",
            "sai gon": "Ho_Chi_Minh_City",
            "ho chi minh": "Ho_Chi_Minh_City",
            "tp hcm": "Ho_Chi_Minh_City",
            "tphcm": "Ho_Chi_Minh_City",
            "da nang": "Da_Nang",
            "hai phong": "Hai_Phong",
            "can tho": "Can_Tho",
            "hue": "Hue",
            "nha trang": "Nha_Trang",
            "da lat": "Da_Lat",
            "vung tau": "Vung_Tau",
            "quang ninh": "Ha_Long",
            "quy nhon": "Quy_Nhon",
        }
        target_city = "Hanoi"  # Mặc định
        city_display = "Hà Nội"

        for k, v in locations.items():
            if k in norm:
                target_city = v
                city_display = k.title()
                break

        try:
            url = f"https://wttr.in/{target_city}?format=j1"
            data = json.loads(cls.fetch_url(url, timeout=6).decode("utf-8", errors="ignore"))
            curr = data.get("current_condition", [{}])[0]
            temp_c = curr.get("temp_C", "N/A")
            humidity = curr.get("humidity", "N/A")
            desc = curr.get("weatherDesc", [{}])[0].get("value", "")

            # Dịch mô tả thời tiết sang tiếng Việt thông dụng
            desc_trans = {
                "Sunny": "Trời nắng đẹp",
                "Clear": "Trời quang đãng",
                "Partly cloudy": "Có mây rải rác",
                "Cloudy": "Trời nhiều mây",
                "Overcast": "Trời âm u",
                "Patchy rain possible": "Có thể có mưa vài nơi",
                "Light rain": "Mưa nhỏ rải rác",
                "Moderate rain": "Có mưa vừa",
                "Heavy rain": "Mưa to",
                "Thundery outbreaks possible": "Có thể có dông sét",
            }.get(desc, desc)

            reply = f"Thời tiết tại {city_display} hiện tại: nhiệt độ khoảng {temp_c}°C, độ ẩm {humidity}%. {desc_trans}."
            return {
                "source": "wttr.in",
                "type": "weather",
                "answer": reply,
            }
        except Exception:
            return None

    @classmethod
    def check_datetime(cls, query: str) -> dict | None:
        """Nhận diện câu hỏi về thời gian thực tế."""
        norm = normalize_vietnamese(query)
        if any(k in norm for k in ("may gio", "gio hien tai", "bay gio la", "ngay may", "thu may", "nam nay la nam")):
            now = datetime.datetime.now()
            weekdays = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
            thu = weekdays[now.weekday()]
            time_str = f"Bây giờ là {now.hour} giờ {now.minute:02d} phút, {thu}, ngày {now.day} tháng {now.month} năm {now.year}."
            return {
                "source": "Đồng hồ hệ thống",
                "type": "time",
                "answer": time_str,
            }
        return None

    @classmethod
    def calculate_math(cls, query: str) -> dict | None:
        """Nhận diện và tính toán các phép toán số học cơ bản."""
        norm = normalize_vietnamese(query).replace("x", "*").replace("nhan", "*").replace("chia", "/")
        norm = norm.replace("cong", "+").replace("tru", "-").replace("bang may", "").replace("=", "")
        m = re.search(r"(\d+(?:\.\d+)?)\s*([\+\-\*\/])\s*(\d+(?:\.\d+)?)", norm)
        if m:
            n1 = float(m.group(1))
            op = m.group(2)
            n2 = float(m.group(3))
            try:
                if op == "+":
                    res = n1 + n2
                elif op == "-":
                    res = n1 - n2
                elif op == "*":
                    res = n1 * n2
                elif op == "/":
                    if n2 == 0:
                        return {"source": "Tính toán", "type": "math", "answer": "Không thể chia cho số 0."}
                    res = n1 / n2
                res_str = f"{res:.2f}".rstrip("0").rstrip(".") if isinstance(res, float) else str(res)
                return {
                    "source": "Máy tính số học",
                    "type": "math",
                    "answer": f"Kết quả phép tính {m.group(1)} {op} {m.group(3)} là: {res_str}.",
                }
            except Exception:
                pass
        return None

    # Từ để hỏi / từ đệm: làm lệch kết quả tìm Wikipedia
    # (đã gặp: "Núi Phú Sĩ cao bao nhiêu" → bài "Dãy núi Ba Vì").
    _QUESTION_WORDS = re.compile(
        r"\b(là gì|là ai|là sao|ở đâu|nằm ở đâu|khi nào|bao giờ|bao nhiêu|bao xa|bao lâu|"
        r"như thế nào|thế nào|ra sao|tại sao|vì sao|có phải|cho tôi biết|hãy|nói về|"
        r"giới thiệu|về|của|là|có|không|được|nào|gì|ai|nhỉ|vậy|thế|à|ạ|nhé)\b",
        re.IGNORECASE,
    )

    @classmethod
    def _wiki_keywords(cls, query: str) -> str:
        q = cls._QUESTION_WORDS.sub(" ", query)
        q = re.sub(r"[?!.,;:]", " ", q)
        return re.sub(r"\s+", " ", q).strip() or query

    @classmethod
    def search_wikipedia(cls, query: str) -> dict | None:
        """Tìm kiếm Wikipedia tiếng Việt và lấy đoạn tóm tắt đầy đủ."""
        try:
            # 1. Tìm trang liên quan nhất (bỏ từ để hỏi trước khi tìm).
            # Từ thừa cuối câu ("cao", "được xây") làm Wikipedia không ra gì →
            # thử lại tối đa 2 lần, mỗi lần bớt 1 từ cuối (giữ ít nhất 2 từ).
            words = cls._wiki_keywords(query).split()
            best = None
            for cut in range(3):
                if cut and len(words) - cut < 2:
                    break
                keywords = " ".join(words[: len(words) - cut])
                # 1 request = tìm + lấy tóm tắt (generator=search), thay vì 2 request.
                # Wikimedia giới hạn tần suất (đã gặp HTTP 429) → càng ít request càng tốt.
                params = urlencode({
                    "action": "query",
                    "generator": "search",
                    "gsrsearch": keywords[:200],
                    "gsrlimit": 3,
                    "prop": "extracts",
                    "exintro": 1,
                    "explaintext": 1,
                    "exlimit": 3,
                    "format": "json",
                    "utf8": 1,
                })
                raw = cls.fetch_url(f"https://vi.wikipedia.org/w/api.php?{params}", timeout=7,
                                    headers={"User-Agent": WIKI_USER_AGENT})
                data = json.loads(raw.decode("utf-8", errors="ignore"))
                pages = sorted(data.get("query", {}).get("pages", {}).values(),
                               key=lambda p: p.get("index", 99))

                # Chọn bài có tên trùng nhiều từ khoá nhất (hoà thì theo thứ hạng tìm kiếm);
                # tên không trùng từ nào → bỏ, vì câu trả lời sai sẽ bị tự học lưu vĩnh viễn.
                # Phải khớp chặt: ≥1/3 từ khoá câu hỏi VÀ ≥60% từ trong tên bài.
                # Lỏng hơn thì câu hỏi vui ("nếu chó biết nói…") ra bài "Chó" — để Gemini trả lời.
                kw_tokens = extract_tokens(keywords)
                best_score = 0
                for page in pages:
                    title_tokens = extract_tokens(page.get("title", ""))
                    score = len(kw_tokens & title_tokens)
                    if not score or not page.get("extract", "").strip():
                        continue
                    if score / max(1, len(kw_tokens)) < 0.34 or score / max(1, len(title_tokens)) < 0.6:
                        continue
                    if score > best_score:
                        best, best_score = page, score
                if best:
                    break
            if not best:
                return None

            # 2. Tóm tắt mở đầu của bài đã chọn
            best_title = best["title"]
            for page in (best,):
                extract = page.get("extract", "").strip()
                if extract:
                    # Lọc sạch các ký tự tham chiếu như [1], [cần dẫn nguồn]
                    clean_text = re.sub(r"\[\d+\]|\[cần dẫn nguồn\]", "", extract).strip()
                    # Cắt ngắn 2-4 câu đầu tiên phù hợp màn hình máy game
                    sentences = re.split(r"(?<=[.!?])\s+", clean_text)
                    summary = " ".join(sentences[:3]).strip()
                    if not summary.endswith("."):
                        summary += "."
                    return {
                        "source": f"Wikipedia tiếng Việt ({best_title})",
                        "type": "wikipedia",
                        "answer": summary,
                    }
        except Exception:
            pass
        return None

    # ---- Gemini: trả lời câu hỏi vui / câu Wikipedia không có ----
    # Key của người dùng (aistudio.google.com) đặt trong local_ai/gemini_key.txt (1 dòng)
    # hoặc env GEMINI_API_KEY. KHÔNG ghi key ra log.
    GEMINI_KEY_FILE = Path(__file__).resolve().parent / "gemini_key.txt"
    # Đo 2026-10-08 bằng key thật: flash-lite-latest ~3,7s, không tốn token "suy nghĩ";
    # flash-latest ~7,6s (tự suy nghĩ ~430 token). gemini-2.5-flash đã ngừng cho người dùng mới.
    # Dùng alias "-latest" để Google tự trỏ sang bản mới, khỏi sửa code khi model cũ ngừng.
    GEMINI_MODELS = ("gemini-flash-lite-latest", "gemini-flash-latest")
    GEMINI_SYSTEM = (
        "Bạn là trợ lý AI vui tính chạy trên máy chơi game cầm tay TrimUI Brick Pro. "
        "Luôn trả lời bằng tiếng Việt, ngắn gọn 2-3 câu, thân thiện, dí dỏm. "
        "Câu hỏi vô nghĩa hoặc hỏi cho vui vẫn trả lời thoả đáng, sáng tạo. "
        "Câu trả lời sẽ được đọc thành giọng nói: không dùng markdown, ký hiệu, danh sách hay emoji."
    )

    @classmethod
    def _gemini_key(cls) -> str:
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            try:
                # utf-8-sig: Notepad Windows hay thêm BOM vô hình ở đầu → key sai 1 ký tự
                key = cls.GEMINI_KEY_FILE.read_text(encoding="utf-8-sig").strip().splitlines()[0].strip()
            except Exception:
                key = ""
        return key

    @classmethod
    def ask_gemini(cls, query: str) -> dict | None:
        cls.last_ai_error = ""
        key = cls._gemini_key()
        if not key:
            return None
        body = json.dumps({
            "systemInstruction": {"parts": [{"text": cls.GEMINI_SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": query[:500]}]}],
            # 1024 token: model có "suy nghĩ" tiêu token trước khi trả lời — 300 từng hết
            # sạch (MAX_TOKENS, không có chữ). Độ ngắn của câu trả lời do prompt quyết định.
            # Không gửi thinkingConfig: model mới bỏ qua thinkingBudget=0 và từ chối thinkingLevel=minimal.
            "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.8},
        }).encode("utf-8")
        for model in cls.GEMINI_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            try:
                req = Request(url, data=body, headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": key,
                    "User-Agent": WIKI_USER_AGENT,
                })
                with urlopen(req, timeout=15, context=get_ssl_context()) as resp:
                    data = json.loads(resp.read(262144).decode("utf-8", errors="ignore"))
                cand = (data.get("candidates") or [{}])[0]
                parts = cand.get("content", {}).get("parts", [])
                text = " ".join(p.get("text", "") for p in parts).strip()
                text = re.sub(r"[*#_`>]+", "", text)  # bỏ markdown sót lại (đọc thành giọng nói)
                text = re.sub(r"\s+", " ", text).strip()
                if text:
                    return {"source": "Gemini (Google AI)", "type": "ai", "answer": text}
                # Rỗng (MAX_TOKENS / SAFETY…) → thử model kế tiếp
                cls.last_ai_error = f"rong:{cand.get('finishReason', '?')}"
                continue
            except HTTPError as e:
                cls.last_ai_error = f"HTTP {e.code}"
                # 404 model ngừng, 429 hết lượt riêng model đó, 5xx quá tải → thử model kế tiếp.
                # 400/401/403 (key sai) thì model nào cũng vậy → dừng.
                if e.code in (404, 429) or e.code >= 500:
                    continue
                return None
            except Exception as e:
                cls.last_ai_error = type(e).__name__
                return None
        return None

    last_ai_error = ""

    @classmethod
    def search_duckduckgo(cls, query: str) -> dict | None:
        """Tra cứu nhanh qua DuckDuckGo Instant Answer API."""
        try:
            url = f"https://api.duckduckgo.com/?q={quote(query)}&format=json&no_html=1&skip_disambig=1"
            raw = cls.fetch_url(url, timeout=5)
            data = json.loads(raw.decode("utf-8", errors="ignore"))
            abstract = data.get("AbstractText", "").strip()
            heading = data.get("Heading", "")
            if abstract:
                return {
                    "source": f"DuckDuckGo ({heading or 'Trực tuyến'})",
                    "type": "internet",
                    "answer": abstract,
                }
        except Exception:
            pass
class UserHabitLearner:
    """Quản lý tần suất câu hỏi của người dùng và tự động lưu/cập nhật thông tin hay hỏi về máy."""

    def __init__(self, base_dir: Path | None = None):
        if base_dir is None:
            self.base_dir = Path(__file__).resolve().parent / "knowledge"
        else:
            self.base_dir = Path(base_dir)
        self.stats_file = self.base_dir / "user_stats.json"
        self.learned_doc_file = self.base_dir / "documents" / "kien_thuc_da_hoc.md"
        self.stats = self._load_stats()

    def _load_stats(self) -> dict:
        if self.stats_file.is_file():
            try:
                return json.loads(self.stats_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        # Thống kê mất/hỏng (đã gặp file 0 byte) → khôi phục từ kien_thuc_da_hoc.md.
        # Nếu không, lần lưu tới _rebuild_learned_doc() sẽ ghi đè và XOÁ kiến thức cũ.
        return self._recover_from_learned_doc()

    def _recover_from_learned_doc(self) -> dict:
        stats = {}
        try:
            text = self.learned_doc_file.read_text(encoding="utf-8")
        except Exception:
            return stats
        for block in re.split(r"^## ", text, flags=re.M)[1:]:
            q = block.split("\n", 1)[0].strip()
            ans = re.search(r"^- Trả lời:\s*(.*)$", block, re.M)
            src = re.search(r"^- Nguồn dữ liệu:\s*(.*?)\s*\(Đã hỏi (\d+) lần, cập nhật:\s*([^)]*)\)", block, re.M)
            key = normalize_vietnamese(q).strip()
            if not key or not ans:
                continue
            stats[key] = {
                "question": q,
                "count": int(src.group(2)) if src else 2,
                "first_asked": src.group(3) if src else "",
                "last_asked": src.group(3) if src else "",
                "is_saved": True,
                "last_answer": ans.group(1).strip(),
                "source": src.group(1) if src else "Internet",
                "type": "internet",
            }
        return stats

    @staticmethod
    def _atomic_write(path: Path, content: str):
        """Ghi an toàn trên thẻ FAT32: file tạm + fsync + replace.

        write_text() cắt file về 0 byte rồi mới ghi; bị tắt ngang (MENU, hết pin, reset)
        là mất sạch dữ liệu đã học (đã gặp user_stats.json 0 byte trên máy).
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def _save_stats(self):
        try:
            self._atomic_write(self.stats_file, json.dumps(self.stats, ensure_ascii=False, indent=2))
        except Exception:
            pass

    def is_saved(self, question: str) -> bool:
        key = normalize_vietnamese(question).strip()
        return bool(self.stats.get(key, {}).get("is_saved", False))

    def record_and_evaluate(self, question: str, answer_info: dict) -> tuple[int, bool]:
        """Ghi nhận số lần hỏi. Nếu hỏi từ 2 lần trở lên -> Tự động lưu hoặc cập nhật vào máy."""
        key = normalize_vietnamese(question).strip()
        if not key:
            return 1, False

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = self.stats.get(key)
        newly_saved = False

        if not entry:
            entry = {
                "question": question,
                "count": 1,
                "first_asked": now_str,
                "last_asked": now_str,
                "is_saved": False,
                "last_answer": answer_info.get("answer", ""),
                "source": answer_info.get("source", ""),
                "type": answer_info.get("type", ""),
            }
            self.stats[key] = entry
            self._save_stats()
            return 1, False

        # Người dùng hỏi lại câu này (hoặc chủ đề này)
        entry["count"] += 1
        entry["last_asked"] = now_str
        count = entry["count"]

        ans_type = answer_info.get("type", "")
        ans_text = answer_info.get("answer", "")

        # Cập nhật câu trả lời mới nhất nếu lấy từ nguồn hợp lệ
        if ans_text and ans_type in ("wikipedia", "internet", "weather"):
            entry["last_answer"] = ans_text
            entry["source"] = answer_info.get("source", "")
            entry["type"] = ans_type

        # NGƯỠNG: Hỏi từ 2 lần trở lên -> Tự động lưu thành tài liệu nội bộ vĩnh viễn
        if count >= 2:
            if not entry.get("is_saved", False) and ans_type in ("wikipedia", "internet", "weather"):
                entry["is_saved"] = True
                newly_saved = True
            self._rebuild_learned_doc()

        self._save_stats()
        return count, newly_saved

    def _rebuild_learned_doc(self):
        """Tái tạo tài liệu kien_thuc_da_hoc.md với các mục người dùng hay hỏi."""
        try:
            self.learned_doc_file.parent.mkdir(parents=True, exist_ok=True)
            lines = [
                "# Cẩm nang tri thức đã học từ thói quen người dùng\n",
                "Tài liệu này được máy TrimUI tự động lưu lại từ các câu hỏi mà bạn hay quan tâm.\n\n",
            ]
            for _, entry in sorted(self.stats.items(), key=lambda x: x[1].get("count", 0), reverse=True):
                if entry.get("is_saved"):
                    q = entry["question"]
                    ans = entry["last_answer"]
                    src = entry.get("source", "Internet")
                    cnt = entry.get("count", 2)
                    upd = entry.get("last_asked", "")
                    lines.append(f"## {q}\n")
                    lines.append(f"- Câu hỏi hay gặp: {q}\n")
                    lines.append(f"- Trả lời: {ans}\n")
                    lines.append(f"- Nguồn dữ liệu: {src} (Đã hỏi {cnt} lần, cập nhật: {upd})\n\n")

            self._atomic_write(self.learned_doc_file, "".join(lines))
        except Exception:
            pass


def generate_answer(question: str, root_dir: Path | None = None, allow_internet: bool = True) -> dict:
    """Hàm trung tâm: Phân tích, tra cứu, tự học và lưu trữ tri thức theo thói quen."""
    question = (question or "").strip()
    if not question:
        return {
            "status": "empty",
            "question": "",
            "answer": "Xin hãy nhập câu hỏi.",
            "source": "Hệ thống",
            "type": "system",
        }

    learner = UserHabitLearner(root_dir.parent if root_dir else None)

    # 1. Các câu hỏi đặc biệt: Thời tiết, Thời gian & Toán học
    weather_res = InternetKnowledge.search_weather(question) if allow_internet else None
    if weather_res:
        count, newly_saved = learner.record_and_evaluate(question, weather_res)
        if newly_saved:
            weather_res["source"] += " [Đã lưu về máy do hay hỏi]"
        weather_res["ask_count"] = count
        return {"status": "ok", "question": question, **weather_res}

    dt_res = InternetKnowledge.check_datetime(question)
    if dt_res:
        return {"status": "ok", "question": question, **dt_res}

    math_res = InternetKnowledge.calculate_math(question)
    if math_res:
        return {"status": "ok", "question": question, **math_res}

    # 2. Tra cứu tài liệu nội bộ máy TrimUI (bao gồm cả tài liệu đã học kien_thuc_da_hoc.md)
    kb = KnowledgeBase(root_dir)
    hits = kb.search(question)

    q_tokens = extract_tokens(question)
    min_coverage = 1.0 if len(q_tokens) <= 2 else 0.65

    if hits and hits[0]["coverage"] >= min_coverage:
        top_hit = hits[0]
        text = top_hit["text"]
        doc_source = top_hit["source"]
        # Mục trong kien_thuc_da_hoc.md có dạng "## câu hỏi / - Câu hỏi hay gặp / - Trả lời: ..."
        # → chỉ lấy phần trả lời, tránh đọc to cả tiêu đề markdown.
        if "kien_thuc_da_hoc" in doc_source:
            m = re.search(r"-\s*Trả lời:\s*(.+)", text)
            if m:
                text = m.group(1)
        sentences = re.split(r"(?<=[.!?])\s+", text)
        clean_ans = " ".join(sentences[:3]).strip()
        
        # Nhận diện nếu thông tin lấy từ cẩm nang đã học
        source_label = "Tài liệu máy đã học" if "kien_thuc_da_hoc" in doc_source else f"Tài liệu máy ({doc_source})"

        res = {
            "status": "ok",
            "question": question,
            "answer": clean_ans,
            "source": source_label,
            "type": "local",
            "coverage": top_hit["coverage"],
        }
        count, _ = learner.record_and_evaluate(question, res)
        res["ask_count"] = count
        return res

    # 3. Tra cứu trên Internet nếu được phép
    if allow_internet:
        # 3.1. Wikipedia tiếng Việt
        wiki_res = InternetKnowledge.search_wikipedia(question)
        if wiki_res:
            count, newly_saved = learner.record_and_evaluate(question, wiki_res)
            if newly_saved:
                wiki_res["source"] += " [Đã lưu về máy do hay hỏi]"
            wiki_res["ask_count"] = count
            return {"status": "ok", "question": question, **wiki_res}

        # 3.2. DuckDuckGo / Internet
        ddg_res = InternetKnowledge.search_duckduckgo(question)
        if ddg_res:
            count, newly_saved = learner.record_and_evaluate(question, ddg_res)
            if newly_saved:
                ddg_res["source"] += " [Đã lưu về máy do hay hỏi]"
            ddg_res["ask_count"] = count
            return {"status": "ok", "question": question, **ddg_res}

        # 3.3. Gemini (key người dùng): câu hỏi vui / vô nghĩa / Wikipedia không có.
        # Không đưa vào tự học: câu vui nên có câu trả lời mới mỗi lần.
        ai_res = InternetKnowledge.ask_gemini(question)
        if ai_res:
            return {"status": "ok", "question": question, **ai_res}

    # 4. Đã BỎ bước "tài liệu gần giống" (khớp lỏng): toàn trả lời sai — "Vịnh Hạ Long ở đâu"
    #    ra hướng dẫn bấm nút, "nếu chó biết nói…" ra bài Trái Đất kèm markdown.
    # 5. Đáp vui thay cho "Không tìm thấy"
    return {
        "status": "not_found",
        "question": question,
        "answer": _fallback_reply(question, allow_internet),
        "source": "Trợ lý cục bộ",
        "type": "none",
    }


_FALLBACK_REPLIES = (
    "Câu hỏi này hay đấy, nhưng mình chịu thua rồi! Bạn hỏi cách khác thử xem nhé.",
    "Ồ, câu này làm mình bối rối quá. Có lẽ phải hỏi một nhà thông thái thật sự mới biết!",
    "Mình đã lục tung trí nhớ mà chưa thấy câu trả lời. Bạn kể thêm chút để mình hiểu ý nhé?",
    "Câu này nghe như mật mã bí ẩn! Mình chưa giải được, bạn gợi ý thêm được không?",
)


def _fallback_reply(question: str, allow_internet: bool) -> str:
    import random
    msg = random.choice(_FALLBACK_REPLIES)
    if not allow_internet:
        return msg + " Hiện đang không có mạng nên mình chỉ tra được tài liệu trong máy."
    if not InternetKnowledge._gemini_key():
        return msg + " Mẹo: thêm key Gemini vào máy để mình trả lời được cả những câu hỏi vui."
    if InternetKnowledge.last_ai_error in ("HTTP 400", "HTTP 401", "HTTP 403"):
        return msg + " Key Gemini trong máy có vẻ không hợp lệ, bạn kiểm tra lại file gemini_key.txt nhé."
    if InternetKnowledge.last_ai_error == "HTTP 429":
        return msg + " Hôm nay đã dùng hết lượt Gemini miễn phí, mai thử lại nhé."
    if InternetKnowledge.last_ai_error:
        return msg + " Mạng hoặc dịch vụ AI đang trục trặc, bạn thử lại sau chút nhé."
    return msg


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Trợ lý AI & Tra cứu tài liệu TrimUI")
    parser.add_argument("question", nargs="?", default="cách thoát game trên trimui")
    parser.add_argument("--no-internet", action="store_true", help="Không tìm kiếm trên Internet")
    args = parser.parse_args()

    result = generate_answer(args.question, allow_internet=not args.no_internet)
    print(json.dumps(result, ensure_ascii=False, indent=2))

