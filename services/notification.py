"""Notification services."""
import json
import smtplib
from email.message import EmailMessage
from typing import Dict, List, Optional, Any

from config.settings import settings

# WebSocket connection manager
class ConnectionManager:
    """Manage WebSocket connections for real-time notifications."""
    
    def __init__(self):
        self.active_connections: Dict[int, List] = {}
    
    async def connect(self, websocket, user_id: int):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
    
    def disconnect(self, websocket, user_id: int):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
    
    async def send_personal_message(self, message: dict, user_id: int):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except:
                    pass
    
    async def broadcast(self, message: dict):
        for user_id in self.active_connections:
            await self.send_personal_message(message, user_id)


ws_manager = ConnectionManager()


def send_notifications(payload: dict):
    """Send email notifications."""
    recipients = list(settings.notification_emails or [])
    if settings.backup_email:
        recipients.append(settings.backup_email)
    
    if not recipients or not settings.smtp_host:
        print("NOTIFY (log only):", json.dumps(payload, default=str))
        return
    
    try:
        msg = EmailMessage()
        msg["Subject"] = "Handmade OS - Alert"
        msg["From"] = settings.smtp_user or "noreply@example.com"
        msg["To"] = ", ".join(recipients)
        msg.set_content(json.dumps(payload, default=str, indent=2, ensure_ascii=False))
        
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port or 25, timeout=5) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_user and settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
    except Exception as exc:
        print("NOTIFY send failed, fallback log:", exc, payload)


async def notify_new_order(order_data: dict, user_id: int = None):
    """Send notification when new order is created."""
    from datetime import datetime
    
    notification = {
        "type": "new_order",
        "title": "Đơn hàng mới",
        "message": f"Đơn hàng #{order_data.get('id')} - {order_data.get('product_name')}",
        "data": order_data,
        "timestamp": datetime.now().isoformat()
    }
    
    if user_id:
        await ws_manager.send_personal_message(notification, user_id)
    else:
        await ws_manager.broadcast(notification)


async def notify_low_stock(material_data: dict):
    """Send notification when stock is low."""
    from datetime import datetime
    
    notification = {
        "type": "low_stock",
        "title": "Cảnh báo tồn kho",
        "message": f"{material_data.get('name')} sắp hết ({material_data.get('stock_quantity')} {material_data.get('unit')})",
        "data": material_data,
        "timestamp": datetime.now().isoformat()
    }
    
    await ws_manager.broadcast(notification)


async def notify_order_status_change(order_id: int, new_status: str, user_id: int = None):
    """Send notification when order status changes."""
    from datetime import datetime
    
    notification = {
        "type": "order_status",
        "title": "Cập nhật đơn hàng",
        "message": f"Đơn hàng #{order_id} đã chuyển sang: {new_status}",
        "data": {"order_id": order_id, "status": new_status},
        "timestamp": datetime.now().isoformat()
    }
    
    if user_id:
        await ws_manager.send_personal_message(notification, user_id)
    else:
        await ws_manager.broadcast(notification)
