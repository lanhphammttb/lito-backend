import os
import copy
from typing import List
from dotenv import load_dotenv
from sqlmodel import Session, select
from pymongo import MongoClient

load_dotenv()

from config.database import engine
from models.user import UserTable
from models.product import ProductTable
from models.material import MaterialTable
from models.order import OrderTable
from models.category import CategoryTable
from models.customer import CustomerTable
from models.season import SeasonTable
from models.task import TaskTable
from models.idea import IdeaTable
from models.issue import IssueTable
from models.experiment import ExperimentTable
from models.activity import ActivityLogTable

# Dictionary mapping mongo collections to SQLModel classes
COLLECTIONS = {
    "users": UserTable,
    "products": ProductTable,
    "materials": MaterialTable,
    "orders": OrderTable,
    "categories": CategoryTable,
    "customers": CustomerTable,
    "seasons": SeasonTable,
    "tasks": TaskTable,
    "ideas": IdeaTable,
    "issues": IssueTable,
    "experiments": ExperimentTable,
    "activity_logs": ActivityLogTable,
}

def clean_doc(doc: dict) -> dict:
    """Xóa các field dư thừa của MongoDB như _id"""
    d = copy.deepcopy(doc)
    if "_id" in d:
        del d["_id"]
    return d

def sync_mongo_to_sql():
    mongo_url = os.getenv("MONGO_URL")
    if not mongo_url:
        print("[-] MONGO_URL chưa được cấu hình trong .env!")
        return

    print(f"[*] Kết nối tới MongoDB...")
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
    db = client["hala_handmade"]
    
    with Session(engine) as session:
        for col_name, model_cls in COLLECTIONS.items():
            print(f"[*] Đồng bộ collection: {col_name} -> {model_cls.__name__}")
            docs = list(db[col_name].find())
            
            # Xóa sạch data hiện tại trong SQL db map với model này
            existing = session.exec(select(model_cls)).all()
            for e in existing:
                session.delete(e)
            session.commit()
            
            # Insert mongo
            inserted_count = 0
            for doc in docs:
                cleaned = clean_doc(doc)
                import json
                try:
                    if col_name == "activity_logs" and "changes" in cleaned and isinstance(cleaned["changes"], dict):
                        cleaned["changes"] = json.dumps(cleaned["changes"])
                    if col_name == "orders" and not cleaned.get("order_date"):
                        from datetime import datetime
                        d = cleaned.get("created_at") or str(datetime.utcnow())
                        cleaned["order_date"] = d.split("T")[0].split(" ")[0]
                    if col_name == "ideas" and "name" in cleaned and "title" not in cleaned:
                        cleaned["title"] = cleaned["name"]
                    
                    # Chuyển đổi qua pydantic trước để fill các default
                    obj = model_cls.model_validate(cleaned)
                    session.add(obj)
                    inserted_count += 1
                except Exception as e:
                    print(f"    [!] Bỏ qua record lỗi ở {col_name}: {e}")
            
            try:
                session.commit()
            except Exception as e:
                session.rollback()
                print(f"    [!] Lỗi khi commit {col_name}: {e}")
            print(f"    -> Đã đồng bộ {inserted_count} / {len(docs)} bản ghi")
            
    print("[+] Hoàn tất đồng bộ từ MongoDB vào SQL!")

if __name__ == "__main__":
    sync_mongo_to_sql()