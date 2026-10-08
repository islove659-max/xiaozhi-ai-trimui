# Vá lỗi kernel TrimUI Brick Pro (A133, 4.9) báo sai độ phân giải CLOCK_MONOTONIC (~548s).
# Hậu quả nếu không vá: asyncio đặt _clock_resolution = 548s nên mọi timeout/timer dưới 548s
# bị kích hoạt ngay lập tức -> aiohttp/websockets TimeoutError tức thì, app không gọi được server.
# File này nằm trong PYTHONPATH (pylibs) nên Python tự nạp khi khởi động, trước khi asyncio tạo event loop.
import time as _time
import types as _types

_orig_get_clock_info = _time.get_clock_info


def _patched_get_clock_info(name):
    info = _orig_get_clock_info(name)
    try:
        if name in ("monotonic", "perf_counter") and info.resolution and info.resolution > 0.01:
            return _types.SimpleNamespace(
                implementation=info.implementation,
                monotonic=info.monotonic,
                adjustable=info.adjustable,
                resolution=1e-09,
            )
    except Exception:
        pass
    return info


_time.get_clock_info = _patched_get_clock_info

# Phòng khi một event loop đã được tạo trước đó: sửa trực tiếp mọi loop mới qua policy.
try:
    import asyncio as _asyncio

    _orig_new_loop = _asyncio.BaseEventLoop.__init__

    def _new_init(self, *a, **kw):
        _orig_new_loop(self, *a, **kw)
        try:
            if getattr(self, "_clock_resolution", 0) > 0.01:
                self._clock_resolution = 1e-09
        except Exception:
            pass

    _asyncio.BaseEventLoop.__init__ = _new_init
except Exception:
    pass
