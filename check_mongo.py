import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

mongo_url = os.getenv("MONGO_URL")
if not mongo_url:
    print("NO MONGO URL!")
else:
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
    db = client["hala_handmade"]
    print("Collections:", db.list_collection_names())
    for col in db.list_collection_names():
        count = db[col].count_documents({})
        print(f" - {col}: {count} documents")
