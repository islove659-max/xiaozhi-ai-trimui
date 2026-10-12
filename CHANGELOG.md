# Xiaozhi AI TrimUI Hybrid v1.0.3

Sửa lỗi cài mới: launcher TrimUI bỏ qua OTA/kích hoạt, dẫn đến URL server trống và tự chuyển cục bộ.

- Bắt buộc OTA xác nhận thiết bị và WebSocket hello thành công trước khi mở giao diện/audio.
- Màn hình liên kết tiếng Việt, mã 6 số từ server; tài khoản mỗi chủ máy riêng biệt, không có ID/token đóng gói sẵn.
- A thử lại, MENU thoát; Y không vượt qua kích hoạt. Mất kết nối khóa thao tác và yêu cầu xác thực lại.
- Bật xác minh chứng chỉ HTTPS với certifi kèm gói; sửa header Activation-Version thành 2.
- Không nạp phím desktop/pynput và mô hình wake word thiếu trên Brick Pro. Giữ nút A và START của máy.
- Câu mẫu X đổi thành “Xin chào”, phù hợp với giới hạn wake word của server. Câu dài hỏi qua mic bằng A; START ở chế độ cục bộ hướng dẫn chuyển sang giọng nói. Hiện thông báo alert từ server.
- Giữ cấu hình, giấy phép, tác giả, âm lượng và thư viện âm thanh khi cập nhật.

Kiểm thử: 23 điều kiện trên Brick Pro với server fixture (hai tài khoản giả độc lập, từ chối token, mất mạng, hủy và chặn UI trước xác thực). HTTPS/OTA/WebSocket thật đã xác thực thành công trên thiết bị đang liên kết. QEMU ARM64 trên rootfs trùng ZIP TOS 4.0: 23/23 đạt. Thử launcher/giao diện/codec thật: nhận 138 gói Opus (8528 byte), 3 sự kiện TTS, thoát về MainUI bình thường. Chưa kiểm thử hội thoại bằng giọng người dùng qua mic hoặc liên kết một tài khoản mới thật.

Yêu cầu: Brick Pro, Stock 1.1.1 (20260717) / TOS 4.0, Python 3.11 ARM64 trên thẻ, Wi-Fi và tài khoản Xiaozhi riêng. Không cam kết TOS/máy khác. Việc liên kết tài khoản mới thật cần chủ máy tự nhập mã trên xiaozhi.me.
