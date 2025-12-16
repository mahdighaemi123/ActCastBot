from aiogram.filters import Command
from aiogram import Router, types
import asyncio
import logging
import os
from typing import Dict, Optional
import json
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
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram import F
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


def convert_to_english_digits(text):
    """Convert Persian digits in the input text to English digits."""
    if not isinstance(text, str):
        return text
    persian_digits = '۰۱۲۳۴۵۶۷۸۹'
    english_digits = '0123456789'
    trans_table = str.maketrans(persian_digits, english_digits)
    return text.translate(trans_table)


class DatabaseService:
    def __init__(self):
        self.client = AsyncIOMotorClient(CONF["MONGO_URL"])
        self.db = self.client[CONF["DB_NAME"]]
        self.users = self.db["users"]
        self.casts = self.db["casts"]
        self.keyword_replies = self.db["keyword_replies"]

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

    async def get_keyword_reply(self, keyword: str):
        """
        جستجو بر اساس کلمه کلیدی و بازگرداندن لیست پیام‌ها
        """
        # جستجوی دقیق (Exact Match).
        # نکته: در فایل main بهتر است ورودی کاربر را .strip() کنید
        doc = await self.keyword_replies.find_one({"keyword": keyword})

        if doc:
            return doc.get("content", [])
        return None

    # async def add_user_history(self, user_id: int, value: str, type: str):
    #     """
    #     این تابع فعالیت کاربر را به لیست سوابق او در دیتابیس اضافه می‌کند.
    #     value: مقداری که کاربر فرستاده (مثلا '33' یا 'جلسه اول')
    #     type: نوع فعالیت (مثلا 'keyword' یا 'cast_button')
    #     """
    #     new_record = {
    #         "value": value,
    #         "type": type,
    #         "date": datetime.now()  # زمان دقیق تعامل
    #     }

    #     await self.users.update_one(
    #         {"user_id": user_id},
    #         {
    #             # دستور push یک آیتم را به انتهای آرایه history اضافه می‌کند
    #             "$push": {
    #                 "history": new_record
    #             }
    #         },
    #         # اگر به هر دلیلی کاربر نبود، upsert باعث ساختش نمی‌شود (چون فقط آپدیت است)
    #         # اما چون کاربر از start رد شده، حتما وجود دارد.
    #         upsert=False
    #     )

    async def add_user_history(self, user_id: int, value: str, type: str):
        """
        اضافه کردن به تاریخچه فقط در صورتی که قبلاً این مقدار ثبت نشده باشد.
        """
        new_entry = {
            "value": value,
            "type": type,
            "created_at": datetime.now()
        }
        
        # شرط آپدیت:
        # 1. user_id پیدا شود
        # 2. در آرایه history، هیچ آیتمی نباشد که value آن برابر با مقدار جدید باشد ($ne)
        await self.users.update_one(
            {
                "user_id": user_id,
                "history.value": {"$ne": value} 
            },
            {"$push": {"history": new_entry}}
        )

    async def get_survey(self, survey_id: str):
        """دریافت اطلاعات کامل یک نظرسنجی"""
        return await self.db["surveys"].find_one({"survey_id": survey_id})

    async def save_vote(self, survey_id: str, user_id: int, option_id: str):
        """ثبت رای کاربر (اختیاری: برای جلوگیری از رای تکراری یا آمارگیری)"""
        # اگر می‌خواهید کاربر بتواند رای خود را تغییر دهد از update_one استفاده کنید
        await self.db["surveys"].update_one(
            {"survey_id": survey_id},
            {"$set": {f"votes.{user_id}": option_id}}
        )


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


async def kb_dynamic_casts(db_service):
    """
    Dynamically creates a ReplyKeyboard based on 'casts' collection in DB.
    """
    casts = await db_service.get_all_casts()

    buttons = []
    for cast in casts:
        buttons.append(KeyboardButton(text=cast.get("name", "Cast")))

    keyboard = []
    row = []
    for btn in buttons:
        row.append(btn)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    return ReplyKeyboardMarkup(keyboard=keyboard,
                               resize_keyboard=True,
                               one_time_keyboard=False,
                               selective=False)
# ---------------------------------------------------------
# 5. HANDLERS
# ---------------------------------------------------------
router = Router()
router.message.filter(F.chat.type == "private")
db = DatabaseService()


@router.message(CommandStart())
@router.message(Command("menu"))
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
    await message.answer(final_text, reply_markup=ReplyKeyboardRemove())

    try:

        final_text = (
            "در اکت‌کست قرار هستش یک کار بزرگ باهم انجام دهیم.♥️✨"
        )
        await message.answer_video("BAACAgQAAxkBAAJqy2k6s2kc7v8ob6_OGFEzUw926MipAAIiIAACK0y4UX49xjpn-nNNNgQ", caption=final_text, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"video send error: {e}")

    kb_test = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 تست", callback_data="send_test_msg")]
        ]
    )

    final_text = """قدم اول پیش از شروع اولین جلسه انجام تست انعطاف پذیری هستش. ✅ جهت دریافت تست روی دکمه زیر ضربه بزنید."""

    # Send message with the keyboard
    await message.answer(final_text, reply_markup=kb_test)
    await state.set_state(UserFlow.main_menu)


