import os
from dotenv import load_dotenv

load_dotenv()

CONF = {
    "BOT_TOKEN": os.getenv("BOT_TOKEN"),
    "ADMIN_BOT_TOKEN": os.getenv("ADMIN_BOT_TOKEN"),
    "MONGO_URL": os.getenv("MONGODB_URL", "mongodb://localhost:27017"),
    "DB_NAME": os.getenv("DB_NAME", "act_cast_db"),
    "ADMIN_IDS": [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x],
    "STORAGE_CHANNEL_ID": int(os.getenv("STORAGE_CHANNEL_ID", "0"))
}

# چک کردن مقادیر حیاتی
if not CONF["ADMIN_BOT_TOKEN"] or not CONF["STORAGE_CHANNEL_ID"] or not CONF["BOT_TOKEN"]:
    raise ValueError(
        "ADMIN_BOT_TOKEN or STORAGE_CHANNEL_ID or BOT_TOKEN is missing in .env")


# تابع چک کردن ادمین
def is_admin(user_id: int) -> bool:
    return user_id in CONF["ADMIN_IDS"]
