import asyncio
import logging
import os
from datetime import datetime
import pytz
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# ---------------------------------------------------------
# 1. CONFIGURATION & SETUP
# ---------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [STATS SERVICE] - %(levelname)s - %(message)s"
)
logger = logging.getLogger("stats_service")

CONF = {
    "ADMIN_BOT_TOKEN": os.getenv("ADMIN_BOT_TOKEN"),
    "MONGO_URL": os.getenv("MONGODB_URL", "mongodb://localhost:27017"),
    "DB_NAME": os.getenv("DB_NAME", "act_cast_db"),
    "REPORT_CHANNEL_ID": os.getenv("REPORT_CHANNEL_ID"),  # یا متغیر جداگانه
    "INTERVAL": 3600,  # 1 Hour in seconds
    "TIMEZONE": "Asia/Tehran"  # برای نمایش ساعت در گزارش
}

# Validation
if not CONF["ADMIN_BOT_TOKEN"] or not CONF["REPORT_CHANNEL_ID"]:
    raise ValueError("Token or Channel ID is missing in .env")

# ---------------------------------------------------------
# 2. DATABASE LOGIC
# ---------------------------------------------------------


class StatsManager:
    def __init__(self):
        self.client = AsyncIOMotorClient(CONF["MONGO_URL"])
        self.db = self.client[CONF["DB_NAME"]]
        self.users = self.db["users"]

    async def get_total_users(self):
        """تعداد کل کاربرانی که در دیتابیس هستند"""
        return await self.users.count_documents({})

    async def get_history_breakdown(self):
        """
        با استفاده از Aggregation تعداد افراد در هر مرحله از history را می‌شمارد.
        فرض بر این است که history یک لیست از آبجکت‌هاست که کلید value دارد.
        """
        pipeline = [
            # 1. آرایه history را باز می‌کند (هر آیتم تبدیل به یک داکیومنت می‌شود)
            {"$unwind": "$history"},

            # 2. بر اساس مقدار value گروه‌بندی می‌کند و می‌شمارد
            {
                "$group": {
                    "_id": "$history.value",
                    "count": {"$sum": 1}
                }
            },

            # 3. مرتب‌سازی از بیشترین به کمترین
            {"$sort": {"count": -1}}
        ]

        cursor = self.users.aggregate(pipeline)
        return await cursor.to_list(length=None)

# ---------------------------------------------------------
# 3. REPORT GENERATOR
# ---------------------------------------------------------


def create_report_text(total_users, history_stats):
    tz = pytz.timezone(CONF["TIMEZONE"])
    now = datetime.now(tz).strftime("%Y-%m-%d | %H:%M")

    text = (
        f"📊 **گزارش آماری ربات**\n"
        f"📅 تاریخ: `{now}`\n"
        f"👥 **کل کاربران:** `{total_users:,}` نفر\n"
        f"──────────────────\n"
        f"📌 **آمار تفکیکی:**\n"
    )

    if not history_stats:
        text += "▫️ هنوز دیتایی در هیستوری ثبت نشده است."
    else:
        for item in history_stats:
            step_name = item.get("_id", "نامشخص")
            count = item.get("count", 0)
            # محاسبه درصد (اختیاری)
            percent = (count / total_users * 100) if total_users > 0 else 0

            text += f"🔹 **{step_name}**: `{count}` نفر ({percent:.1f}%)\n"

    return text

# ---------------------------------------------------------
# 4. MAIN SERVICE LOOP
# ---------------------------------------------------------


async def send_to_telegram(text):
    bot = Bot(
        token=CONF["ADMIN_BOT_TOKEN"],
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    try:
        await bot.send_message(
            chat_id=CONF["REPORT_CHANNEL_ID"],
            text=text
        )
        logger.info("Report sent to Telegram successfully.")
    except Exception as e:
        logger.error(f"Telegram Error: {e}")
    finally:
        await bot.session.close()


async def run_scheduler():
    db_manager = StatsManager()
    logger.info("Stats Service Started...")

    while True:
        try:
            logger.info("Generating report...")

            # 1. Fetch Data
            total = await db_manager.get_total_users()
            breakdown = await db_manager.get_history_breakdown()

            # 2. Format Message
            message = create_report_text(total, breakdown)

            # 3. Send
            await send_to_telegram(message)

        except Exception as e:
            logger.error(f"Critical Error in loop: {e}")

        # Wait for next hour
        logger.info(f"Sleeping for {CONF['INTERVAL']} seconds...")
        await asyncio.sleep(CONF['INTERVAL'])

if __name__ == "__main__":
    try:
        asyncio.run(run_scheduler())
    except KeyboardInterrupt:
        pass
