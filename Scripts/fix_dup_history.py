import asyncio
import os
import logging
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# تنظیمات لاگ
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger("fix_history")

# بارگذاری متغیرها
load_dotenv()

MONGO_URL = os.getenv(
    "MONGO_URL", "mongodb://mongo_user:mongo_pass@95.217.69.70:3003/tg?authSource=admin")
DB_NAME = os.getenv("DB_NAME", "act_cast_db")


async def clean_duplicate_history():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    users_collection = db["users"]

    logger.info("⏳ در حال شروع عملیات پاک‌سازی تاریخچه...")

    # دریافت تمام کاربران که هیستوری دارند
    cursor = users_collection.find(
        {"history": {"$exists": True, "$not": {"$size": 0}}})

    processed_count = 0
    updated_count = 0

    async for user in cursor:
        processed_count += 1
        user_id = user.get("user_id")
        original_history = user.get("history", [])

        # -------------------------------------------
        # منطق حذف تکراری‌ها
        # -------------------------------------------
        seen_values = set()
        clean_history = []

        for item in original_history:
            # دریافت مقدار دکمه یا کلمه کلیدی
            val = item.get("value")

            # اگر این مقدار قبلا دیده نشده، به لیست تمیز اضافه کن
            if val not in seen_values:
                seen_values.add(val)
                clean_history.append(item)

        # -------------------------------------------
        # بررسی تغییرات و آپدیت
        # -------------------------------------------
        # اگر تعداد آیتم‌ها کم شده، یعنی تکراری وجود داشته
        if len(clean_history) < len(original_history):
            await users_collection.update_one(
                {"_id": user["_id"]},
                {"$set": {"history": clean_history}}
            )
            updated_count += 1
            logger.info(
                f"✅ User {user_id}: Fixed (Reduced from {len(original_history)} to {len(clean_history)})")

        # نمایش پیشرفت هر 100 کاربر
        if processed_count % 100 == 0:
            logger.info(f"🔄 Processed {processed_count} users...")

    logger.info("------------------------------------------------")
    logger.info(f"🎉 عملیات تمام شد.")
    logger.info(f"👥 کل کاربران بررسی شده: {processed_count}")
    logger.info(f"🛠 کاربران اصلاح شده: {updated_count}")

if __name__ == "__main__":
    try:
        asyncio.run(clean_duplicate_history())
    except KeyboardInterrupt:
        pass
