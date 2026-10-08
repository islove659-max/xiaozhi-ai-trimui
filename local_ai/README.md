# Kho dữ liệu cục bộ — bản nền thử nghiệm

Chép tài liệu TXT hoặc MD mã hóa UTF-8 vào knowledge/documents. Mỗi đoạn nên nói về một chủ đề; để dòng trống giữa các đoạn. Giới hạn mỗi file 2 MB. Thêm hoặc sửa tài liệu sẽ được nhận ở lần tìm tiếp theo.

Chạy trên máy: /mnt/SDCARD/System/bin/python3 local_ai/knowledge_engine.py "bật nghe tự động"
Thêm --internet để tìm Wikipedia tiếng Việt khi tài liệu cục bộ không khớp đủ. Tìm internet chỉ gửi câu hỏi, không tải tài liệu cá nhân lên. Trả về đoạn văn và nguồn, chưa phải câu trả lời từ LLM. Không có kết quả sẽ báo thiếu dữ liệu; lỗi mạng báo riêng.

Đây là công cụ tra tài liệu chạy độc lập, chưa nối vào nút A hay thay backend giọng nói hiện tại. Xiaozhi hiện tại vẫn sử dụng server cho nhận tiếng nói và tạo/phát câu trả lời.

Các phần còn thiếu để độc lập hoàn toàn: nhận giọng nói tiếng Việt cục bộ, tổng hợp giọng nói cục bộ, và tùy chọn mô hình suy luận nhỏ. Cần biên dịch ARM64 tương thích Stock OS và đo RAM/tốc độ trên máy. PC hiện không có CMake/compiler hoặc WSL hoạt động; máy game cũng không có compiler, whisper-cli, llama-cli, piper hay espeak trong PATH.
