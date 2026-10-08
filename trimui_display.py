"""Handheld Framebuffer Viewport for TrimUI Brick Pro.
Hỗ trợ hiển thị 2 chế độ hoán đổi & bổ trợ: Server Đám Mây và Trợ Lý Cục Bộ & Web.
"""

import asyncio
import ctypes
import fcntl
import math
import mmap
import os
import unicodedata
from PIL import Image, ImageDraw, ImageFont


class Bitfield(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint32) for n in ("offset", "length", "msb_right")]


class VarInfo(ctypes.Structure):
    _fields_ = (
        [(n, ctypes.c_uint32) for n in ("xres", "yres", "xres_virtual", "yres_virtual", "xoffset", "yoffset", "bits_per_pixel", "grayscale")]
        + [(n, Bitfield) for n in ("red", "green", "blue", "transp")]
        + [(n, ctypes.c_uint32) for n in ("nonstd", "activate", "height", "width", "accel_flags", "pixclock", "left_margin", "right_margin", "upper_margin", "lower_margin", "hsync_len", "vsync_len", "sync", "vmode", "rotate", "colorspace")]
        + [("reserved", ctypes.c_uint32 * 4)]
    )


class FixInfo(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_char * 16),
        ("smem_start", ctypes.c_ulong),
        ("smem_len", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("type_aux", ctypes.c_uint32),
        ("visual", ctypes.c_uint32),
        ("xpanstep", ctypes.c_uint16),
        ("ypanstep", ctypes.c_uint16),
        ("ywrapstep", ctypes.c_uint16),
        ("line_length", ctypes.c_uint32),
        ("mmio_start", ctypes.c_ulong),
        ("mmio_len", ctypes.c_uint32),
        ("accel", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint16),
        ("reserved", ctypes.c_uint16 * 2),
    ]


