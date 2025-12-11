import asyncio
import logging
import os
from typing import Dict, Union

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ContentType
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

# ---------------------------------------------------------
# 1. CONFIGURATION
# ---------------------------------------------------------
load_dotenv()

# Setup Logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("admin_bot")

# CONFIGURATION VARS
CONF = {
    "ADMIN_BOT_TOKEN": os.getenv("ADMIN_BOT_TOKEN"),
    "MONGO_URL": os.getenv("MONGODB_URL", "mongodb://localhost:27017"),
    "DB_NAME": os.getenv("DB_NAME", "act_cast_db"),

    # Comma separated list of admin Telegram IDs
    "ADMIN_IDS": [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x],

    # The Channel ID where files will be stored
    "STORAGE_CHANNEL_ID": int(os.getenv("STORAGE_CHANNEL_ID", "0"))
}

if not CONF["ADMIN_BOT_TOKEN"] or not CONF["STORAGE_CHANNEL_ID"]:
    raise ValueError(
        "ADMIN_BOT_TOKEN or STORAGE_CHANNEL_ID is missing in .env")

# ---------------------------------------------------------
# 2. DATABASE SERVICE
# ---------------------------------------------------------


class DatabaseService:
    def __init__(self):
        self.client = AsyncIOMotorClient(CONF["MONGO_URL"])
        self.db = self.client[CONF["DB_NAME"]]
        self.casts = self.db["casts"]

    async def add_new_cast(self, name: str, chat_id: int, message_id: int):
        """Saves the reference to the file stored in the channel."""
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

# ---------------------------------------------------------
# 3. FSM STATES
# ---------------------------------------------------------


class AdminFlow(StatesGroup):
    waiting_for_content = State()  # Admin sends the file
    waiting_for_name = State()    # Admin names the button
    waiting_for_delete = State()  # For deleting casts

# ---------------------------------------------------------
# 4. UTILS
# ---------------------------------------------------------


def is_admin(user_id: int) -> bool:
    return user_id in CONF["ADMIN_IDS"]


def kb_cancel():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ انصراف")]],
        resize_keyboard=True
    )


def kb_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📤 آپلود محتوای جدید")],
            [KeyboardButton(text="🗑 حذف محتوا")]
        ],
        resize_keyboard=True
    )


# ---------------------------------------------------------
# 5. HANDLERS
# ---------------------------------------------------------
router = Router()
db = DatabaseService()


@router.message(CommandStart())
async def cmd_start(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ شما اجازه دسترسی به این ربات را ندارید.")
        return

    await message.answer(
        "👋 سلام! به پنل ادمین **اکت‌کست** خوش آمدید.\n"
        "در اینجا می‌توانید فایل‌ها را به کانال آرشیو بفرستید و دکمه‌های ربات اصلی را مدیریت کنید.",
        reply_markup=kb_main_menu()
    )


@router.message(F.text == "❌ انصراف")
async def cancel_action(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("عملیات لغو شد. به منوی اصلی برگشتید.", reply_markup=kb_main_menu())

# --- Upload Flow ---


@router.message(F.text == "📤 آپلود محتوای جدید")
async def start_upload(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "لطفاً محتوای مورد نظر (ویدیو، صدا، عکس، ویس یا متن) را همینجا ارسال کنید.",
        reply_markup=kb_cancel()
    )
    await state.set_state(AdminFlow.waiting_for_content)


@router.message(AdminFlow.waiting_for_content)
async def process_content(message: Message, state: FSMContext, bot: Bot):
    # 1. Copy the message to the Storage Channel
    try:
        sent_message = await message.copy_to(chat_id=CONF["STORAGE_CHANNEL_ID"])

        # 2. Store the ID of the message in the CHANNEL
        await state.update_data(
            source_message_id=sent_message.message_id,
            source_chat_id=sent_message.chat.id
        )

        await message.answer(
            f"✅ محتوا با موفقیت در کانال ذخیره شد (ID: {sent_message.message_id}).\n\n"
            "حالا لطفاً **نام دکمه** را وارد کنید (این نام در ربات اصلی نمایش داده می‌شود):",
            reply_markup=kb_cancel()
        )
        await state.set_state(AdminFlow.waiting_for_name)

    except Exception as e:
        logger.error(f"Failed to copy to channel: {e}")
        await message.answer(
            f"❌ خطا در کپی کردن فایل به کانال.\n"
            f"لطفاً مطمئن شوید که ربات در کانال (ID: {CONF['STORAGE_CHANNEL_ID']}) ادمین است.\n"
            f"Error: {e}"
        )


@router.message(AdminFlow.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    button_name = message.text
    data = await state.get_data()

    # Save to DB
    await db.add_new_cast(
        name=button_name,
        chat_id=data['source_chat_id'],
        message_id=data['source_message_id']
    )

    await state.clear()
    await message.answer(
        f"🎉 عالی! دکمه **'{button_name}'** ساخته شد.\n"
        "کاربران ربات اصلی اکنون می‌توانند این محتوا را ببینند.",
        reply_markup=kb_main_menu()
    )

# --- Delete Flow ---


@router.message(F.text == "🗑 حذف محتوا")
async def start_delete(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    casts = await db.get_all_cast_names()
    if not casts:
        await message.answer("هنوز هیچ محتوایی در دیتابیس ثبت نشده است.")
        return

    # List all names
    text = "نام دقیق محتوایی که می‌خواهید حذف کنید را ارسال کنید:\n\n"
    for c in casts:
        text += f"• `{c['name']}`\n"

    await message.answer(text, reply_markup=kb_cancel())
    await state.set_state(AdminFlow.waiting_for_delete)


@router.message(AdminFlow.waiting_for_delete)
async def process_delete(message: Message, state: FSMContext):
    name = message.text
    deleted = await db.delete_cast(name)

    if deleted:
        await message.answer(f"✅ محتوای '{name}' از دیتابیس حذف شد.", reply_markup=kb_main_menu())
    else:
        await message.answer(f"❌ محتوایی با نام '{name}' پیدا نشد. دوباره تلاش کنید یا انصراف دهید.", reply_markup=kb_cancel())
        return  # Don't clear state so they can try again

    await state.clear()

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------


async def main():
    bot = Bot(
        token=CONF["ADMIN_BOT_TOKEN"],
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )

    dp = Dispatcher()
    dp.include_router(router)

    logger.info("🚀 Admin Bot Started (Persian)...")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
