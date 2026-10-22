# Xóa dữ liệu và nguyên liệu thay thế theo dòng BOM

Các nút Xóa mới dùng cùng hộp xác nhận, trạng thái chờ và cập nhật dữ liệu sau
khi API thành công. API xóa bản ghi SQL, trả 404 khi bản ghi không tồn tại và
409 kèm lý do khi có liên kết nghiệp vụ. Các API xóa quản trị yêu cầu ADMIN.
Audit log được giữ để truy vết thao tác.

| Đối tượng | Điều kiện xóa hoàn toàn |
| --- | --- |
| Sản phẩm | Không có đơn hàng/job, tồn thành phẩm/biến thể, liên kết bộ khác, nội dung, vấn đề hoặc khuyến mãi. Xóa các ảnh/biến thể/đánh giá/lịch sử giá/vòng đời/tín hiệu riêng trong cùng transaction. |
| Nguyên liệu | Tồn và giữ chỗ bằng 0; không dùng trong BOM kể cả phương án thay thế, job, PO, lô hàng hoặc lịch sử xuất nhập. Báo giá riêng được dọn cùng bản ghi. |
| Nhà cung cấp | Không còn nguyên liệu, PO, lô hàng hoặc báo giá sử dụng. |
| Khách hàng | Không có đơn hàng hoặc đánh giá. |
| Đơn bán | Nháp/chờ/đã hủy, chưa thanh toán, không có job, giao dịch, hoàn trả hoặc lịch sử kho. Dòng đơn hàng SQL được xóa trước bản ghi cha. |
| Đơn mua | Chưa nhận hàng, chưa thanh toán, không có lô hàng/lịch sử nhập kho. |
| Job | Kế hoạch/đã hủy, chưa bắt đầu, chưa tiêu hao và không còn giữ chỗ. Lịch sử giữ/nhả chỗ cân bằng của job nháp được dọn; tồn và giữ chỗ của job khác giữ nguyên. |
| Strategy | OKR, SWOT và thông tin thị trường có endpoint xóa riêng; kiểm tra đúng loại bản ghi. |
| Nội dung | Không phải nguồn của đơn hàng; cả endpoint chính và alias cũ đều xóa SQL. Phạm vi là bản ghi kế hoạch trong ứng dụng. |
| Vấn đề | Xóa bình luận riêng cùng transaction. |
| Biến thể | Không còn tồn và chưa có trong đơn hàng; frontend dùng đúng `/products/variants`. |
| Danh mục | Không có con và không còn sản phẩm sử dụng. |

Các kiểm tra tham chiếu đọc SQL trong transaction thay vì dựa vào danh sách
trong bộ nhớ. Danh sách cũ và cache được cập nhật sau commit. Không xóa thử dữ
liệu nghiệp vụ production.

## Thay thế theo từng dòng

- `MaterialUsage.alternative_material_ids` vẫn là danh sách không giới hạn số
  phương án cho một dòng; loại trùng và loại chính nguyên liệu của dòng đó.
- Form job chỉ hiển thị nguyên liệu chính và các phương án của dòng đang chọn.
  Dòng nguyên liệu bổ sung ngoài BOM được ghi rõ và có thể chọn từ toàn bộ kho.
- Job lưu `bom_line_index`, `bom_material_id` và danh sách thay thế vào
  `materials_json`. Khi sửa job, giữ snapshot của job để thay đổi BOM sản phẩm
  sau đó không đổi danh sách/định mức đã lưu.
- Backend kiểm tra nguyên liệu có thuộc dòng nguồn hay không. Không gom các dòng
  cùng chọn một nguyên liệu: giữ định mức/hao hụt riêng, cộng đúng khi giữ chỗ và
  xuất kho. Thiếu tổng tồn phải rollback toàn bộ transaction.
- Job cũ thiếu thông tin nguồn chỉ suy ra dòng khi khớp duy nhất; trường hợp
  không xác định giữ nguyên nguyên liệu thực tế thay vì tự gán nhầm dòng BOM.
- Không thêm cột SQL; dữ liệu nguồn nằm trong JSON hiện có.

Kiểm tra: 43/43 unittest qua trên SQLite và schema Neon `lito_qa_*` riêng đã được
dọn. Có kiểm thử xóa thật và 404 sau xóa, dữ liệu liên kết/stock/payment được giữ,
quyền ADMIN, alias nội dung, nhiều phương án mỗi dòng, hai dòng dùng chung len,
rollback thiếu tổng tồn, sửa job theo snapshot. Node kiểm tra lựa chọn từng dòng;
ESLint các file sửa và build frontend qua. Chrome QA kiểm tra tạo job với hai
nguồn riêng, định mức 10/15, xóa sản phẩm nháp và chặn sản phẩm có job.

Kiểm tra liên quan phát hiện và sửa sai tên trường khách hàng (`notes`,
`tags_json`), trường ngày/doanh thu của đơn trong thống kê khách hàng, và các
trường tạo đơn từng bị bỏ sót (`payment_status`, `source_content_id`, người làm,
thông tin vận chuyển). Các trường này cần đúng để kiểm tra liên kết khi xóa.
