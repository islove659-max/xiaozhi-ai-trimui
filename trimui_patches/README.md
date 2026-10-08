# Bản vá để chạy trên TrimUI Brick Pro (Stock OS)

Áp sau khi cài thư viện vào `pylibs/` (xem README chính).

| File | Chép tới | Vì sao |
|---|---|---|
| `sitecustomize.py` | `pylibs/sitecustomize.py` | Kernel A133 báo sai độ phân giải `CLOCK_MONOTONIC` (~548 giây) → mọi timeout của asyncio nổ ngay, không kết nối được server. File này ép độ phân giải về 1 ns. |
| `websockets_version.py` | `pylibs/websockets/version.py` | Bản gốc gọi `importlib.metadata`, trên thẻ FAT32 báo `OSError: Bad file descriptor` → không import được websockets. |

## Vá sounddevice

`ctypes.util.find_library("portaudio")` trả `None` trên máy. Trong `pylibs/sounddevice.py`, thay dòng:

```python
raise OSError('PortAudio library not found')
```

bằng:

```python
_libname = 'libportaudio.so.2'
```

## Thư viện hệ thống (`/mnt/SDCARD/System/lib/`)

Stock OS không có PortAudio. Lấy từ gói Debian bullseye arm64 (glibc 2.31 ≤ 2.33 của máy):

- `libportaudio2` → `libportaudio.so.2`
- `libjack-jackd2-0` → `libjack.so.0`

Giải nén file `.deb` (`ar x`, rồi `tar xf data.tar.xz`), chép file `.so` **thật** (thẻ FAT32 không có symlink).
