import asyncio
import logging
import os
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from aiogram import Bot
from aiogram.types import FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import re
# ---------------------------------------------------------
# 1. CONFIGURATION & LOGGING
# ---------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [BACKUP SERVICE] - %(levelname)s - %(message)s"
)
logger = logging.getLogger("backup_service")

# Configuration
CONF = {
    "ADMIN_BOT_TOKEN": os.getenv("ADMIN_BOT_TOKEN"),
    "MONGO_URL": os.getenv("MONGODB_URL", "mongodb://localhost:27017"),
    "DB_NAME": os.getenv("DB_NAME", "act_cast_db"),
    # Example: "-1001234567890"
    "BACKUP_CHANNEL_ID": os.getenv("BACKUP_CHANNEL_ID"),
    # Default 1 hour (3600s)
    "BACKUP_INTERVAL": int(os.getenv("BACKUP_INTERVAL", 3600))
}

# Validation
if not CONF["ADMIN_BOT_TOKEN"]:
    raise ValueError("ADMIN_BOT_TOKEN is missing in .env")
if not CONF["BACKUP_CHANNEL_ID"]:
    raise ValueError(
        "BACKUP_CHANNEL_ID is missing in .env (Required for sending backups)")

# ---------------------------------------------------------
# 2. CORE FUNCTIONS
# ---------------------------------------------------------


def convert_to_english_digits(text):
    """Convert Persian digits in the input text to English digits."""
    if not isinstance(text, str):
        return text
    persian_digits = '۰۱۲۳۴۵۶۷۸۹'
    english_digits = '0123456789'
    trans_table = str.maketrans(persian_digits, english_digits)
    return text.translate(trans_table)


def remove_trailing_dot_zero(text):
    """Remove trailing '.0' or '.00' from the input text."""
    if not isinstance(text, str):
        return text
    if text.endswith('.00'):
        return text[:-3]
    elif text.endswith('.0'):
        return text[:-2]
    return text


def standardize_phone_number(phone):
    """Standardize phone numbers to the format '09xxxxxxxxx'."""
    if phone is None or phone == "":
        return phone

    phone = str(phone).strip()
    phone = remove_trailing_dot_zero(phone)
    phone = convert_to_english_digits(phone)
    phone = re.sub(r'\D', '', phone)

    if phone.startswith('+98'):
        phone = '0' + phone[3:]

    elif phone.startswith('0098'):
        phone = '0' + phone[4:]

    elif phone.startswith('98'):
        phone = '0' + phone[2:]

    if len(phone) == 10:
        if not phone.startswith('0'):
            phone = '0' + phone

    return phone


async def fetch_users_data():
    """Fetches all user documents from MongoDB."""
    client = AsyncIOMotorClient(CONF["MONGO_URL"])
    db = client[CONF["DB_NAME"]]
    users_collection = db["users"]

    # Fetch all users
    users = await users_collection.find().to_list(length=None)
    client.close()
    return users


def format_history_list(history_data):
    """
    Extracts only 'value' from the history list and joins them with commas.
    Input: [{'value': 'A', ...}, {'value': 'B', ...}]
    Output: "A, B"
    """
    if isinstance(history_data, list):
        # استخراج مقدار value از هر آیتم لیست
        # فقط در صورتی که دیکشنری باشد و کلید value را داشته باشد
        values = [str(item.get('value', '')) for item in history_data if isinstance(
            item, dict) and item.get('value')]
        return ", ".join(values)
    return ""


def generate_excel(users_data, filename):
    """Converts user data list to an Excel file using Pandas."""
    if not users_data:
        return False

    df = pd.DataFrame(users_data)

    # Optional: Clean up data (e.g., convert ObjectIds to string)
    if '_id' in df.columns:
        df['_id'] = df['_id'].astype(str)

    # Optional: Format datetime columns if they exist
    if 'created_at' in df.columns:
        df['created_at'] = pd.to_datetime(
            df['created_at']).dt.strftime('%Y-%m-%d %H:%M:%S')

    if 'phone' in df.columns:
        df['phone'] = df['phone'].apply(standardize_phone_number)

    if 'history' in df.columns:
        df['history'] = df['history'].apply(format_history_list)

    # Save to Excel
    df.to_excel(filename, index=False, engine='openpyxl')
    return True


async def send_backup(filename):
    """Sends the generated file to the Telegram channel."""
    bot = Bot(
        token=CONF["ADMIN_BOT_TOKEN"],
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )

    try:
        file = FSInputFile(filename)
        caption = f"📊 **User Database Backup**\n📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        await bot.send_document(
            chat_id=CONF["BACKUP_CHANNEL_ID"],
            document=file,
            caption=caption
        )
        logger.info(f"Backup sent successfully to {CONF['BACKUP_CHANNEL_ID']}")
    except Exception as e:
        logger.error(f"Failed to send backup: {e}")
    finally:
        await bot.session.close()

# ---------------------------------------------------------
# 3. MAIN LOOP
# ---------------------------------------------------------


async def run_scheduler():
    logger.info("Backup Service Started. Waiting for the first interval...")

    # Loop forever
    while True:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"users_backup_{timestamp}.xlsx"

            logger.info("Starting backup process...")

            # 1. Fetch Data
            users = await fetch_users_data()
            if users:
                logger.info(f"Fetched {len(users)} users.")

                # 2. Generate Excel
                success = generate_excel(users, filename)

                if success:
                    # 3. Send to Telegram
                    await send_backup(filename)

                    # 4. Cleanup local file
                    if os.path.exists(filename):
                        os.remove(filename)
                        logger.info("Local backup file cleaned up.")
                else:
                    logger.warning(
                        "Could not generate Excel file (Empty data?).")
            else:
                logger.info("No users found in database. Skipping backup.")

        except Exception as e:
            logger.error(f"An error occurred during backup cycle: {e}")

        # Wait for the next interval
        logger.info(f"Sleeping for {CONF['BACKUP_INTERVAL']} seconds...")
        await asyncio.sleep(CONF["BACKUP_INTERVAL"])

if __name__ == "__main__":
    try:
        asyncio.run(run_scheduler())
    except KeyboardInterrupt:
        logger.info("Backup service stopped by user.")
