# Điều chỉnh tiêu hao đã ghi nhận

Khi nhập sai loại hoặc lượng nguyên liệu của lệnh đã bắt đầu/hoàn thành, ADMIN mở **Sản xuất → Xem chi tiết → Điều chỉnh nguyên liệu**. Có ô tìm nguyên liệu theo tên/mã. Chọn nguyên liệu đúng và nhập **tổng lượng đúng cho cả lệnh**, không phải định mức một sản phẩm, cùng lý do. Nhập 0 nếu dòng đó thực tế không dùng.

Ví dụ lệnh 2 sản phẩm ghi 20 g nhưng thực tế dùng 12 g: điều chỉnh về 12 g hoàn kho đúng 8 g. Sửa 12 g thành 25 g thì xuất thêm 13 g. Nếu đổi 12 g len A thành 7 g len B, hệ thống hoàn 12 g A và xuất 7 g B. Số thành phẩm, trạng thái và định mức mẫu giữ nguyên. Cùng nguyên liệu giữ mức giá đã lưu; đổi sang nguyên liệu khác lưu giá hiện tại tại lần điều chỉnh và đánh dấu nguồn giá này. Chi phí nguyên liệu hiển thị dùng lượng mới × mức giá đã lưu, chưa phải giá vốn thực theo lô. Giá vốn ước tính đã lưu ở đơn hàng không tự viết lại.

Định mức ban đầu của lệnh giữ riêng, kể cả khi nguyên liệu thực tế đổi loại/đơn vị. Đổi loại phải nhập lại lượng dùng; không tự chuyển đổi gram sang cái hay sang đơn vị khác. Đây là sửa ghi nhận thực tế nên có thể chọn nguyên liệu ngoài danh sách thay thế của BOM. Luồng lập lệnh mới vẫn giới hạn các phương án theo từng dòng BOM như trước.

Kho, lô, lượng tiêu hao, giao dịch điều chỉnh và nhật ký trước/sau được lưu cùng một transaction. Yêu cầu gửi lại cùng lượng không sinh giao dịch lần nữa. Bản dữ liệu cũ bị từ chối nếu đã có điều chỉnh khác. Nhu cầu xuất thêm được gộp theo nguyên liệu và không sử dụng lượng đang giữ cho lệnh khác. Vật tư dạng cái chỉ nhận số nguyên; vật tư liên tục hỗ trợ 4 chữ số thập phân; lượng 0 hợp lệ.

Xuất thêm trừ lô theo FIFO. Do dữ liệu tiêu hao cũ chưa lưu phân bổ lô gốc, hoàn kho tạo lô điều chỉnh riêng, không đoán rồi sửa lại lô nhập cũ. Giá lô hoàn dựa trên mức giá đã lưu; nếu lịch sử thiếu giá thì giữ chi phí lệnh ở trạng thái chưa biết và ghi rõ giá lô hoàn chỉ tham khảo từ giá nguyên liệu hiện hành.

Lịch sử nằm ngay trong chi tiết lệnh (100 lần gần nhất), trong lịch sử xuất/nhập kho và nhật ký kiểm toán. ADMIN không thể xóa lệnh đã sản xuất dù đã điều chỉnh lượng về 0: đây không phải chức năng hủy sản xuất hoặc tháo dỡ thành phẩm. Trường hợp lệnh được tạo nhầm cả sản lượng cần một nghiệp vụ đảo sản xuất riêng, có đối chiếu thành phẩm đã giao.

Không tự sửa dữ liệu vận hành vì chưa biết lệnh và lượng đúng của người dùng. Kiểm chứng dùng DB thử: 80 test backend, 12 test frontend, lint/build, 4 ca điều chỉnh lượng và 4 ca đổi loại trên schema Neon riêng đều qua. Đã sửa 20 → 12 g rồi đổi A 12 g sang B 7 g qua giao diện bản build; tải lại và đối chiếu kho A về 100 g, kho B còn 93 g, giữ nguyên tồn thành phẩm. Không cần migration mới.
