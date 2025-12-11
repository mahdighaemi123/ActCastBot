from aiogram.filters import Command
from aiogram import Router, types
import asyncio
import logging
import os
from typing import Dict, Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.mongo import MongoStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)

from datetime import datetime
# ---------------------------------------------------------
# 1. CONFIGURATION & LOGGING
# ---------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("act_cast_bot")

CONF = {
    "BOT_TOKEN": os.getenv("BOT_TOKEN"),
    "MONGO_URL": os.getenv("MONGODB_URL", "mongodb://localhost:27017"),
    "DB_NAME": os.getenv("DB_NAME", "act_cast_db"),
}

if not CONF["BOT_TOKEN"]:
    raise ValueError("BOT_TOKEN is missing in .env")

# ---------------------------------------------------------
# 2. DATABASE SERVICE
# ---------------------------------------------------------


class DatabaseService:
    def __init__(self):
        self.client = AsyncIOMotorClient(CONF["MONGO_URL"])
        self.db = self.client[CONF["DB_NAME"]]
        self.users = self.db["users"]
        self.casts = self.db["casts"]

    async def get_user(self, user_id: int) -> Dict:
        user = await self.users.find_one({"user_id": user_id})
        if not user:
            user = {
                "user_id": user_id,
                "created_at": datetime.now(),
                "profile_completed": False
            }
            await self.users.insert_one(user)
        return user

    async def update_user(self, user_id: int, data: Dict):
        await self.users.update_one(
            {"user_id": user_id},
            {"$set": data},
            upsert=True
        )

    async def get_all_casts(self):
        """Fetches all casts to generate buttons."""
        cursor = self.casts.find()
        return await cursor.to_list(length=None)

    async def get_cast_by_name(self, cast_name: str) -> Optional[Dict]:
        """Finds a specific cast by its button name."""
        return await self.casts.find_one({"name": cast_name})

    async def delete_user(self, user_id: int) -> bool:
        """
        Completely removes the user document from the database.
        Returns True if a document was deleted, False otherwise.
        """
        result = await self.users.delete_one({"user_id": user_id})
        return result.deleted_count > 0
# ---------------------------------------------------------
# 3. FSM STATES
# ---------------------------------------------------------


class UserFlow(StatesGroup):
    waiting_for_start_click = State()  # Waiting for user to click "شروع"
    waiting_phone = State()           # Waiting for contact sharing
    main_menu = State()               # User is registered and in main menu

# ---------------------------------------------------------
# 4. KEYBOARDS
# ---------------------------------------------------------


def kb_start_button():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="شروع")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def kb_phone_request():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 ارسال شماره تماس", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )


async def kb_dynamic_casts(db_service: DatabaseService):
    """
    Dynamically creates a ReplyKeyboard based on 'casts' collection in DB.
    """
    casts = await db_service.get_all_casts()

    # Create buttons list
    buttons = []
    for cast in casts:
        buttons.append(KeyboardButton(text=cast.get("name", "Cast")))

    # Arrange buttons in rows of 2
    keyboard = []
    row = []
    for btn in buttons:
        row.append(btn)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # Optional: Add a Support or Profile button at the bottom
    keyboard.append([KeyboardButton(text="🎧 پشتیبانی")])

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# ---------------------------------------------------------
# 5. HANDLERS
# ---------------------------------------------------------
router = Router()
router.message.filter(F.chat.type == "private")
db = DatabaseService()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id

    # Check if user already exists and is completed
    user = await db.get_user(user_id)
    if user.get("profile_completed"):
        keyboard = await kb_dynamic_casts(db)
        await message.answer(
            "به خانه برگشتید 🌿\n\nاز لیست زیر انتخاب کنید:",
            reply_markup=keyboard
        )
        await state.set_state(UserFlow.main_menu)
        return

    # New User Flow
    welcome_text = (
        "سلام و ارادت ✋🏼\n"
        "به اکت‌کست خوش آمدی 🌿🎧\n\n"
        "تبریک می‌گم که اولین قدمت رو در مسیر بهبود زندگی برداشتی.♥️\n"
        "اینجا کمکت می‌کنم با رویکرد اکت، انعطاف‌پذیری روانی‌ات رو بیشتر کنی و در مسیر ارزش‌هات پیش بری. ✨\n"
        "📌برای شروع روی کلمه «شروع» در پایین صفحه ضربه بزن."
    )

    await message.answer(welcome_text, reply_markup=kb_start_button())
    await state.set_state(UserFlow.waiting_for_start_click)


