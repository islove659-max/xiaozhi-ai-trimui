# Xiaozhi AI — Bản TrimUI Hybrid

Trợ lý AI giọng nói tiếng Việt cho máy chơi game cầm tay **TrimUI Brick Pro** (Stock OS), chạy thẳng trên framebuffer, điều khiển bằng nút máy.

**Phát triển & tuỳ biến bản TrimUI Hybrid:** islove659@gmail.com
**Lõi:** [py-xiaozhi](https://github.com/huangjunsen0406/py-xiaozhi) © 2025 Junsen — giấy phép MIT.

## Tính năng

- **Hai chế độ, bấm Y để đổi:**
  - **Server đám mây Xiaozhi:** nói chuyện bằng giọng nói (nút A), chế độ tự động trò chuyện liên tục (START).
  - **Cục bộ & Internet:** không cần server Xiaozhi.
    - Thời tiết (wttr.in), giờ, máy tính, tài liệu hướng dẫn máy TrimUI.
    - Tra **Wikipedia tiếng Việt**.
    - **Tự học:** câu hỏi lặp lại ≥2 lần được lưu vào máy, mất mạng vẫn trả lời được.
    - **Gemini (tuỳ chọn):** trả lời câu hỏi vui, câu tưởng tượng (dùng key miễn phí của chính bạn).
- Tự chuyển sang chế độ Cục bộ khi mất kết nối server.
- Giao diện tiếng Việt 1024×768, giọng đọc tiếng Việt.

## Yêu cầu

- TrimUI Brick Pro, Stock OS (đã thử bản 20260717), kết nối Wi-Fi.
- Python 3.11 trên thẻ (`/mnt/SDCARD/System/bin/python3`).
- Tài khoản [xiaozhi.me](https://xiaozhi.me) để kích hoạt chế độ Server (miễn phí).

## Cài đặt

1. Chép thư mục này vào thẻ nhớ thành `Apps/XiaozhiAI/`.
2. Bật SSH trên máy, rồi cài thư viện:
   ```sh
   cd /mnt/SDCARD/Apps/XiaozhiAI
   . /mnt/SDCARD/System/etc/ex_config
   python3 -m pip install --target pylibs -r requirements-trimui.txt
   ```
3. Áp các bản vá TrimUI và thư viện hệ thống: xem [`trimui_patches/README.md`](trimui_patches/README.md).
4. Lần đầu chạy để kích hoạt (nhận mã 6 số, nhập trên xiaozhi.me):
   ```sh
   export HOME=/root PYTHONPATH=$PWD/pylibs
   python3 main.py --mode cli
   ```
5. Từ đó mở **Xiaozhi AI** trong menu Apps của máy.

### Bật Gemini (tuỳ chọn)

Xem [`local_ai/HUONG_DAN_GEMINI.txt`](local_ai/HUONG_DAN_GEMINI.txt). Tóm tắt: tạo key tại aistudio.google.com/apikey, ghi vào `local_ai/gemini_key.txt` (1 dòng). **Không đưa file key lên GitHub** (đã có trong `.gitignore`).

## Nút điều khiển

| Nút | Chế độ Server | Chế độ Cục bộ |
|---|---|---|
| A | Bắt đầu / gửi lời nói | Hỏi câu hiện tại |
| B | Ngắt câu trả lời | Dừng giọng đọc |
| X | Gửi câu mẫu | Đổi câu hỏi |
| START | Bật/tắt tự động | Gửi câu hỏi lên Server |
| Y | Đổi sang Cục bộ | Đổi sang Server |
| MENU | Thoát | Thoát |

## Ghi chú kỹ thuật (Brick Pro)

- Âm thanh ra: `PlaybackDmix` 48 kHz 2 kênh (thiết bị `default` báo 128 kênh → treo máy; 2 kênh trên `default` → câm).
- Không chỉnh âm lượng mixer: `Headphone Volume` và `digital volume` của codec có thang **ngược** chú thích dB; giữ mức MainUI để lại.
- Hàng đợi giọng đọc 120 giây (10 giây làm mất cuối câu dài).
- `XIAOZHI_TRIMUI_LITE=1`: bỏ camera, chụp màn hình, công cụ desktop → RAM ~63 MB (từ ~91 MB).
- Toàn bộ biến môi trường nằm trong `launch.sh`.

## Giấy phép

MIT — xem [`LICENSE`](LICENSE) và [`AUTHORS`](AUTHORS). Khi phân phối lại phải giữ nguyên thông báo bản quyền của cả lõi py-xiaozhi và bản TrimUI Hybrid.
