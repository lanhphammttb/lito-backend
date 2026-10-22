# Kiểm tra kết nối Facebook — cập nhật 23/10/2026

## Cập nhật sau kiểm tra tổng thể

DNS `api.litohandmade.com` đã chuyển sang backend Vercel và xác minh hoạt động; phần mô tả AWS bên dưới là lịch sử trước khi sửa. Callback vẫn là `https://api.litohandmade.com/auth/facebook/callback`. Luồng mới bắt đầu bằng `POST /auth/facebook/start` với token ADMIN, sau đó chuyển trang qua vé có hạn để đặt cookie và mở Meta. Callback kiểm tra state/cookie và quyền quản trị viên trước khi lưu. Các kiểm thử dùng Meta giả lập; vẫn cần người dùng cấp quyền Trang thật để khôi phục kết nối, không có Page token để tự phục hồi.

## Trạng thái đã xác minh

Lần kiểm tra đầu, Neon không lưu các trường Facebook. Kiểm tra lại sau đó cho thấy App ID và App Secret đã có, nhưng Page ID, Page token và Instagram ID vẫn trống. API production báo thiếu kết nối trước khi gọi Meta. Các DB SQLite cục bộ và bản sao trong thư mục kiểm thử không có cấu hình để khôi phục. Không thể kết luận token hết hạn từ thông báo này.

Người dùng xác nhận đã kết nối tại `admin.litohandmade.com`, với callback `https://api.litohandmade.com/auth/facebook/callback`. DNS của `api.litohandmade.com` hiện trỏ tới `nhacogi-production-alb-1583215362.ap-southeast-1.elb.amazonaws.com`, không tới Vercel; đích AWS không phân giải được tại thời điểm kiểm tra. Đây là lỗi riêng khiến callback cũ không dùng được.

## Bản sửa

- Bỏ qua giá trị null/rỗng cho trường Facebook khi lưu cài đặt chung. Frontend chỉ gửi App ID/Secret khi người dùng chủ động sửa; Page token do luồng OAuth quản lý. Ngắt kết nối dùng endpoint riêng.
- Trả trạng thái kết nối riêng, không buộc giao diện của người không có quyền đọc secret phải dựa vào token.
- Khi tải lại cấu hình, giá trị null trong DB xóa trạng thái cũ trong bộ nhớ. Callback chỉ cập nhật bộ nhớ sau khi lưu thành công; kết nối Trang không có Instagram sẽ xóa Instagram ID cũ.
- Callback về `/#/settings` theo HashRouter; mã hóa tên Trang và thông báo. Giao diện đọc, hiển thị rồi xóa tham số kết quả.
- Đặt `FRONTEND_URL=https://admin.litohandmade.com` và giữ `FACEBOOK_REDIRECT_URI=https://api.litohandmade.com/auth/facebook/callback` trên Vercel Production theo cấu hình người dùng xác nhận. Đã gắn tên miền API vào dự án backend. Frontend vẫn gọi API qua tên miền Vercel hiện đang hoạt động.

## Kiểm chứng và phần chưa hoàn tất

47 kiểm thử backend qua, gồm 4 ca hồi quy mới cho lưu trống, ngắt kết nối/tải lại, trạng thái không lộ secret và callback có tên Trang chứa ký tự đặc biệt. Callback dùng phản hồi Meta giả lập trong DB thử, không phải một lần cấp quyền Meta thật. Frontend qua lint/build; còn cảnh báo cũ về chunk biểu đồ và dung lượng bundle. Đã kiểm tra thông báo thiếu cấu hình và đọc/xóa tham số callback trong trình duyệt QA.

Chưa khôi phục được kết nối thật. Cần sửa Cloudflare: bản ghi CNAME `api` → `e6b1644bfda7b0b8.vercel-dns-017.com`, DNS only, thay cho đích AWS cũ; sau đó xác minh bằng `vercel domains verify api.litohandmade.com`. Cấu hình ứng dụng Meta đã có nên có thể cấp quyền lại khi callback hoạt động. Không gửi App Secret hoặc Page token trong chat hay commit vào Git. Luồng OAuth hiện cũng cần bổ sung kiểm tra `state` và xác thực quản trị viên khi bắt đầu; bản sửa này chưa xử lý phần đó.
