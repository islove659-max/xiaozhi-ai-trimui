"""Ứng dụng Trợ lý AI & Tra cứu thông tin chạy trực tiếp trên máy TrimUI Brick Pro.
Hoạt động độc lập, không thông qua server chủ Xiaozhi.
Tự động lấy thông tin từ tài liệu nội bộ trong máy và tra cứu trực tiếp qua Internet.
"""

import asyncio
import ctypes
import fcntl
import glob
import math
import mmap
import os
import random
import re
import select
import signal
import struct
import sys
import threading
import time
import unicodedata
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Thêm đường dẫn module
CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR))

from knowledge_engine import generate_answer
from voice_player import VoicePlayer

# Cấu hình Framebuffer
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

class DisplayManager:
    def __init__(self):
        self.width = 1024
        self.height = 768
        self.memory = None
        self.fd = None
        self.rawmode = "BGRA"
        self._init_framebuffer()
        self._init_fonts()

    def _init_framebuffer(self):
        if not os.path.exists("/dev/fb0"):
            print("[Display] Không có /dev/fb0 (chế độ mô phỏng)")
            return
        try:
            self.fd = os.open("/dev/fb0", os.O_RDWR)
            self.var, self.fix = VarInfo(), FixInfo()
            fcntl.ioctl(self.fd, 0x4600, self.var)
            fcntl.ioctl(self.fd, 0x4602, self.fix)
            offsets = (self.var.red.offset, self.var.green.offset, self.var.blue.offset)
            self.rawmode = {(16, 8, 0): "BGRA", (0, 8, 16): "RGBA"}.get(offsets, "BGRA")
            self.width, self.height = self.var.xres, self.var.yres
            self.memory = mmap.mmap(self.fd, self.fix.smem_len, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
            print(f"[Display] Framebuffer sẵn sàng: {self.width}x{self.height} ({self.rawmode})")
        except Exception as e:
            print(f"[Display] Lỗi mở Framebuffer: {e}")

    def _init_fonts(self):
        # Tìm font chữ DejaVu
        font_paths = [
            CURRENT_DIR.parent / "fonts" / "DejaVuSans.ttf",
            CURRENT_DIR / "fonts" / "DejaVuSans.ttf",
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ]
        font_file = None
        for p in font_paths:
            if p.is_file():
                font_file = str(p)
                break

        if font_file:
            self.font_title = ImageFont.truetype(font_file, 40)
            self.font_sub = ImageFont.truetype(font_file, 26)
            self.font_body = ImageFont.truetype(font_file, 30)
            self.font_btn = ImageFont.truetype(font_file, 22)
            self.font_badge = ImageFont.truetype(font_file, 20)
        else:
            self.font_title = ImageFont.load_default()
            self.font_sub = ImageFont.load_default()
            self.font_body = ImageFont.load_default()
            self.font_btn = ImageFont.load_default()
            self.font_badge = ImageFont.load_default()

    def present(self, image: Image.Image):
        if not self.memory or not self.fd:
            return
        try:
            raw = image.convert("RGBA").tobytes("raw", self.rawmode)
            rowbytes = self.width * 4
            for y in range(self.height):
                start = (self.var.yoffset + y) * self.fix.line_length + self.var.xoffset * 4
                self.memory[start : start + rowbytes] = raw[y * rowbytes : (y + 1) * rowbytes]
        except Exception as e:
            print(f"[Display] Lỗi present: {e}")

    def close(self):
        if self.memory:
            self.memory.close()
            self.memory = None
        if self.fd:
            os.close(self.fd)
            self.fd = None


# Danh sách các câu hỏi mẫu thiết thực
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


class LocalAIAssistant:
    def __init__(self):
        self.display = DisplayManager()
        self.player = VoicePlayer()
        self.running = True
        self.current_q_index = 0
        self.question = SAMPLE_QUESTIONS[0]
        self.answer = "Bấm nút A để bắt đầu hỏi câu này, hoặc bấm X để đổi câu hỏi khác."
        self.source = "Hệ thống TrimUI"
        self.status = "SẴN SÀNG"
        self.is_processing = False
        self._lock = threading.Lock()

    def next_question(self):
        self.current_q_index = (self.current_q_index + 1) % len(SAMPLE_QUESTIONS)
        self.question = SAMPLE_QUESTIONS[self.current_q_index]
        self.status = "ĐÃ ĐỔI CÂU HỎI"
        self.render()

    def prev_question(self):
        self.current_q_index = (self.current_q_index - 1) % len(SAMPLE_QUESTIONS)
        self.question = SAMPLE_QUESTIONS[self.current_q_index]
        self.status = "ĐÃ ĐỔI CÂU HỎI"
        self.render()

    def random_question(self):
        self.current_q_index = random.randint(0, len(SAMPLE_QUESTIONS) - 1)
        self.question = SAMPLE_QUESTIONS[self.current_q_index]
        self.status = "ĐÃ CHỌN CÂU HỎI MỚI"
        self.render()

    def ask_current(self):
        if self.is_processing:
            return
        threading.Thread(target=self._ask_worker, daemon=True).start()

    def _ask_worker(self):
        self.is_processing = True
        self.status = "ĐANG TÌM KIẾM & SUY NGHĨ..."
        self.answer = "Đang tra cứu dữ liệu máy và tìm kiếm trên Internet..."
        self.render()

        try:
            res = generate_answer(self.question, allow_internet=True)
            self.answer = res.get("answer", "Không có câu trả lời.")
            self.source = res.get("source", "Trực tuyến")
            self.status = "ĐÃ TRẢ LỜI"
            self.render()

            # Phát giọng đọc ra loa
            self.player.speak(
                self.answer,
                on_start=lambda: self._set_speaking(True),
                on_finish=lambda: self._set_speaking(False),
            )
        except Exception as e:
            self.answer = f"Lỗi xử lý: {e}"
            self.status = "LỖI"
            self.render()
        finally:
            self.is_processing = False

    def _set_speaking(self, speaking: bool):
        if speaking:
            self.status = "ĐANG PHÁT GIỌNG ĐỌC (BẤM B ĐỂ DỪNG)"
        else:
            self.status = "HOÀN TẤT"
        self.render()

    def stop_speech(self):
        self.player.stop()
        self.status = "ĐÃ DỪNG GIỌNG ĐỌC"
        self.render()

    def render(self):
        w, h = self.display.width, self.display.height
        im = Image.new("RGB", (w, h), (18, 24, 38))
        d = ImageDraw.Draw(im)

        # 1. Header
        d.rectangle((0, 0, w, 80), fill=(26, 36, 56))
        d.text((32, 18), "TRỢ LÝ AI — TRIMUI", font=self.display.font_title, fill=(60, 220, 180))
        d.text((w - 380, 26), "Chạy trực tiếp • Tra cứu Internet", font=self.display.font_sub, fill=(160, 185, 210))
        d.line((0, 80, w, 80), fill=(45, 62, 92), width=2)

        # 2. Khung Trạng thái
        status_color = (60, 220, 180) if "ĐANG" not in self.status else (255, 190, 60)
        d.text((32, 98), f"Trạng thái: {self.status}", font=self.display.font_sub, fill=status_color)

        # 3. Khung Câu Hỏi
        d.rounded_rectangle((32, 140, w - 32, 230), radius=12, fill=(28, 40, 64), outline=(48, 70, 110), width=2)
        d.text((48, 150), "Câu hỏi:", font=self.display.font_btn, fill=(130, 160, 190))
        # Cắt câu hỏi vừa khung
        q_display = self.question
        while d.textlength(q_display, font=self.display.font_body) > (w - 120) and len(q_display) > 5:
            q_display = q_display[:-4] + "..."
        d.text((48, 178), q_display, font=self.display.font_body, fill=(255, 255, 255))

        # 4. Khung Câu Trả Lời
        d.rounded_rectangle((32, 250, w - 32, h - 160), radius=14, fill=(22, 32, 50), outline=(40, 60, 95), width=2)
        d.text((48, 262), f"Câu trả lời (Nguồn: {self.source}):", font=self.display.font_btn, fill=(60, 220, 180))

        # Tự động ngắt dòng cho câu trả lời
        words = self.answer.replace("\n", " ").split()
        lines = []
        cur_line = ""
        max_w = w - 100
        for word in words:
            test_line = f"{cur_line} {word}".strip()
            if d.textlength(test_line, font=self.display.font_body) <= max_w:
                cur_line = test_line
            else:
                if cur_line:
                    lines.append(cur_line)
                cur_line = word
        if cur_line:
            lines.append(cur_line)

        # Hiển thị tối đa 8 dòng
        for idx, line in enumerate(lines[:8]):
            d.text((48, 305 + idx * 42), line, font=self.display.font_body, fill=(240, 245, 255))

        # 5. Thanh nút bấm điều khiển ở đáy màn hình
        buttons = [
            ("A", "Hỏi câu này", (60, 220, 180)),
            ("X", "Đổi câu hỏi", (100, 180, 255)),
            ("B", "Dừng đọc", (255, 120, 120)),
            ("MENU", "Thoát", (160, 175, 195)),
        ]
        btn_y = h - 130
        btn_w = (w - 64 - (len(buttons) - 1) * 16) // len(buttons)
        for i, (btn, desc, color) in enumerate(buttons):
            bx = 32 + i * (btn_w + 16)
            d.rounded_rectangle((bx, btn_y, bx + btn_w, btn_y + 80), radius=10, fill=(28, 40, 64))
            # Huy hiệu phím
            badge_w = 70 if btn == "MENU" else 46
            d.rounded_rectangle((bx + 12, btn_y + 16, bx + 12 + badge_w, btn_y + 64), radius=8, fill=color)
            d.text((bx + 20, btn_y + 24), btn, font=self.display.font_btn, fill=(18, 24, 38))
            d.text((bx + badge_w + 22, btn_y + 26), desc, font=self.display.font_btn, fill=(255, 255, 255))

        self.display.present(im)


def find_gamepad():
    """Tìm node gamepad có nút A (305) trên Linux TrimUI."""
    EVIOCGBIT_KEY = 0x80604521
    for dev in sorted(glob.glob("/dev/input/event*")):
        try:
            fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
            buf = bytearray(96)
            try:
                fcntl.ioctl(fd, EVIOCGBIT_KEY, buf)
                if (buf[305 // 8] >> (305 % 8)) & 1:
                    return dev
            finally:
                os.close(fd)
        except Exception:
            continue
    return "/dev/input/event3"


def run_app():
    app = LocalAIAssistant()
    app.render()

    dev_path = find_gamepad()
    print(f"[App] Đọc nút bấm từ: {dev_path}")

    # Cấu trúc event input Linux
    EV_FMT = "<qqHHi"
    EV_SIZE = struct.calcsize(EV_FMT)

    BTN_A = 305
    BTN_B = 304
    BTN_X = 308
    BTN_Y = 307
    BTN_START = 315
    BTN_MENU = 316

    fd = None
    try:
        fd = os.open(dev_path, os.O_RDONLY | os.O_NONBLOCK)
    except Exception as e:
        print(f"[App] Không mở được thiết bị input: {e}")

    pending = bytearray()
    stop_app = False

    def handle_signal(sig, frame):
        nonlocal stop_app
        stop_app = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while not stop_app:
        if fd:
            ready, _, _ = select.select([fd], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(fd, EV_SIZE * 16)
                    if chunk:
                        pending.extend(chunk)
                except BlockingIOError:
                    pass

                while len(pending) >= EV_SIZE:
                    rec = pending[:EV_SIZE]
                    del pending[:EV_SIZE]
                    _, _, etype, code, value = struct.unpack(EV_FMT, rec)
                    # Chỉ bắt sự kiện phím bấm xuống (value = 1)
                    if etype == 1 and value == 1:
                        print(f"[App] Nút bấm: code={code}")
                        if code == BTN_A:
                            app.ask_current()
                        elif code == BTN_X:
                            app.next_question()
                        elif code == BTN_Y:
                            app.prev_question()
                        elif code == BTN_B:
                            app.stop_speech()
                        elif code == BTN_START:
                            app.ask_current()
                        elif code == BTN_MENU:
                            print("[App] Nút MENU -> Thoát")
                            stop_app = True
                            break
        else:
            time.sleep(0.2)

    app.player.stop()
    if fd:
        os.close(fd)
    app.display.close()
    print("[App] Đã thoát ứng dụng an toàn.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "--gui":
        # Chế độ dòng lệnh: Hỏi trực tiếp câu hỏi
        q = " ".join(sys.argv[1:])
        print(f"Câu hỏi: {q}")
        ans = generate_answer(q)
        print(f"Nguồn: {ans.get('source')}")
        print(f"Trả lời: {ans.get('answer')}")
    else:
        run_app()
