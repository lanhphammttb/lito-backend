# Hala Handmade Backend - Setup Guide

Dự án FastAPI backend (đã được cấu trúc lại Modular)

## Yêu cầu hệ thống
- Python 3.10+
- PostgreSQL (hoặc dùng mặc định SQLite in-memory)

## Cài đặt trên macOS / Linux

1. Mở Terminal và di chuyển vào thư mục `backend`:
   ```bash
   cd path/to/hala_handmade/backend
   ```
2. Tạo môi trường ảo (virtual environment) và kích hoạt:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
3. Cài đặt các thư viện yêu cầu:
   ```bash
   pip install -r requirements.txt
   ```
4. Cấu hình biến môi trường (`.env`):
   Sửa file `.env` chứa các biến cần thiết (VD: `DATABASE_URL`, `JWT_SECRET`). Nếu không có Database PostgreSQL, dự án sẽ tự động fallback về in-memory SQLite.
5. Chạy dự án:
   ```bash
   uvicorn main:app --reload --port 8000
   ```

## Cài đặt trên Windows

1. Mở Command Prompt (cmd) hoặc PowerShell và di chuyển vào thư mục `backend`:
   ```cmd
   cd path\to\hala_handmade\backend
   ```
2. Tạo môi trường ảo (virtual environment):
   ```cmd
   python -m venv .venv
   ```
3. Kích hoạt môi trường ảo:
   - Trên **Command Prompt**:
     ```cmd
     .venv\Scripts\activate.bat
     ```
   - Trên **PowerShell**:
     ```powershell
     .venv\Scripts\Activate.ps1
     ```
   *(Lưu ý: Nếu PowerShell báo lỗi Execution Policy, bạn cần chạy `Set-ExecutionPolicy Unrestricted -Scope CurrentUser` trước).*
4. Cài đặt các thư viện yêu cầu:
   ```cmd
   pip install -r requirements.txt
   ```
5. Chạy dự án:
   ```cmd
   uvicorn main:app --reload --port 8000
   ```

## Thông tin đăng nhập mặc định (Seed Data)
Cơ sở dữ liệu tự động tạo một số tài khoản mặc định lúc khởi động:
- **Thợ Lan**: `maker_lan@example.com` | Mật khẩu: `maker123`
- **Owner**: `owner_a@example.com` | Mật khẩu: *(In ra log Terminal lúc start server "Mật khẩu tạm thời: ...")*