@router.message(UserFlow.waiting_for_start_click, F.text == "شروع")
async def process_start_click(message: Message, state: FSMContext):
    text = "برای ادامه و تکمیل حساب کاربری لطفا شماره همراه خودتون رو با دکمه در پایین صفحه به اشتراک بزارید"
    await message.answer(text, reply_markup=kb_phone_request())
    await state.set_state(UserFlow.waiting_phone)


@router.message(UserFlow.waiting_phone)
async def process_phone(message: Message, state: FSMContext):
    # Handle both contact object and manual text (though button forces contact)
    phone = message.contact.phone_number if message.contact else message.text

    if not phone:
        await message.answer("لطفا از دکمه پایین برای ارسال شماره استفاده کنید.")
        return

    user_id = message.from_user.id

    # Update DB
    await db.update_user(user_id, {
        "name": message.from_user.full_name,
        "username": message.from_user.username,
        "phone": phone,
        "profile_completed": True
    })

    # Generate Dynamic Keyboard
    keyboard = await kb_dynamic_casts(db)

    final_text = (
        "اینجا قراره قدم‌به‌قدم با رویکرد اکت یاد بگیری چطور وسطِ واقعیت‌های زندگی، انعطاف‌پذیرتر و آگاهانه‌تر حرکت کنی.\n"
    )
    await message.answer(final_text, reply_markup=keyboard)

    final_text = (
        "در اکت‌کست قرار هستش یک کار بزرگ باهم انجام دهیم.♥️✨"
    )
    await message.answer_video("BAACAgQAAxkBAAJqy2k6s2kc7v8ob6_OGFEzUw926MipAAIiIAACK0y4UX49xjpn-nNNNgQ", caption=final_text, reply_markup=keyboard)

    final_text = """قدم اول پیش از شروع اولین جلسه انجام تست انعطاف پذیری هستش. ✅ جهت انجام تست روی لینک زیر ضربه بزنید:
https://alimirsadeghi.com/test-congnitive-flexibility/
نتیجه تستتون رو اسکرین شات بگیرین یا یک جا ذخیره کنید تا پس از پایان دوره  میزان بهبود آن را متوجه شوید"""
    await message.answer(final_text, reply_markup=keyboard)

    await state.set_state(UserFlow.main_menu)


@router.message(F.text == "🎧 پشتیبانی")
async def support_handler(message: Message):
    await message.answer("برای ارتباط با پشتیبانی به آیدی زیر پیام دهید:\n@YourSupportID")


router = Router()


@router.message(Command("reset"))
async def cmd_reset(message: types.Message):
    user_id = message.from_user.id

    was_deleted = await db.delete_user(user_id)

    if was_deleted:
        await message.answer("Account Reset")
    else:
        await message.answer("You don't have a profile to reset yet. Type /start to join.")

# ---------------------------------------------------------
# GENERIC CAST HANDLER
# ---------------------------------------------------------


@router.message(UserFlow.main_menu)
async def cast_handler(message: Message, bot: Bot):
    """
    Checks if the user clicked a button matching a cast name in the DB.
    """
    cast_name = message.text

    # 1. Search in DB
    cast_data = await db.get_cast_by_name(cast_name)

    if not cast_data:
        # If it's not a cast, maybe generic fallback or ignore
        await message.answer("گزینه مورد نظر یافت نشد. لطفا از منو انتخاب کنید.")
        return

    # 2. Fetch Source Data
    src_chat_id = cast_data.get("source_chat_id")
    src_msg_id = cast_data.get("source_message_id")

    if not src_chat_id or not src_msg_id:
        logger.error(f"Invalid data for cast: {cast_name}")
        await message.answer("مشکلی در بارگذاری فایل وجود دارد.")
        return

    # 3. Copy Message
    try:
        await bot.copy_message(
            chat_id=message.from_user.id,
            from_chat_id=src_chat_id,
            message_id=src_msg_id
        )
    except Exception as e:
        logger.error(f"Error copying cast message: {e}")
        await message.answer("خطا در ارسال فایل. لطفا با پشتیبانی تماس بگیرید.")


# ---------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------
async def main():
    bot = Bot(
        token=CONF["BOT_TOKEN"],
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )

    storage = MongoStorage(client=db.client, db_name=CONF["DB_NAME"])
    dp = Dispatcher(storage=storage)
    dp.include_router(router)

    logger.info("🌿 ActCast Bot Started...")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
