# Sao lưu và phục hồi dữ liệu

ADMIN có thể tải JSON qua `POST /backup` hoặc `POST /system/backup`. Bản sao gồm dữ liệu các bảng, số bản ghi và checksum SHA-256; PostgreSQL xuất trong một transaction REPEATABLE READ. Đây là dữ liệu bảng, không bao gồm ảnh trên Cloudinary, file khóa hoặc biến môi trường.

File có thể chứa thông tin khách hàng, hash mật khẩu và token tích hợp đã lưu trong CSDL. Lưu tại nơi riêng tư có kiểm soát truy cập; không đưa vào Git hoặc đính kèm nhật ký công khai.

Phục hồi sử dụng cùng phiên bản schema, vào một DB riêng và trống. Công cụ tạo bảng nhưng không chạy bootstrap/seed người dùng. Đặt `LITO_RESTORE_DATABASE_URL` trong môi trường cục bộ tới DB đích, sau đó chạy từ thư mục backend:

```powershell
.venv/Scripts/python.exe scripts/restore_backup.py D:/PrivateBackups/lito-backup.json
```

Công cụ từ chối DB có bất kỳ dữ liệu nào, checksum sai hoặc cấu trúc không khớp. Toàn bộ dữ liệu được chèn trong một transaction và cập nhật sequence PostgreSQL. Không có chức năng ghi đè hay nút phục hồi trực tiếp vào DB đang vận hành. Sau phục hồi, đối chiếu số bản ghi và kiểm tra luồng nghiệp vụ trên DB đích trước khi chuyển hệ thống sang DB đó.
