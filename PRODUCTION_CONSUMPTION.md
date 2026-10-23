# Điều chỉnh tiêu hao đã ghi nhận

Khi nhập sai lượng nguyên liệu của lệnh đã bắt đầu/hoàn thành, ADMIN mở **Sản xuất → Xem chi tiết → Điều chỉnh tiêu hao**. Nhập **tổng lượng đúng cho cả lệnh**, không phải định mức một sản phẩm, cùng lý do.

Ví dụ lệnh 2 sản phẩm ghi 20 g nhưng thực tế dùng 12 g: điều chỉnh về 12 g hoàn kho đúng 8 g. Sửa 12 g thành 25 g thì xuất thêm 13 g. Số thành phẩm, trạng thái, định mức mẫu và mức giá nguyên liệu đã lưu của lệnh không đổi. Chi phí nguyên liệu hiển thị của lệnh dùng lượng thực tế mới × mức giá đã lưu. Giá vốn ước tính đã lưu ở đơn hàng không được tự viết lại; giá vốn bán hàng thực theo lô chưa triển khai.

Kho, lô, lượng tiêu hao, giao dịch điều chỉnh và nhật ký trước/sau được lưu cùng một transaction. Yêu cầu gửi lại cùng lượng không sinh giao dịch lần nữa. Bản dữ liệu cũ bị từ chối nếu đã có điều chỉnh khác. Nhu cầu xuất thêm được gộp theo nguyên liệu và không sử dụng lượng đang giữ cho lệnh khác. Vật tư dạng cái chỉ nhận số nguyên; vật tư liên tục hỗ trợ 4 chữ số thập phân; lượng 0 hợp lệ.

Xuất thêm trừ lô theo FIFO. Do dữ liệu tiêu hao cũ chưa lưu phân bổ lô gốc, hoàn kho tạo lô điều chỉnh riêng, không đoán rồi sửa lại lô nhập cũ. Giá lô hoàn dựa trên mức giá đã lưu; nếu lịch sử thiếu giá thì giữ chi phí lệnh ở trạng thái chưa biết và ghi rõ giá lô hoàn chỉ tham khảo từ giá nguyên liệu hiện hành.

Lịch sử nằm ngay trong chi tiết lệnh (100 lần gần nhất), trong lịch sử xuất/nhập kho và nhật ký kiểm toán. ADMIN không thể xóa lệnh đã sản xuất dù đã điều chỉnh lượng về 0: đây không phải chức năng hủy sản xuất hoặc tháo dỡ thành phẩm. Trường hợp lệnh được tạo nhầm cả sản lượng cần một nghiệp vụ đảo sản xuất riêng, có đối chiếu thành phẩm đã giao.

Không tự sửa dữ liệu vận hành vì chưa biết lệnh và lượng đúng của người dùng. Kiểm chứng dùng DB thử: 76 test backend, 11 test frontend, lint/build và 4 ca điều chỉnh trên schema Neon riêng đều qua. Đã thực hiện điều chỉnh 20 → 12 g qua giao diện bản build, tải lại, đối chiếu kho 80 → 88 g và giữ nguyên tồn thành phẩm. Không cần migration mới.