@router.callback_query(F.data == "send_test_msg")
async def process_test_callback(callback: CallbackQuery):
    """
    This function runs when the user clicks the 'تست' button.
    """
    user_id = callback.from_user.id
    keyboard = await kb_dynamic_casts(db)

    await callback.message.answer("""لینک تست :
https://alimirsadeghi.com/test-congnitive-flexibility/
نتیجه تستتون رو اسکرین شات بگیرین یا یک جا ذخیره کنید تا پس از پایان دوره میزان بهبود آن را متوجه شوید""", reply_markup=keyboard)

    await callback.answer()

    await db.add_user_history(
        user_id=user_id,
        value="تست",
        type="start_test"
    )


@router.message(Command("reset_my_account"))
async def cmd_reset(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await state.clear()

    await db.delete_user(user_id)

    await message.answer("Account Reset -> use /start ")


# ---------------------------------------------------------
# HANDLERS: تعامل کاربر با نظرسنجی (CALLBACK)
# ---------------------------------------------------------


@router.callback_query(F.data.startswith("surv:"))
async def handle_survey_click(callback: CallbackQuery):
    """
    وقتی کاربر روی دکمه نظرسنجی کلیک می‌کند.
    Format: surv:{survey_id}:{option_id}
    """
    parts = callback.data.split(":")
    if len(parts) != 3:
        return

    survey_id = parts[1]
    option_id = parts[2]
    user_id = callback.from_user.id

    # 1. دریافت اطلاعات نظرسنجی از دیتابیس
    survey = await db.get_survey(survey_id)
    if not survey:
        await callback.answer("❌ این نظرسنجی منقضی یا حذف شده است.", show_alert=True)
        # اگر دیتابیس پیدا نشد، پیام را حذف کن تا کاربر گیج نشود
        try:
            await callback.message.delete()
        except:
            pass
        return

    # 2. پیدا کردن گزینه انتخاب شده و پیام پاسخ آن
    selected_option = next(
        (opt for opt in survey['options'] if opt['id'] == option_id), None)

    if selected_option:
        response_text = selected_option.get("reply", "✅ نظر شما ثبت شد.")

        await db.save_vote(survey_id, user_id, option_id)

        try:
            await callback.message.delete()
        except Exception:
            pass

        await callback.message.answer(f"{response_text}")
        await callback.answer()

    else:
        await callback.answer("گزینه نامعتبر است.")

# ---------------------------------------------------------
# UNIFIED HANDLER (هندلر یکپارچه نهایی)
# ---------------------------------------------------------
# در فایل main.py


@router.message()
async def final_message_handler(message: Message, state: FSMContext, bot: Bot):
    # چک کردن‌های اولیه (دستورات و پیام خالی و ...)
    if message.text and message.text.startswith("/"):
        return
    user_input = message.text
    if not user_input:
        await cmd_start(message, state)
        return

    user_input_clean = convert_to_english_digits(user_input.strip())
    user_id = message.from_user.id

    # -----------------------------------------------------
    # ۱. بررسی دکمه‌ها (Casts)
    # -----------------------------------------------------
    cast_data = await db.get_cast_by_name(user_input_clean)

    if cast_data:
        # ✅ ثبت در تاریخچه کاربر (نوع: دکمه)
        await db.add_user_history(
            user_id=user_id,
            value=user_input_clean,
            type="cast_button"
        )

        # ... (کدهای دریافت پیام و ارسال آن - بدون تغییر) ...
        raw_msg_id = cast_data.get("source_message_id")
        raw_chat_id = cast_data.get("source_chat_id")

        # [بخش پردازش لیست و JSON را اینجا بگذارید...]
        content_list = []
        try:
            if isinstance(raw_msg_id, str) and raw_msg_id.startswith("["):
                content_list = json.loads(raw_msg_id)
            else:
                content_list = [
                    {"message_id": raw_msg_id, "chat_id": raw_chat_id}]
        except:
            content_list = [{"message_id": raw_msg_id, "chat_id": raw_chat_id}]

        if not content_list:
            await message.answer("محتوایی یافت نشد.")
            return

        keyboard = await kb_dynamic_casts(db)
        try:
            for index, item in enumerate(content_list):
                is_last = (index == len(content_list) - 1)
                await bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=item['chat_id'],
                    message_id=item['message_id'],
                    reply_markup=keyboard if is_last else None
                )
                
                if not is_last:
                    await asyncio.sleep(0.1)

            await state.set_state(UserFlow.main_menu)
            return
        except Exception as e:
            logger.error(f"Error sending cast: {e}")
            return

    # -----------------------------------------------------
    # ۲. بررسی کلمات کلیدی (Smart Reply)
    # -----------------------------------------------------
    reply_data = await db.get_keyword_reply(user_input_clean)

    if reply_data:
        # ✅ ثبت در تاریخچه کاربر (نوع: کلمه کلیدی)
        # مثلا اینجا ثبت می‌شود کاربر "33" را فرستاده
        await db.add_user_history(
            user_id=user_id,
            value=user_input_clean,
            type="keyword"
        )

        try:
            for item in reply_data:
                await bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=item['chat_id'],
                    message_id=item['message_id']
                )
                await asyncio.sleep(0.1)
            return

        except Exception as e:
            logger.error(f"Error keyword reply: {e}")
            return

    # -----------------------------------------------------
    # ۳. بازگشت به منو (Fallback)
    # -----------------------------------------------------
    current_state = await state.get_state()
    if current_state not in [UserFlow.waiting_phone, UserFlow.waiting_for_start_click]:
        await cmd_start(message, state)

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
