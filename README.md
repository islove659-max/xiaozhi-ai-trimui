# Xiaozhi AI — Bản TrimUI Hybrid

Trợ lý AI giọng nói tiếng Việt cho máy chơi game cầm tay **TrimUI Brick Pro** (Stock OS / TOS 4.0), chạy thẳng trên framebuffer, điều khiển bằng nút máy.

**Phát triển & tuỳ biến bản TrimUI Hybrid:** islove659@gmail.com
**Lõi:** [py-xiaozhi](https://github.com/huangjunsen0406/py-xiaozhi) © 2025 Junsen — giấy phép MIT.

## Tính năng

- **Hai chế độ, bấm Y để đổi:**
  - **Server đám mây Xiaozhi:** nói chuyện bằng giọng nói (nút A), chế độ tự động trò chuyện liên tục (START).
  - **Cục bộ & Internet:** dùng sau khi đã xác thực thiết bị với server Xiaozhi.
    - Thời tiết (wttr.in), giờ, máy tính, tài liệu hướng dẫn máy TrimUI.
    - Tra **Wikipedia tiếng Việt**.
    - **Tự học:** câu hỏi lặp lại ≥2 lần được lưu vào máy, mất mạng vẫn trả lời được.
    - **Gemini (tuỳ chọn):** trả lời câu hỏi vui, câu tưởng tượng (dùng key miễn phí của chính bạn).
- **v1.1.0 — Cài gói game bằng AI (bấm R1):** chép game vào thư mục `CHEP_GAME_VAO_DAY` ở gốc thẻ (zip, 7z, thư mục, ROM lẻ, gói port PortMaster, dữ liệu game của port). Bấm **A** để AI tự nhận diện và cài gói đang chọn, **START** để cài tất cả. App tự tìm đúng thư mục `Roms/<HỆ>`, tự cài port vào `Data/ports` và menu Ports (kèm runtime khi có Wi-Fi), tự cài port trước khi chép dữ liệu game của nó; gói chưa nhận ra thì Gemini chọn trong các nơi cài hợp lệ. Không ghi đè, có hoàn tác. Riêng tư: AI (Gemini, key riêng của bạn) chỉ nhận tên gói, tên và dung lượng file, vài file chữ nhỏ đã lọc dòng nhạy cảm; **không** nhận nội dung ROM hay dữ liệu game. Không có key/mạng thì AI không chạy, app vẫn tự cài các gói nhận ra được.
- **v1.0.3:** kiểm tra quyền thiết bị qua OTA và kết nối server trước khi mở giao diện. Mất kết nối sẽ khóa thao tác, bấm A để thử lại.
- Mã kích hoạt hiện trực tiếp trên màn hình. Mỗi chủ máy liên kết với tài khoản Xiaozhi riêng; gói không có ID/token dùng chung.
- Kiểm tra chứng chỉ HTTPS bằng bộ CA đi kèm.
- Giao diện tiếng Việt 1024×768, giọng đọc tiếng Việt.

## Yêu cầu

- TrimUI Brick Pro, Stock OS 1.1.1 (20260717) / TOS 4.0, kết nối Wi-Fi.
- Python 3.11 trên thẻ (`/mnt/SDCARD/System/bin/python3`).
- Tài khoản [xiaozhi.me](https://xiaozhi.me) của chính chủ máy. Cần kết nối server thành công mỗi lần mở app.

## Cài đặt

### Gói cài sẵn (khuyên dùng)

1. Tải `XiaozhiAI-TrimUI-BrickPro-v1.0.3.zip` tại Releases, giải nén vào gốc thẻ game và ghi gộp `Apps/` + `System/`.
2. Bật Wi-Fi, mở Apps → Xiaozhi AI. App kiểm tra thiết bị với server trước khi vào giao diện.
3. Nếu hiện mã 6 số: trên điện thoại vào xiaozhi.me → đăng nhập **tài khoản của bạn** → Thêm thiết bị → nhập mã. App chỉ tiếp tục sau khi server xác nhận và kết nối thành công.
4. Máy đã liên kết hợp lệ không phải nhập mã mỗi lần, nhưng vẫn phải kiểm tra server. Không có mã cố định hay tài khoản chung trong gói.
5. Lỗi mạng/chứng chỉ/xác thực: app ở lại màn hình kết nối. **A** thử lại, **MENU** thoát. Không tự chuyển cục bộ để bỏ qua xác thực.

Cập nhật từ v1.0.2 chỉ ghi gộp file app; cấu hình trong `/root/.local/share/py-xiaozhi/` được giữ nguyên. Không chép cấu hình/efuse từ máy khác.

### Tự cài từ mã nguồn

Chép repo thành `Apps/XiaozhiAI/`, cài `requirements-trimui.txt` vào `pylibs/` bằng Python 3.11 ARM64, áp các bản vá/thư viện trong [`trimui_patches/README.md`](trimui_patches/README.md), rồi mở app từ menu. Không cần chạy `main.py` để kích hoạt thủ công nữa.

### Bật Gemini (tuỳ chọn)

Xem [`local_ai/HUONG_DAN_GEMINI.txt`](local_ai/HUONG_DAN_GEMINI.txt). Tóm tắt: tạo key tại aistudio.google.com/apikey, ghi vào `local_ai/gemini_key.txt` (1 dòng). **Không đưa file key lên GitHub** (đã có trong `.gitignore`).

## Nút điều khiển

| Nút | Chế độ Server | Chế độ Cục bộ |
|---|---|---|
| A | Bắt đầu / gửi lời nói | Hỏi câu hiện tại |
| B | Ngắt câu trả lời | Dừng giọng đọc |
| X | Gửi câu mẫu | Đổi câu hỏi |
| START | Bật/tắt tự động | Sang Server, bấm A để hỏi |
| Y | Đổi sang Cục bộ | Đổi sang Server |
| MENU | Thoát | Thoát |
| R1 / L1 | Sang tab Cài gói game / về Trợ lý AI | |

Tab **Cài gói game**: A = AI tự cài gói, START = AI cài tất cả, X = xem trước (sau khi cài: xoá gói gốc), Y = hỏi AI, B = quay lại, giữ Lên/Xuống để cuộn.

## Ghi chú kỹ thuật (Brick Pro)

- Âm thanh ra: `PlaybackDmix` 48 kHz 2 kênh (thiết bị `default` báo 128 kênh → treo máy; 2 kênh trên `default` → câm).
- Không chỉnh âm lượng mixer: `Headphone Volume` và `digital volume` của codec có thang **ngược** chú thích dB; giữ mức MainUI để lại.
- Hàng đợi giọng đọc 120 giây (10 giây làm mất cuối câu dài).
- `XIAOZHI_TRIMUI_LITE=1`: bỏ camera, chụp màn hình, công cụ desktop → RAM ~63 MB (từ ~91 MB).
- Toàn bộ biến môi trường nằm trong `launch.sh`.

## Giấy phép

MIT — xem [`LICENSE`](LICENSE) và [`AUTHORS`](AUTHORS). Khi phân phối lại phải giữ nguyên thông báo bản quyền của cả lõi py-xiaozhi và bản TrimUI Hybrid.
