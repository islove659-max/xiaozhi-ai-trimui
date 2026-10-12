# Xiaozhi AI TrimUI Hybrid v1.1.0

Mới: tab **Cài gói game** — AI tự nhận diện và cài game vào đúng chỗ, dành cho người mới.

- Bấm **R1** để sang tab Cài gói game, **L1** để về Trợ lý AI.
- Chép game vào thư mục **CHEP_GAME_VAO_DAY** ở ngoài cùng thẻ nhớ (có sẵn HUONG_DAN.txt): file .zip, .7z, thư mục đã giải nén, file ROM lẻ, gói port PortMaster hoặc dữ liệu game của port.
- **A**: AI tự cài gói đang chọn. **START**: AI cài tất cả (port trước, rồi dữ liệu game, rồi ROM) và hiện bảng kết quả. **X**: xem trước. **Y**: hỏi AI. Cài xong bấm X để xoá gói gốc.
- Tự nhận diện ROM theo giả lập có trên thẻ (kể cả N64/NDS/PSP… không khai báo đuôi file), dữ liệu game của port theo script của port, gói port PortMaster. Gói chưa nhận ra thì AI (Gemini, key riêng của bạn) chọn nơi cài trong danh sách hợp lệ; AI có kèm hướng dẫn cài game của máy.
- Port PortMaster được cài thẳng vào Data/ports và thêm vào menu Ports; runtime tải qua PortMaster khi có Wi-Fi. Gói dữ liệu game mà port chưa cài thì app tự cài port trước.
- Cài ROM xong tự làm mới danh sách game của MainUI.
- An toàn: không ghi đè file khác nội dung, cài qua thư mục tạm và tự hoàn tác khi lỗi/hủy, không tự chạy game, không gửi ROM/dữ liệu game/key cho AI.
- Gồm bản sửa kích hoạt tài khoản của v1.0.3 (chưa phát hành riêng).

Kiểm thử: 66 + 14 điều kiện tự động; trên Brick Pro thật đã cài 8 gói (ROM zip/7z/thư mục/file lẻ, port Unwin, port The Last Game + dữ liệu Steam), MD5 khớp bản gốc, mở chơi được.

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