class Framebuffer:
    def __init__(self):
        self.fd = os.open("/dev/fb0", os.O_RDWR)
        self.memory = None
        try:
            self.var, self.fix = VarInfo(), FixInfo()
            fcntl.ioctl(self.fd, 0x4600, self.var)
            fcntl.ioctl(self.fd, 0x4602, self.fix)
            v = self.var
            if v.bits_per_pixel != 32 or any(getattr(v, n).length != 8 for n in ("red", "green", "blue")):
                raise RuntimeError("Unsupported framebuffer pixel format")
            if any(getattr(v, n).msb_right for n in ("red", "green", "blue", "transp")):
                raise RuntimeError("Unsupported framebuffer bit ordering")
            offsets = (v.red.offset, v.green.offset, v.blue.offset)
            self.rawmode = {(16, 8, 0): "BGRA", (0, 8, 16): "RGBA"}.get(offsets)
            if self.rawmode is None:
                raise RuntimeError("Unsupported framebuffer channel offsets")
            self.width, self.height = v.xres, v.yres
            self.memory = mmap.mmap(self.fd, self.fix.smem_len, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
            self.validate_bounds()
        except BaseException:
            self.close()
            raise

    def validate_bounds(self):
        v = self.var
        end = (v.yoffset + self.height - 1) * self.fix.line_length + (v.xoffset + self.width) * 4
        if not self.width or not self.height or end > self.fix.smem_len or (v.xoffset + self.width) * 4 > self.fix.line_length:
            raise RuntimeError("Framebuffer dimensions exceed mapped memory")

    def present(self, image, box=None):
        fcntl.ioctl(self.fd, 0x4600, self.var)
        self.validate_bounds()
        left, top, right, bottom = box or (0, 0, self.width, self.height)
        if not (0 <= left < right <= self.width and 0 <= top < bottom <= self.height):
            raise ValueError("Invalid framebuffer update region")
        region = image.crop((left, top, right, bottom)) if box else image
        raw = region.convert("RGBA").tobytes("raw", self.rawmode)
        rowbytes = (right - left) * 4
        # Tối ưu: khi vùng ghi chiếm trọn bề rộng và stride khít (line_length == rowbytes)
        # thì ghi NGUYÊN khối một lần thay vì lặp 768 dòng (nhẹ CPU A53 gấp nhiều lần).
        if self.var.xoffset == 0 and left == 0 and rowbytes == self.fix.line_length:
            base = (self.var.yoffset + top) * self.fix.line_length
            self.memory[base : base + len(raw)] = raw
        else:
            for y in range(bottom - top):
                start = (self.var.yoffset + top + y) * self.fix.line_length + (self.var.xoffset + left) * 4
                self.memory[start : start + rowbytes] = raw[y * rowbytes : (y + 1) * rowbytes]

    def close(self):
        if self.memory is not None:
            self.memory.close()
            self.memory = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


_SIG_PARTS = ("c1b4ee894a5acd2a", "573b1c0add62cac4", "0a16806567fb12e6", "ce77fa46c55a353c")
_TAMPER_TEXT = "Phiên bản này đã bị chỉnh sửa trái phép (chữ ký tác giả không hợp lệ)."


def _verify_signature() -> list:
    """Kiểm tra chữ ký tác giả (độc lập với trimui_run.py). Lỗi bất kỳ = bị sửa."""
    import hashlib
    import trimui_signature as sig

    data = sig.raw_bytes()
    if hashlib.sha256(data).hexdigest() != "".join(_SIG_PARTS):
        raise RuntimeError(_TAMPER_TEXT)
    sig.check_authors_file(os.path.dirname(os.path.abspath(__file__)))
    return data.decode("utf-8").split("\n")


class TrimuiViewManager:
    def __init__(self, event_bus, task_manager=None):
        self.bus, self.tasks = event_bus, task_manager
        self.fb = Framebuffer()
        try:
            self.sig_lines = _verify_signature()
        except Exception:
            self._show_tamper_and_exit()
        self.running = False
        self.status, self.connected, self.text = "Sẵn sàng — bấm A để nói", False, ""
        self.auto, self.emotion, self.music, self.last_button = False, "neutral", "", ""
        self.mic = {"enabled": False, "rms": 0.0, "peak": 0.0, "clipped": False, "overflows": 0}
        self.recognized = ""
        self._canvas = None
        self.meter_dirty = False
        self.dirty = True

        # Chế độ hoạt động: "server" (Server Đám Mây) hoặc "local" (Cục Bộ & Web)
        self.mode = "server"
        self.local_question = "Cách thoát game và lưu game trên máy TrimUI"
        self.local_source = ""
        self.supplement_info = ""

        font_path = os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans.ttf")
        self.font = ImageFont.truetype(font_path, 30)
        self.titlefont = ImageFont.truetype(font_path, 42)
        self.buttonfont = ImageFont.truetype(font_path, 22)
        self.badgefont = ImageFont.truetype(font_path, 24)

        self.bus.on("trimui_button", self.on_button)
        self.bus.on("trimui_mic", self.on_mic)
        self.bus.on("incoming_json", self.on_message)
        self.bus.on("trimui_mode_change", self.on_mode_change)
        self.bus.on("trimui_local_update", self.on_local_update)

    async def on_mode_change(self, new_mode):
        self.mode = str(new_mode)
        self.last_button = "Y"
        self.dirty = True

    async def on_local_update(self, data):
        if isinstance(data, dict):
            if "question" in data:
                self.local_question = unicodedata.normalize("NFC", str(data["question"]))
            if "answer" in data:
                self.text = unicodedata.normalize("NFC", str(data["answer"]))
            if "source" in data:
                self.local_source = unicodedata.normalize("NFC", str(data["source"]))
            if "status" in data:
                self.status = str(data["status"])
            if "supplement" in data:
                self.supplement_info = unicodedata.normalize("NFC", str(data["supplement"]))
        self.dirty = True

    async def on_mic(self, data):
        self.mic = data
        self.meter_dirty = True

    async def on_message(self, message):
        if isinstance(message, dict):
            mtype = message.get("type")
            if mtype == "stt":
                self.recognized = unicodedata.normalize("NFC", str(message.get("text", "")))
                self.dirty = True
            elif mtype == "tts":
                # Nhận nội dung text server trả lời
                t = message.get("text")
                if t:
                    self.text = unicodedata.normalize("NFC", str(t))
                    self.dirty = True

    async def on_button(self, data):
        self.last_button = {"305": "A", "304": "B", "308": "X", "307": "Y", "315": "START", "316": "MENU"}.get(
            str(data), str(data)
        )
        self.dirty = True

    def _show_tamper_and_exit(self):
        """Chữ ký bị xoá/sửa: báo trên màn hình rồi thoát (launcher trả về menu)."""
        import time as _time

        try:
            w, h = self.fb.width, self.fb.height
            im = Image.new("RGB", (w, h), (40, 8, 12))
            d = ImageDraw.Draw(im)
            font = ImageFont.truetype(os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans.ttf"), 28)
            d.text((40, h // 2 - 60), "LỖI XÁC THỰC", font=font, fill=(255, 90, 90))
            d.text((40, h // 2), _TAMPER_TEXT, font=font, fill="white")
            self.fb.present(im)
            _time.sleep(5)
        finally:
            self.fb.close()
        raise SystemExit(3)

    def render_splash(self):
        w, h = self.fb.width, self.fb.height
        im = Image.new("RGB", (w, h), (16, 22, 34))
        d = ImageDraw.Draw(im)
        title, author, core = "XIAOZHI AI", self.sig_lines[1], self.sig_lines[2]
        sub = self.sig_lines[0].split("—", 1)[-1].strip()  # "BẢN TRIMUI HYBRID" (tiêu đề đã có tên app)
        y = h // 2 - 120
        d.text(((w - d.textlength(title, font=self.titlefont)) / 2, y), title,
               font=self.titlefont, fill=(70, 220, 185))
        d.text(((w - d.textlength(sub, font=self.badgefont)) / 2, y + 70), sub,
               font=self.badgefont, fill=(175, 190, 210))
        d.line((w * 0.2, y + 120, w * 0.8, y + 120), fill=(60, 80, 100), width=2)
        d.text(((w - d.textlength(author, font=self.font)) / 2, y + 145), author,
               font=self.font, fill="white")
        d.text(((w - d.textlength(core, font=self.buttonfont)) / 2, y + 205), core,
               font=self.buttonfont, fill=(130, 150, 175))
        self.fb.present(im)

    async def start(self, mode="cli"):
        self.running = True
        try:
            # Màn chào có chữ ký tác giả (2 giây)
            self.render_splash()
            await asyncio.sleep(2.0)
            self.dirty = True
            while self.running:
                if self.dirty:
                    self.dirty = False
                    self.render()
                    self.meter_dirty = False
                elif self.meter_dirty and self._canvas is not None and self.mode == "server":
                    self.meter_dirty = False
                    self.render_meter()
                await asyncio.sleep(0.08)
        except Exception:
            if self.tasks:
                self.tasks.request_shutdown()
            raise

    async def close(self):
        self.running = False
        self.bus.off("trimui_button", self.on_button)
        self.bus.off("trimui_mic", self.on_mic)
        self.bus.off("incoming_json", self.on_message)
        self.bus.off("trimui_mode_change", self.on_mode_change)
        self.bus.off("trimui_local_update", self.on_local_update)
        self.fb.close()

    def render(self):
        w, h = self.fb.width, self.fb.height
        im = Image.new("RGB", (w, h), (16, 22, 34))
        d = ImageDraw.Draw(im)

        # 1. Header & Tiêu đề
        d.text((32, 20), "XIAOZHI AI", font=self.titlefont, fill=(70, 220, 185))

        # Huy hiệu chế độ (Mode Badge)
        is_server = self.mode == "server"
        mode_text = "[ CHẾ ĐỘ: SERVER ĐÁM MÂY ]" if is_server else "[ CHẾ ĐỘ: CỤC BỘ & INTERNET ]"
        mode_color = (70, 220, 185) if is_server else (255, 185, 65)
        d.text((340, 30), mode_text, font=self.badgefont, fill=mode_color)

        # 2. Thanh trạng thái & Phím vừa bấm
        status_map = {
            "待命": "Sẵn sàng — bấm A để nói",
            "聆听中...": "Đang thu mic — bấm A để gửi",
            "说话中...": "AI đang trả lời — bấm B để ngắt",
            "未连接": "Chưa kết nối Server",
            "Dang ket noi...": "Đang kết nối Server...",
            "Ket noi that bai - bam START de thu lai": "Lỗi Server — Bấm Y chuyển Cục Bộ",
            "Loi ket noi - bam START de thu lai": "Lỗi Server — Bấm Y chuyển Cục Bộ",
        }
        status_str = status_map.get(self.status, self.status)
        if is_server and self.auto and self.status == "聆听中...":
            status_str = "Đang nghe tự động — nói rồi ngừng để gửi"

        d.text((32, 86), status_str[:60], font=self.font, fill="white")

        mode_sub = ("Tự động" if self.auto else "Thủ công") if is_server else "Độc lập không qua Server"
        btn_info = f" | Vừa bấm: {self.last_button}" if self.last_button else ""
        d.text((32, 132), f"{mode_sub}{btn_info}", font=self.buttonfont, fill=(175, 190, 210))

        d.line((32, 175, w - 32, 175), fill=(50, 68, 92), width=2)

        # 3. Khung Câu hỏi
        if is_server:
            heard = "Bạn nói: " + self.recognized if self.recognized else "Bạn nói: ..."
        else:
            heard = "Câu hỏi: " + self.local_question

        while d.textlength(heard, font=self.buttonfont) > w - 64 and len(heard) > 6:
            heard = heard[:-3] + "..."
        d.text((32, 188), heard, font=self.buttonfont, fill=(70, 220, 185) if is_server else (255, 185, 65))

        # 4. Khung Nội dung Trả lời
        ans_text = self.text
        if not ans_text:
            ans_text = "Chờ phản hồi..." if is_server else "Bấm A để trả lời câu này, bấm X để đổi câu khác."
        if self.local_source and not is_server:
            ans_text = f"{ans_text} [Nguồn: {self.local_source}]"

        words = ans_text.replace("\n", " ").split()
        lines, line = [], ""
        for word in words:
            candidate = (line + " " + word).strip()
            if d.textlength(candidate, font=self.font) > w - 64 and line:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)

        # Hiển thị tối đa 4 dòng câu trả lời
        for i, line_str in enumerate(lines[:4]):
            d.text((32, 230 + i * 40), line_str, font=self.font, fill="white")

        # Khung thông tin bổ trợ (nếu có bổ trợ từ tài liệu máy)
        if self.supplement_info:
            d.text((32, 400), f"Bổ trợ máy: {self.supplement_info[:70]}...", font=self.buttonfont, fill=(100, 200, 255))

        # Vẽ Mic meter nếu ở Server mode
        if is_server:
            self.draw_meter(d, h)

        # 5. Thanh Điều khiển 6 Nút Bấm (Grid 2 cột x 3 hàng)
        recording = is_server and self.status == "聆听中..."
        if is_server:
            controls = [
                ("A", "Chỉ dùng ở thủ công" if self.auto else ("Gửi câu vừa nói" if recording else "Bắt đầu thu mic")),
                ("B", "Ngắt câu trả lời"),
                ("START", "Tắt tự động" if self.auto else "Bật tự động"),
                ("X", "Thử chữ mẫu"),
                ("Y", "ĐỔI SANG CỤC BỘ"),
                ("MENU", "Thoát về menu"),
            ]
        else:
            controls = [
                ("A", "Hỏi câu hiện tại"),
                ("B", "Dừng giọng đọc"),
                ("START", "Gửi câu lên Server"),
                ("X", "Đổi câu hỏi khác"),
                ("Y", "ĐỔI SANG SERVER"),
                ("MENU", "Thoát về menu"),
            ]

        top = h - 250
        card_w = (w - 80) // 2
        for i, (button, label) in enumerate(controls):
            x = 32 + (i % 2) * (card_w + 16)
            y = top + (i // 2) * 70
            d.rounded_rectangle((x, y, x + card_w, y + 60), radius=10, fill=(26, 38, 54))

            badge_w = 110 if button in ("START", "MENU") else 52
            badge_color = (255, 185, 65) if button == "Y" else (70, 220, 185)
            d.rounded_rectangle((x + 8, y + 8, x + 8 + badge_w, y + 52), radius=8, fill=badge_color)

            d.text((x + 16, y + 15), button, font=self.buttonfont, fill=(16, 22, 34))
            d.text((x + badge_w + 18, y + 15), label, font=self.buttonfont, fill="white")

        hint = "Bấm Y bất cứ lúc nào để hoán đổi giữa Server Đám Mây và Cục Bộ & Web"
        d.text((32, h - 30), hint, font=self.buttonfont, fill=(150, 170, 195))

        self._canvas = im
        self.fb.present(im)

    def draw_meter(self, d, h):
        if not self.mic.get("enabled", False):
            d.text((32, h - 280), "Mic đã tắt — bấm A hoặc bật tự động", font=self.buttonfont, fill=(175, 190, 210))
            return
        db = 20 * math.log10(max(self.mic.get("rms", 0), 1e-6))
        clipped = self.mic.get("clipped", False)
        color = (255, 100, 100) if clipped else (70, 220, 185)
        level = max(0, min(1, (db + 60) / 60))
        d.rounded_rectangle((32, h - 275, 272, h - 257), radius=6, fill=(26, 38, 54))
        if level > 0:
            d.rounded_rectangle((32, h - 275, 32 + int(240 * level), h - 257), radius=6, fill=color)
        note = "Quá lớn / méo tiếng" if clipped else ("Nhỏ / yên lặng" if db < -40 else "Có tín hiệu")
        d.text((288, h - 280), f"Mic: {db:.0f} dB • {note}", font=self.buttonfont, fill=color)

    def render_meter(self):
        h, w = self.fb.height, self.fb.width
        d = ImageDraw.Draw(self._canvas)
        d.rectangle((32, h - 290, w - 32, h - 250), fill=(16, 22, 34))
        self.draw_meter(d, h)
        self.fb.present(self._canvas, box=(32, h - 290, w - 32, h - 250))

    def set_status(self, status, connected=True):
        self.status, self.connected, self.dirty = status, connected, True

    def set_chat_text(self, text):
        self.text, self.dirty = unicodedata.normalize("NFC", text or ""), True

    def set_music_line(self, text):
        self.music, self.dirty = text, True

    def set_emotion(self, emotion):
        self.emotion, self.dirty = emotion, True

    def set_auto_mode(self, auto_mode):
        self.auto, self.dirty = auto_mode, True

    def set_button_text(self, text):
        pass

    def is_auto_mode(self):
        return self.auto

    @property
    def is_running(self):
        return self.running
