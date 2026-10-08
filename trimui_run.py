"""Bộ chạy Xiaozhi AI cho TrimUI Brick Pro (Bản Hybrid 2 chế độ Hoán đổi & Bổ trợ).
Chế độ 1: Server Đám Mây Xiaozhi (Trò chuyện giọng nói với AI qua server).
Chế độ 2: Cục Bộ & Internet (Tra cứu tài liệu máy TrimUI, cẩm nang game, thời tiết, Wikipedia).

Nút điều khiển:
  Y (307)     -> SWAP: Hoán đổi qua lại giữa Server Đám Mây và Cục Bộ & Web.
  A (305)     -> Server: Thu âm/Gửi lời nói | Cục bộ: Hỏi câu hiện tại.
  B (304)     -> Server: Ngắt lời AI server | Cục bộ: Dừng giọng đọc loa.
  START (315) -> Server: Bật/tắt tự động   | Cục bộ: Gửi câu hỏi lên Server (Bổ trợ).
  X (308)     -> Server: Gửi câu mẫu server| Cục bộ: Đổi câu hỏi khác.
  MENU (316)  -> Thoát ứng dụng an toàn.
"""

import asyncio
import glob
import os
import random
import select
import signal
import struct
import threading
import unicodedata
from pathlib import Path


def _check_author_signature() -> None:
    """Chữ ký tác giả bản TrimUI Hybrid (xem AUTHORS). Kiểm tra độc lập với trimui_display.py:
    sai chữ ký, mất file AUTHORS, hoặc màn hình bị gỡ phần kiểm tra → không chạy."""
    import hashlib
    import sys as _sys

    here = os.path.dirname(os.path.abspath(__file__))
    _sys.path.insert(0, here)
    try:
        import trimui_display
        import trimui_signature

        h = hashlib.sha256(trimui_signature.raw_bytes()).hexdigest()
        if h[::-1] != "c353a55c64af77ec6e21bf76560861a04cac26dda0c1b375a2dca5a498ee4b1c":
            raise RuntimeError("sig")
        trimui_signature.check_authors_file(here)
        if not callable(getattr(trimui_display, "_verify_signature", None)) or \
                not callable(getattr(trimui_display.TrimuiViewManager, "render_splash", None)):
            raise RuntimeError("display")
    except Exception:
        msg = "Phiên bản này đã bị chỉnh sửa trái phép (chữ ký tác giả không hợp lệ)."
        print(msg, flush=True)
        try:  # cố hiện lên màn hình (nếu module màn hình còn dùng được)
            import time as _time

            from PIL import Image, ImageDraw, ImageFont
            from trimui_display import Framebuffer

            fb = Framebuffer()
            im = Image.new("RGB", (fb.width, fb.height), (40, 8, 12))
            d = ImageDraw.Draw(im)
            font = ImageFont.truetype(os.path.join(here, "fonts", "DejaVuSans.ttf"), 28)
            d.text((40, fb.height // 2 - 60), "LỖI XÁC THỰC", font=font, fill=(255, 90, 90))
            d.text((40, fb.height // 2), msg, font=font, fill="white")
            fb.present(im)
            _time.sleep(5)
            fb.close()
        except Exception:
            pass
        raise SystemExit(3)


_check_author_signature()

from src.utils.config_manager import initialize_config  # noqa: E402

initialize_config()

from src.logging import load_logging_config, setup_logging  # noqa: E402

setup_logging(enable_console=False, config=load_logging_config())

from src.bootstrap.container import ServiceContainer  # noqa: E402
from src.core.event_bus import Events  # noqa: E402
from src.logging import get_logger  # noqa: E402

logger = get_logger()

# ---- Chống treo (2026-10-08): vòng asyncio từng kẹt sau khi nhận "stt" → MENU không ăn,
# máy như đơ phải reset. Ghi vị trí kẹt vào bộ nhớ trong (còn sau reset) để sửa tận gốc.
import faulthandler  # noqa: E402
import time  # noqa: E402

HANG_LOG = "/mnt/UDISK/xiaozhi_hang.log"
HEARTBEAT = "/tmp/xiaozhi_hb"
try:
    _hang_fp = open(HANG_LOG, "a", buffering=1)
    # Người gác trong launch.sh gửi SIGUSR1 khi nhịp tim ngừng → in stack mọi luồng.
    faulthandler.register(signal.SIGUSR1, file=_hang_fp, all_threads=True)
except Exception:
    _hang_fp = None


def _force_exit(reason: str) -> None:
    """Gọi từ luồng phụ khi vòng chính không phản hồi: ghi stack mọi luồng rồi thoát cứng."""
    try:
        if _hang_fp:
            _hang_fp.write(f"\n===== {time.strftime('%F %T')} THOAT CUNG ({reason}) =====\n")
            faulthandler.dump_traceback(file=_hang_fp, all_threads=True)
            _hang_fp.flush()
    finally:
        os._exit(0)


async def _heartbeat() -> None:
    """Nhịp tim của vòng asyncio — launch.sh theo dõi để biết app còn sống."""
    while True:
        try:
            with open(HEARTBEAT, "w") as f:
                f.write(str(time.time()))
        except OSError:
            pass
        await asyncio.sleep(2)


# Nạp mô-đun Trí tuệ Nhân tạo & Giọng đọc Cục bộ
LOCAL_AI_DIR = Path(__file__).resolve().parent / "local_ai"
try:
    import sys
    sys.path.insert(0, str(LOCAL_AI_DIR))
    from knowledge_engine import generate_answer, KnowledgeBase
    from voice_player import VoicePlayer
    LOCAL_AI_AVAILABLE = True
except Exception as e:
    logger.warning(f"[hybrid] Khong nạp duoc local_ai: {e}")
    LOCAL_AI_AVAILABLE = False
    generate_answer = None
    VoicePlayer = None

# input_event trên aarch64
EV_FMT = "<qqHHi"
EV_SIZE = struct.calcsize(EV_FMT)
EV_KEY = 1

BTN_A = 305
BTN_B = 304
BTN_X = 308
BTN_Y = 307
BTN_START = 315
BTN_MENU = 316

# Danh sách câu hỏi mẫu bổ trợ cho chế độ Cục bộ
SAMPLE_QUESTIONS = [
    "Cách thoát game và lưu game trên máy TrimUI",
    "Màn hình và cấu hình máy TrimUI như thế nào",
    "Thời tiết hôm nay tại Hà Nội",
    "Thời tiết hôm nay tại TP Hồ Chí Minh",
    "Bây giờ là mấy giờ",
    "25 nhân 4 bằng mấy",
    "Mặt trời cách trái đất bao xa",
    "Việt Nam có bao nhiêu tỉnh thành",
    "Ai là người đầu tiên đặt chân lên Mặt Trăng",
    "Nước nào có diện tích lớn nhất thế giới",
]

TEST_SERVER_TEXT = "Xin chao, ban hay tu gioi thieu ngan gon bang tieng Viet"


class HybridController:
    """Điều phối viên quản lý 2 chế độ hoán đổi & bổ trợ."""

    def __init__(self, container, loop):
        self.container = container
        self.loop = loop
        self.mode = "server"  # "server" hoặc "local"
        self.q_index = 0
        self.player = VoicePlayer() if VoicePlayer else None
        self.local_kb = KnowledgeBase() if LOCAL_AI_AVAILABLE else None
        self.is_answering = False

    def swap_mode(self):
        """Hoán đổi giữa Server và Cục bộ."""
        if self.player:
            self.player.stop()

        if self.mode == "server":
            self.mode = "local"
            msg = "ĐÃ CHUYỂN SANG CHẾ ĐỘ CỤC BỘ & INTERNET"
        else:
            self.mode = "server"
            msg = "ĐÃ CHUYỂN SANG CHẾ ĐỘ SERVER ĐÁM MÂY"

        logger.info(f"[hybrid] Swap mode -> {self.mode}")
        asyncio.run_coroutine_threadsafe(self.container.event_bus.emit("trimui_mode_change", self.mode), self.loop)
        asyncio.run_coroutine_threadsafe(
            self.container.event_bus.emit(
                "trimui_local_update",
                {
                    "question": SAMPLE_QUESTIONS[self.q_index],
                    "status": msg,
                },
            ),
            self.loop,
        )

    def next_question(self):
        self.q_index = (self.q_index + 1) % len(SAMPLE_QUESTIONS)
        q = SAMPLE_QUESTIONS[self.q_index]
        asyncio.run_coroutine_threadsafe(
            self.container.event_bus.emit(
                "trimui_local_update",
                {
                    "question": q,
                    "answer": "Bấm A để hỏi câu này, hoặc START để gửi lên Server.",
                    "source": "Danh sách câu hỏi",
                    "status": "ĐÃ ĐỔI CÂU HỎI",
                },
            ),
            self.loop,
        )

    def ask_local(self):
        """Tra cứu cục bộ và Internet bằng AI cục bộ."""
        if self.is_answering or not LOCAL_AI_AVAILABLE:
            return
        threading.Thread(target=self._ask_local_worker, daemon=True).start()

    def _ask_local_worker(self):
        self.is_answering = True
        q = SAMPLE_QUESTIONS[self.q_index]
        asyncio.run_coroutine_threadsafe(
            self.container.event_bus.emit(
                "trimui_local_update",
                {
                    "question": q,
                    "answer": "Đang tra cứu tài liệu máy và tìm kiếm Internet...",
                    "status": "ĐANG TÌM KIẾM...",
                },
            ),
            self.loop,
        )
        try:
            res = generate_answer(q, allow_internet=True)
            ans = res.get("answer", "")
            src = res.get("source", "")
            asyncio.run_coroutine_threadsafe(
                self.container.event_bus.emit(
                    "trimui_local_update",
                    {
                        "question": q,
                        "answer": ans,
                        "source": src,
                        "status": "ĐÃ TRẢ LỜI (BẤM B ĐỂ DỪNG)",
                    },
                ),
                self.loop,
            )
            if self.player:
                self.player.speak(
                    ans,
                    on_finish=lambda: asyncio.run_coroutine_threadsafe(
                        self.container.event_bus.emit(
                            "trimui_local_update",
                            {"status": "HOÀN TẤT"},
                        ),
                        self.loop,
                    ),
                )
        except Exception as e:
            logger.error(f"[hybrid] Lỗi ask_local: {e}")
        finally:
            self.is_answering = False

    def send_current_to_server(self):
        """Bổ trợ: Lấy câu hỏi từ kho cục bộ gửi thẳng lên Server Xiaozhi."""
        q = SAMPLE_QUESTIONS[self.q_index]
        logger.info(f"[hybrid] Bổ trợ: Gửi câu '{q}' lên Server")
        self.mode = "server"
        asyncio.run_coroutine_threadsafe(self.container.event_bus.emit("trimui_mode_change", "server"), self.loop)
        asyncio.run_coroutine_threadsafe(self.container.event_bus.emit(Events.UI_SEND_TEXT, {"text": q}), self.loop)

    def check_local_supplement(self, spoken_text: str):
        """Bổ trợ: Khi Server nhận câu nói của người dùng, kiểm tra xem tài liệu máy có bổ trợ gì không."""
        if not self.local_kb or not spoken_text:
            return
        try:
            hits = self.local_kb.search(spoken_text, limit=1)
            if hits and hits[0].get("coverage", 0) >= 0.5:
                doc_ans = hits[0].get("text", "")[:120]
                doc_src = hits[0].get("source", "")
                asyncio.run_coroutine_threadsafe(
                    self.container.event_bus.emit(
                        "trimui_local_update",
                        {"supplement": f"[{doc_src}] {doc_ans}"},
                    ),
                    self.loop,
                )
        except Exception as e:
            logger.debug(f"[hybrid] Supplement check: {e}")


def find_gamepad():
    """Tìm node gamepad có nút A (305)."""
    EVIOCGBIT_KEY = 0x80604521
    import fcntl

    for dev in sorted(glob.glob("/dev/input/event*")):
        try:
            fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
            buf = bytearray(96)
            try:
                fcntl.ioctl(fd, EVIOCGBIT_KEY, buf)
                byte_idx = BTN_A // 8
                if byte_idx < len(buf) and (buf[byte_idx] >> (BTN_A % 8)) & 1:
                    return dev
            finally:
                os.close(fd)
        except Exception:
            continue
    return "/dev/input/event3"


def button_reader(loop, container, controller, stop_flag):
    try:
        dev = find_gamepad()
        logger.info(f"[trimui] Gamepad: {dev}")
        fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
    except Exception:
        logger.exception("[trimui] Không mở được gamepad")
        loop.call_soon_threadsafe(container.tasks.request_shutdown)
        return

    pending = bytearray()
    try:
        while not stop_flag["stop"]:
            ready, _, _ = select.select([fd], [], [], 0.2)
            if not ready:
                continue
            try:
                chunk = os.read(fd, EV_SIZE * 32)
            except BlockingIOError:
                continue
            if not chunk:
                break
            pending.extend(chunk)
            while len(pending) >= EV_SIZE:
                record = pending[:EV_SIZE]
                del pending[:EV_SIZE]
                _, _, etype, code, value = struct.unpack(EV_FMT, record)
                if etype != EV_KEY or value != 1:
                    continue

                asyncio.run_coroutine_threadsafe(container.event_bus.emit("trimui_button", str(code)), loop)
                logger.info("[trimui] Pressed button code=%s (mode=%s)", code, controller.mode)

                # Nút MENU: Thoát ứng dụng ở mọi chế độ
                if code == BTN_MENU:
                    asyncio.run_coroutine_threadsafe(container.event_bus.emit(Events.UI_QUIT_REQUEST), loop)
                    # Lối thoát cứng: vòng asyncio từng bị kẹt (2026-10-08) → MENU không ăn, máy như đơ.
                    # Luồng này độc lập: quá 4 giây chưa thoát thì ghi vị trí kẹt rồi buộc thoát.
                    threading.Timer(4.0, _force_exit, args=("MENU",)).start()
                    continue

                # Nút Y: HOÁN ĐỔI CHẾ ĐỘ (SWAP)
                if code == BTN_Y:
                    controller.swap_mode()
                    continue

                # Xử lý theo từng chế độ
                if controller.mode == "local":
                    # Chế độ Cục bộ & Web
                    if code == BTN_A:
                        controller.ask_local()
                    elif code == BTN_X:
                        controller.next_question()
                    elif code == BTN_B:
                        if controller.player:
                            controller.player.stop()
                    elif code == BTN_START:
                        # Bổ trợ: Gửi câu hỏi hiện tại lên Server
                        controller.send_current_to_server()

                else:
                    # Chế độ Server Đám Mây
                    if code == BTN_A:
                        asyncio.run_coroutine_threadsafe(container.event_bus.emit(Events.UI_MANUAL_TOGGLE), loop)
                    elif code == BTN_B:
                        asyncio.run_coroutine_threadsafe(container.event_bus.emit(Events.UI_ABORT_REQUEST), loop)
                    elif code == BTN_START:
                        asyncio.run_coroutine_threadsafe(container.event_bus.emit(Events.UI_AUTO_START), loop)
                    elif code == BTN_X:
                        asyncio.run_coroutine_threadsafe(
                            container.event_bus.emit(Events.UI_SEND_TEXT, {"text": TEST_SERVER_TEXT}), loop
                        )

    except Exception:
        logger.exception("[trimui] Lỗi đọc gamepad")
        loop.call_soon_threadsafe(container.tasks.request_shutdown)
    finally:
        os.close(fd)


async def setup_supplement_listeners(container, controller):
    """Lắng nghe các sự kiện để tự động bổ trợ giữa Server và Cục bộ."""
    # 1. Tự động chuyển Cục bộ khi Server ngắt kết nối (Fallback)
    async def on_disconnect(_data=None):
        logger.warning("[hybrid] Server ngắt kết nối -> Tự động chuyển sang chế độ Cục bộ")
        if controller.mode == "server":
            controller.mode = "local"
            await container.event_bus.emit("trimui_mode_change", "local")
            await container.event_bus.emit(
                "trimui_local_update",
                {
                    "status": "MẤT KẾT NỐI SERVER — ĐÃ CHUYỂN CỤC BỘ & WEB",
                    "question": SAMPLE_QUESTIONS[controller.q_index],
                    "answer": "Server bị gián đoạn. Bạn có thể bấm A để hỏi bằng dữ liệu máy & Internet.",
                },
            )

    container.event_bus.on(Events.PROTOCOL_DISCONNECTED, on_disconnect)
    container.event_bus.on(Events.NETWORK_ERROR, on_disconnect)

    # 2. Bổ trợ tri thức máy khi người dùng nói chuyện qua Server
    async def on_incoming_json(message):
        if isinstance(message, dict) and message.get("type") == "stt":
            spoken = message.get("text", "")
            if spoken:
                # Đọc tài liệu trên thẻ nhớ (thẻ từng lỗi I/O) → làm ở luồng phụ, không chặn vòng chính.
                loop = asyncio.get_running_loop()
                loop.run_in_executor(None, controller.check_local_supplement, spoken)

    container.event_bus.on(Events.INCOMING_JSON, on_incoming_json)


async def main():
    container = ServiceContainer()
    loop = asyncio.get_running_loop()
    stop_flag = {"stop": False}
    bg_tasks = []

    controller = HybridController(container, loop)

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        loop.add_signal_handler(sig, container.tasks.request_shutdown)

    reader = threading.Thread(
        target=button_reader, args=(loop, container, controller, stop_flag), daemon=True
    )

    if os.environ.get("XIAOZHI_HEADLESS") != "1":
        import src.ui.shared.factory as factory
        from trimui_display import TrimuiViewManager

        original_factory = factory.create_viewport

        def create_viewport(mode, event_bus, task_manager=None):
            if mode == "cli":
                return TrimuiViewManager(event_bus, task_manager)
            return original_factory(mode, event_bus, task_manager)

        factory.create_viewport = create_viewport

    reader.start()
    bg_tasks.append(asyncio.create_task(_heartbeat()))
    bg_tasks.append(asyncio.create_task(setup_supplement_listeners(container, controller)))

    try:
        return await container.run(mode="cli", protocol="websocket")
    finally:
        stop_flag["stop"] = True
        if controller.player:
            controller.player.stop()
        for t in bg_tasks:
            t.cancel()
        await asyncio.gather(*bg_tasks, return_exceptions=True)
        await asyncio.to_thread(reader.join, 1)


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
