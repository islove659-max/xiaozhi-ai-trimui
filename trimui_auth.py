"""Account gate for Brick Pro: OTA authorization AND a successful server hello.
No packaged identity/token and no offline bypass before authorization.
"""
import asyncio
import os
import select
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

VERSION = "1.1.0"


def render_auth_screen(width, height, state):
    image = Image.new("RGB", (width, height), (16, 22, 34))
    draw = ImageDraw.Draw(image)
    font_path = str(Path(__file__).parent / "fonts" / "DejaVuSans.ttf")
    scale = min(width / 1024, height / 768)
    def font(size):
        return ImageFont.truetype(font_path, max(14, int(size * scale)))
    left, y = int(40 * scale), int(40 * scale)
    draw.text((left, y), "XIAOZHI AI  " + VERSION, font=font(40), fill=(70, 220, 185))
    y += int(100 * scale)
    for text, size, color in [
        (state.get("status", "Đang kiểm tra tài khoản..."), 30, "white"),
        (state.get("detail", ""), 25, (175, 190, 210)),
    ]:
        line = ""
        for word in text.split():
            candidate = (line + " " + word).strip()
            if line and draw.textlength(candidate, font=font(size)) > width - 2 * left:
                draw.text((left, y), line, font=font(size), fill=color)
                y += int(42 * scale); line = word
            else:
                line = candidate
        draw.text((left, y), line, font=font(size), fill=color)
        y += int(65 * scale)
    code = str(state.get("code", ""))
    if code:
        spaced = " ".join(code)
        f = font(100)
        draw.text(((width - draw.textlength(spaced, font=f)) / 2, int(355 * scale)),
                  spaced, font=f, fill=(255, 210, 90))
    draw.text((left, height - int(135 * scale)),
              "Mỗi máy liên kết với tài khoản Xiaozhi của chủ máy.",
              font=font(24), fill=(175, 190, 210))
    controls = "MENU: Thoát" if state.get("busy") else "A: Thử kết nối lại     MENU: Thoát"
    draw.text((left, height - int(75 * scale)), controls, font=font(26), fill=(70, 220, 185))
    return image


async def authorize_cloud(show):
    """Return True only for server-confirmed identity plus authenticated WS hello.
    show is an async callback. Cancellation never authorizes the app.
    """
    from src.activation import ActivationService
    from src.protocols.websocket_protocol import WebsocketProtocol
    from src.utils.config_manager import get_config
    await show({"status": "Đang kiểm tra kết nối Xiaozhi...", "busy": True})
    service = None
    ws = None
    try:
        config = get_config()
        config.update_config("SYSTEM_OPTIONS.NETWORK.ACTIVATION_VERSION", "v2")
        service = await ActivationService.create()
        result = await service.initialize()
        if not result.get("success"):
            raise RuntimeError("Không lấy được cấu hình server. Kiểm tra Wi-Fi, ngày giờ và chứng chỉ HTTPS.")
        if result.get("need_activation_ui"):
            data = service.get_activation_data() or {}
            code, challenge = str(data.get("code", "")), data.get("challenge")
            if len(code) != 6 or not code.isdigit() or not challenge:
                raise RuntimeError("Server chưa trả mã kích hoạt hợp lệ. Bấm A để thử lại.")
            await show({"status": "Liên kết tài khoản của bạn", "code": code, "busy": True,
                        "detail": "Trên điện thoại vào xiaozhi.me, đăng nhập tài khoản của bạn, chọn Thêm thiết bị và nhập mã dưới đây."})
            if not await service._http.activate(challenge, code):
                raise RuntimeError("Mã kích hoạt hết thời gian hoặc chưa được xác nhận. Bấm A lấy mã mới.")
            result = await service.initialize()
        # Never trust a locally cached flag or the service's compatibility fallback.
        if (not result.get("success") or result.get("need_activation_ui")
                or not service.get_activation_status().get("server_activated")):
            raise RuntimeError("Server chưa xác nhận thiết bị thuộc tài khoản. Bấm A để thử lại.")
        url = config.get_config("SYSTEM_OPTIONS.NETWORK.WEBSOCKET_URL")
        token = config.get_config("SYSTEM_OPTIONS.NETWORK.WEBSOCKET_ACCESS_TOKEN")
        if not isinstance(url, str) or not url.startswith(("wss://", "ws://")) or not token:
            raise RuntimeError("Cấu hình server thiếu địa chỉ hoặc mã truy cập.")
        await show({"status": "Đang xác thực kết nối server...", "busy": True})
        ws = WebsocketProtocol()
        if not await ws.connect():
            raise RuntimeError("Server chưa chấp nhận kết nối. Kiểm tra Wi-Fi hoặc liên kết tài khoản rồi bấm A.")
        await show({"status": "Đã xác thực thiết bị và kết nối server", "ready": True})
        return True
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        from src.logging import get_logger
        get_logger().warning("[auth] Authorization failed: %s", type(exc).__name__)
        detail = str(exc) if isinstance(exc, RuntimeError) else "Không kết nối được. Kiểm tra Wi-Fi, ngày giờ và chứng chỉ HTTPS rồi thử lại."
        await show({"status": "Chưa kết nối được tài khoản", "detail": detail, "busy": False})
        return False
    finally:
        if service:
            service.cancel_activation()
        if ws:
            await ws.close_audio_channel()


async def run_startup_gate(find_gamepad):
    """Own framebuffer/input before the main application or audio plugins start."""
    from trimui_display import Framebuffer
    fb = Framebuffer()
    fd = None
    task = None
    pending = bytearray()
    async def show(state):
        fb.present(render_auth_screen(fb.width, fb.height, state))
    try:
        fd = os.open(find_gamepad(), os.O_RDONLY | os.O_NONBLOCK)
        task = asyncio.create_task(authorize_cloud(show))
        while True:
            if task.done() and task.result():
                return True
            ready, _, _ = select.select([fd], [], [], 0)
            if ready:
                pending.extend(os.read(fd, 24 * 32))
                while len(pending) >= 24:
                    record = bytes(pending[:24]); del pending[:24]
                    _, _, etype, code, value = struct.unpack("<qqHHi", record)
                    if etype != 1 or value != 1:
                        continue
                    if code == 316:
                        return False
                    if code == 305 and task.done():
                        task = asyncio.create_task(authorize_cloud(show))
            await asyncio.sleep(0.08)
    finally:
        if task and not task.done():
            task.cancel()
        if task:
            await asyncio.gather(task, return_exceptions=True)
        if fd is not None:
            os.close(fd)
        fb.close()
