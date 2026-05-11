"""Firebase Cloud Messaging service."""
import os
from typing import List

try:
    import firebase_admin
    from firebase_admin import credentials, messaging
    _firebase_available = True
except ImportError:
    _firebase_available = False

_app = None


def _init() -> bool:
    """Initialize Firebase Admin SDK from service account file."""
    global _app
    if not _firebase_available:
        return False
    if _app is not None:
        return True
    cred_path = os.environ.get(
        "FIREBASE_CREDENTIALS",
        os.path.join(os.path.dirname(__file__), '..', 'firebase-adminsdk.json')
    )
    if not os.path.exists(cred_path):
        print("[FCM] firebase-adminsdk.json not found — push disabled")
        return False
    try:
        cred = credentials.Certificate(cred_path)
        _app = firebase_admin.initialize_app(cred)
        print("[FCM] Firebase Admin initialized")
        return True
    except Exception as e:
        print(f"[FCM] Init error: {e}")
        return False


def send_one(token: str, title: str, body: str, data: dict = None) -> bool:
    """Send push notification to a single FCM token."""
    if not _init():
        return False
    try:
        msg = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            webpush=messaging.WebpushConfig(
                notification=messaging.WebpushNotification(
                    title=title,
                    body=body,
                    icon='/pwa-192x192.png',
                )
            ),
            token=token,
        )
        messaging.send(msg)
        return True
    except Exception as e:
        print(f"[FCM] send_one error: {e}")
        return False


def send_many(tokens: List[str], title: str, body: str, data: dict = None) -> int:
    """Send push notification to multiple FCM tokens. Returns success count."""
    if not _init() or not tokens:
        return 0
    # FCM multicast limit is 500 tokens per call
    success = 0
    for i in range(0, len(tokens), 500):
        batch = tokens[i:i + 500]
        try:
            msg = messaging.MulticastMessage(
                notification=messaging.Notification(title=title, body=body),
                data={k: str(v) for k, v in (data or {}).items()},
                webpush=messaging.WebpushConfig(
                    notification=messaging.WebpushNotification(
                        title=title,
                        body=body,
                        icon='/pwa-192x192.png',
                    )
                ),
                tokens=batch,
            )
            resp = messaging.send_each_for_multicast(msg)
            success += resp.success_count
        except Exception as e:
            print(f"[FCM] send_many batch error: {e}")
    return success
