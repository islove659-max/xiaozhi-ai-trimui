"""激活验证码副作用：剪贴板与语音播报."""

from __future__ import annotations

from typing import Optional

from src.logging import get_logger

logger = get_logger()


def _show_code_on_screen(code: str) -> None:
    """TrimUI: vẽ mã kích hoạt lên màn hình máy (không có console/SSH thì người dùng mới
    không biết mã — trước đây mã chỉ nằm trong log và được đọc bằng tiếng Trung)."""
    try:
        import os
        import sys
        from pathlib import Path

        from PIL import Image, ImageDraw, ImageFont

        app_dir = Path(__file__).resolve().parents[2]
        if str(app_dir) not in sys.path:
            sys.path.insert(0, str(app_dir))
        from trimui_display import Framebuffer

        fb = Framebuffer()
        try:
            w, h = fb.width, fb.height
            im = Image.new("RGB", (w, h), (16, 22, 34))
            d = ImageDraw.Draw(im)
            font_path = os.path.join(app_dir, "fonts", "DejaVuSans.ttf")
            f_title = ImageFont.truetype(font_path, 40)
            f_text = ImageFont.truetype(font_path, 26)
            f_code = ImageFont.truetype(font_path, 110)
            d.text((40, 40), "KÍCH HOẠT XIAOZHI AI (lần đầu)", font=f_title, fill=(70, 220, 185))
            steps = (
                "1. Trên điện thoại/máy tính, vào trang xiaozhi.me và đăng nhập.",
                "2. Vào bảng điều khiển → Thêm thiết bị → nhập mã 6 số dưới đây:",
            )
            for i, s in enumerate(steps):
                d.text((40, 130 + i * 44), s, font=f_text, fill="white")
            spaced = " ".join(code)
            cw = d.textlength(spaced, font=f_code)
            d.text(((w - cw) / 2, 290), spaced, font=f_code, fill=(255, 210, 90))
            d.text((40, h - 100), "Kích hoạt xong, app tự tiếp tục. Mã chỉ dùng một lần.", font=f_text,
                   fill=(175, 190, 210))
            fb.present(im)
        finally:
            fb.close()
    except Exception as e:
        logger.debug(f"Không vẽ được mã kích hoạt lên màn hình: {e}")


def apply_code_side_effects(code: str, message: Optional[str] = None) -> None:
    """日志 + 剪贴板 + 播报；不负责 CLI/GUI 文案."""
    if not code:
        return
    msg = message or "请在控制面板输入验证码"
    logger.info(f"激活提示: {msg}")
    logger.info(f"验证码: {code}")
    _show_code_on_screen(code)

    text = f".请登录到控制面板添加设备，输入验证码：{' '.join(code)}..."
    try:
        from src.utils.common_utils import handle_verification_code

        handle_verification_code(text)
    except Exception as e:
        logger.debug(f"复制验证码失败: {e}")

    try:
        from src.utils.activation_announcer import announce_activation_code

        announce_activation_code(code, locale="zh-CN")
    except Exception as e:
        logger.debug(f"验证码播报失败: {e}")


def announce_code(code: str) -> None:
    """仅播报（轮询重试时用）."""
    if not code:
        return
    _show_code_on_screen(code)  # vẽ lại phòng khi giao diện khác đã vẽ đè
    from src.utils.activation_announcer import announce_activation_code

    announce_activation_code(code, locale="zh-CN")
