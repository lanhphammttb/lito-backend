# Thông báo trình duyệt — 23/10/2026

## Nguyên nhân đã xác định

- Backend chỉ đọc file `firebase-adminsdk.json`, trong khi Vercel không có file này và chưa có cấu hình Firebase riêng. Thiết bị đã đăng ký nhưng kênh gửi bị vô hiệu hóa.
- `/notifications/send` tự đặt số đã gửi bằng số người được chọn hoặc 1, dù không có lần gửi thành công. Giao diện luôn báo thành công rồi xóa form.
- Hook nhận thông báo chỉ chạy khi mount, bỏ qua đăng ký sau đăng nhập. Nếu token không đổi, hook cũng không đăng ký lại khi DB mất đăng ký hoặc người dùng đổi tài khoản.
- Thông báo nền được Firebase hiển thị tự động nhưng service worker tiếp tục gọi hiển thị lần nữa. Luồng foreground chờ service worker của trang, thay vì registration riêng của Firebase.

## Thay đổi

- Cấu hình `FIREBASE_CREDENTIALS_JSON` dạng secret trên backend Vercel, dùng service account hiện có của đúng dự án `handmade-14fd7`. Không đưa khóa vào mã nguồn hoặc file triển khai.
- API trả số thiết bị Firebase thực sự chấp nhận, số thất bại và số kết nối WebSocket chuyển được. Không có thiết bị hoặc gửi thất bại trả `success: false`; gửi một phần có trạng thái riêng. Chỉ xóa token chắc chắn đã hết hiệu lực.
- Giao diện giữ form khi thất bại, hiển thị kết quả ngay trên trang. Thêm trạng thái quyền/thiết bị/cấu hình, nút bật và kiểm tra. Chỉ hỏi quyền sau thao tác người dùng; đăng ký thiết bị lại sau đăng nhập/tải trang.
- Service worker dùng cấu hình cùng frontend, không hiển thị trùng, mở đúng trang thông báo khi bấm. Thông báo foreground cập nhật chuông và gọi thông báo hệ thống qua registration Firebase.
- Nút kiểm tra gửi chỉ tới tài khoản hiện tại. Nút gửi email thử trong Cài đặt dùng SMTP riêng, không dùng nhầm endpoint thông báo trình duyệt.

## Kiểm chứng

- 55 kiểm thử backend qua, trong đó 8 ca mới bao phủ xác thực, không có người nhận, thiếu credentials, gửi một phần, phạm vi người nhận, token hết hạn, JSON credentials, dữ liệu không hợp lệ và email thử.
- 6 kiểm thử frontend qua cho kết quả gửi và service worker; lint/build qua. Vẫn có cảnh báo build cũ về chunk biểu đồ và kích thước bundle.
- Firebase kiểm tra `dry_run=True` với 5 token production: 5 chấp nhận, 0 lỗi. Phép này không phát thông báo tới người nhận và không sửa dữ liệu nghiệp vụ.
- Trình duyệt QA xác nhận lỗi gửi hiện trên form và nội dung nhập được giữ lại. Không gửi thông báo thật tới người dùng production trong quá trình kiểm tra.

Firebase chấp nhận yêu cầu không chứng minh hệ điều hành đã hiện banner hoặc người nhận đã đọc. Cần người dùng bấm Kiểm tra trên thiết bị của mình để nghiệm thu hiển thị thực tế, đồng thời kiểm tra quyền thông báo và chế độ Không làm phiền. Các sự kiện tự động về đơn hàng/tồn kho vẫn có luồng WebSocket riêng; bản sửa này tập trung vào chức năng Gửi thông báo mà người dùng xác nhận gặp lỗi.
