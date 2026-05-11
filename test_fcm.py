"""
Script test gửi FCM push notification.
Chạy: python test_fcm.py
"""
import sys
import os

# Đảm bảo đọc được firebase-adminsdk.json
os.chdir(os.path.dirname(__file__))

from services.fcm import _init, send_one, send_many

def test_init():
    ok = _init()
    if ok:
        print("✅ Firebase Admin khởi động thành công")
    else:
        print("❌ Firebase Admin KHÔNG khởi động được")
        print("   Kiểm tra file: backend/firebase-adminsdk.json")
    return ok

def test_send(token: str):
    print(f"\nGửi notification đến token: {token[:30]}...")
    ok = send_one(
        token=token,
        title="🔔 Test từ Hala Handmade",
        body="FCM hoạt động! Thời gian: " + __import__('datetime').datetime.now().strftime("%H:%M:%S"),
        data={"test": "true", "source": "test_fcm.py"}
    )
    if ok:
        print("✅ Gửi thành công! Kiểm tra notification trên màn hình")
    else:
        print("❌ Gửi thất bại — xem log ở trên")

if __name__ == "__main__":
    if not test_init():
        sys.exit(1)

    if len(sys.argv) > 1:
        # python test_fcm.py <FCM_TOKEN>
        test_send(sys.argv[1])
    else:
        # Lấy token từ DB
        try:
            from config.database import engine
            from sqlmodel import Session, select
            from models.notifications import FcmTokenTable
            with Session(engine) as session:
                tokens = session.exec(select(FcmTokenTable)).all()
            if not tokens:
                print("\n⚠️  Chưa có FCM token nào trong DB")
                print("   Hãy mở app trên browser, đăng nhập, cho phép notification")
                print("   Sau đó chạy lại script này")
            else:
                print(f"\nTìm thấy {len(tokens)} token(s) trong DB:")
                for t in tokens:
                    print(f"  User {t.user_id}: {t.token[:40]}...")
                    test_send(t.token)
        except Exception as e:
            print(f"\n❌ Không kết nối được DB: {e}")
            print("   Chạy: python test_fcm.py <FCM_TOKEN>")
