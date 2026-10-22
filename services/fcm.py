"""Firebase Cloud Messaging delivery with explicit outcomes and safe errors."""
import json
import os
from pathlib import Path

try:
    import firebase_admin
    from firebase_admin import credentials, messaging
    _firebase_available = True
except ImportError:
    _firebase_available = False

_app = None
_last_error = None


def _init() -> bool:
    global _app, _last_error
    if _app is not None:
        return True
    if not _firebase_available:
        _last_error = "sdk_unavailable"
        return False
    raw = os.getenv("FIREBASE_CREDENTIALS_JSON", "").strip()
    path = Path(os.getenv("FIREBASE_CREDENTIALS") or Path(__file__).resolve().parents[1] / "firebase-adminsdk.json")
    if not raw and not path.is_file():
        _last_error = "credentials_missing"
        return False
    try:
        info = json.loads(raw) if raw else json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(info, dict) or info.get("type") != "service_account":
            raise ValueError("Expected service account")
        _app = firebase_admin.initialize_app(credentials.Certificate(info), name="lito-notifications")
        _last_error = None
        return True
    except (OSError, ValueError, TypeError):
        _last_error = "credentials_invalid"
        return False


def delivery_status() -> dict:
    return {"push_configured": _init(), "configuration_error": _last_error}


def send_many_result(tokens: list[str], title: str, body: str, data: dict = None) -> dict:
    """Accepted means FCM accepted the message, not proof of OS display/read."""
    result = {"attempted": len(tokens), "accepted": 0, "failed": 0,
              "invalid_tokens": [], "error_codes": []}
    if not tokens:
        return result
    if not _init():
        result.update(failed=len(tokens), error_codes=[_last_error])
        return result
    frontend = os.getenv("FRONTEND_URL", "https://admin.litohandmade.com").rstrip("/")
    for start in range(0, len(tokens), 500):
        batch = tokens[start:start + 500]
        try:
            msg = messaging.MulticastMessage(
                notification=messaging.Notification(title=title, body=body),
                data={key: str(value) for key, value in (data or {}).items()},
                webpush=messaging.WebpushConfig(
                    notification=messaging.WebpushNotification(
                        title=title, body=body, icon=f"{frontend}/pwa-192x192.png",
                    ),
                    fcm_options=messaging.WebpushFCMOptions(link=f"{frontend}/#/notifications"),
                ),
                tokens=batch,
            )
            response = messaging.send_each_for_multicast(msg, app=_app)
            result["accepted"] += response.success_count
            result["failed"] += response.failure_count
            for token, item in zip(batch, response.responses):
                if not item.success:
                    if isinstance(item.exception, messaging.UnregisteredError):
                        result["invalid_tokens"].append(token)
                    result["error_codes"].append(type(item.exception).__name__)
        except Exception as exc:
            result["failed"] += len(batch)
            result["error_codes"].append(type(exc).__name__)
    result["error_codes"] = sorted(set(result["error_codes"]))
    return result


def send_many(tokens: list[str], title: str, body: str, data: dict = None) -> int:
    return send_many_result(tokens, title, body, data)["accepted"]


def send_one(token: str, title: str, body: str, data: dict = None) -> bool:
    return bool(send_many([token], title, body, data))
