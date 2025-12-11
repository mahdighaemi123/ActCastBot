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
        self.broadcast_logs = self.db["broadcast_logs"]

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

        start_date = datetime.fromtimestamp(start_ts)
        end_date = datetime.fromtimestamp(end_ts)

        query = {
            "created_at": {
                "$gte": start_date,
                "$lte": end_date
            }
        }

        cursor = self.users.find(query, {"user_id": 1})
        return await cursor.to_list(length=None)

    async def save_broadcast_log(self, batch_id: str, user_id: int, message_id: int):
        """
        Saves a record of a sent message to allow future deletion.
        """
        log_entry = {
            "batch_id": batch_id,
            "user_id": user_id,
            "message_id": message_id,
            "sent_at": datetime.now()
        }
        await self.broadcast_logs.insert_one(log_entry)

    async def get_broadcast_logs(self, batch_id: str):
        """
        Retrieves all message IDs associated with a specific broadcast batch.
        """
        cursor = self.broadcast_logs.find(
            {"batch_id": batch_id}, {"user_id": 1, "message_id": 1})
        return await cursor.to_list(length=None)

    async def get_all_casts(self):
        """Fetches all casts to generate buttons."""
        cursor = self.casts.find()
        return await cursor.to_list(length=None)

# In database.py -> DatabaseService class

    async def save_broadcast_batch(self, batch_id: str, start_ts: float, end_ts: float, total_users: int, messages: list):
        """
        Creates the batch record with initial status 'processing'.
        """
        batch_data = {
            "batch_id": batch_id,
            "filter_start_ts": start_ts,
            "filter_end_ts": end_ts,
            "total_users_target": total_users,
            "messages_data": messages,  # Optional: save what messages were sent
            "created_at": datetime.now(),
            "status": "processing",  # 🟡 Initial status
            "sent_count": 0,
            "blocked_count": 0
        }
        await self.db["broadcast_batches"].insert_one(batch_data)

    async def update_broadcast_batch_stats(self, batch_id: str, success: int, blocked: int):
        """
        Updates the batch status to 'completed' with final counts.
        """
        await self.db["broadcast_batches"].update_one(
            {"batch_id": batch_id},
            {
                "$set": {
                    "status": "completed",      # 🟢 Final status
                    "sent_count": success,
                    "blocked_count": blocked,
                    "finished_at": datetime.now()
                }
            }
        )


# ساخت یک آبجکت که در بقیه فایل‌ها استفاده شود
db = DatabaseService()
