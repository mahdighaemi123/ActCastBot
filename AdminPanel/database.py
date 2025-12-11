import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from config import CONF
from datetime import datetime


class DatabaseService:
    def __init__(self):
        self.client = AsyncIOMotorClient(CONF["MONGO_URL"])
        self.db = self.client[CONF["DB_NAME"]]
        self.casts = self.db["casts"]
        self.users = self.db["users"]

    async def add_new_cast(self, name: str, chat_id: int, message_id: int):
        new_cast = {
            "name": name,
            "source_chat_id": chat_id,
            "source_message_id": message_id,
            "created_at": asyncio.get_event_loop().time()
        }
        await self.casts.update_one(
            {"name": name},
            {"$set": new_cast},
            upsert=True
        )

    async def delete_cast(self, name: str):
        result = await self.casts.delete_one({"name": name})
        return result.deleted_count > 0

    async def get_all_cast_names(self):
        cursor = self.casts.find({}, {"name": 1})
        return await cursor.to_list(length=None)


async def get_users_in_range(self, start_ts: float, end_ts: float):
    """
    دریافت کاربران با تبدیل Timestamp ورودی به DateTime قابل فهم برای مونگو
    """
    # --- تبدیل Timestamp به Datetime ---
    start_date = datetime.fromtimestamp(start_ts)
    end_date = datetime.fromtimestamp(end_ts)

    query = {
        "created_at": {
            "$gte": start_date,  # مقایسه تاریخ با تاریخ
            "$lte": end_date
        }
    }

    # لاگ برای دیباگ (اختیاری)
    # print(f"Querying from {start_date} to {end_date}")

    cursor = self.users.find(query, {"user_id": 1})
    return await cursor.to_list(length=None)


# ساخت یک آبجکت که در بقیه فایل‌ها استفاده شود
db = DatabaseService()
