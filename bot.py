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

    keyboard = await kb_dynamic_casts(db)

    await callback.message.answer("""لینک تست :
https://alimirsadeghi.com/test-congnitive-flexibility/
نتیجه تستتون رو اسکرین شات بگیرین یا یک جا ذخیره کنید تا پس از پایان دوره میزان بهبود آن را متوجه شوید""", reply_markup=keyboard)

    await callback.answer()


@router.message(Command("reset_my_account"))
async def cmd_reset(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await state.clear()

    await db.delete_user(user_id)

    await message.answer("Account Reset -> use /start ")


# ---------------------------------------------------------
# UNIFIED HANDLER (هندلر یکپارچه نهایی)
# ---------------------------------------------------------

@router.message()
async def final_message_handler(message: Message, state: FSMContext, bot: Bot):
    """
    این تابع تمام پیام‌های متنی که در مراحل قبلی (مثل ثبت‌نام) هندل نشده‌اند را دریافت می‌کند.
    اولویت بررسی:
    ۱. آیا دکمه (Cast) است؟
    ۲. آیا کلمه کلیدی (Keyword) است؟
    ۳. اگر هیچکدام نبود -> نمایش منوی اصلی (Reset/Default).
    """

    # 1. نادیده گرفتن دستورات سیستمی (اگر هندل نشده باشند)
    if message.text and message.text.startswith("/"):
        return

    user_input = message.text
    if not user_input:
        # اگر کاربر استیکر یا گیف فرستاد، منو را نشان بده
        await cmd_start(message, state)
        return

    user_input_clean = user_input.strip()

    # -----------------------------------------------------
    # گام اول: بررسی دکمه‌ها (Casts)
    # -----------------------------------------------------
    cast_data = await db.get_cast_by_name(user_input_clean)

    if cast_data:
        # دریافت داده‌های خام از دیتابیس
        raw_msg_id = cast_data.get("source_message_id")
        raw_chat_id = cast_data.get("source_chat_id")

        content_list = []

        # تشخیص فرمت (تکی یا چندتایی JSON)
        try:
            if isinstance(raw_msg_id, str) and raw_msg_id.startswith("["):
                content_list = json.loads(raw_msg_id)
            else:
                content_list = [
                    {"message_id": raw_msg_id, "chat_id": raw_chat_id}]
        except Exception as e:
            logger.error(f"Error parsing cast data: {e}")
            content_list = [{"message_id": raw_msg_id, "chat_id": raw_chat_id}]

        if not content_list:
            await message.answer("محتوایی یافت نشد.")
            return

        # دریافت کیبورد
        keyboard = await kb_dynamic_casts(db)

        # ارسال پیام‌ها
        try:
            total_items = len(content_list)
            for index, item in enumerate(content_list):
                is_last_message = (index == total_items - 1)
                reply_markup = keyboard if is_last_message else None

                msg_id = item.get('message_id')
                chat_id = item.get('chat_id')

                if msg_id and chat_id:
                    await bot.copy_message(
                        chat_id=message.from_user.id,
                        from_chat_id=chat_id,
                        message_id=msg_id,
                        reply_markup=reply_markup
                    )
                    if not is_last_message:
                        await asyncio.sleep(0.1)

            # ثبت وضعیت کاربر در منوی اصلی
            await state.set_state(UserFlow.main_menu)
            return  # پایان عملیات موفق

        except Exception as e:
            logger.error(f"Error sending cast: {e}")
            await message.answer("خطا در ارسال محتوا.", reply_markup=keyboard)
            return

    # -----------------------------------------------------
    # گام دوم: بررسی کلمات کلیدی (Smart Reply)
    # -----------------------------------------------------
    reply_data = await db.get_keyword_reply(user_input_clean)

    if reply_data:
        try:
            for item in reply_data:
                msg_id = item.get('message_id')
                chat_id = item.get('chat_id')

                if msg_id and chat_id:
                    await bot.copy_message(
                        chat_id=message.from_user.id,
                        from_chat_id=chat_id,
                        message_id=msg_id
                    )
                    await asyncio.sleep(0.1)  # تاخیر جزئی برای حفظ ترتیب
            return  # پایان عملیات موفق

        except Exception as e:
            logger.error(f"Error sending keyword reply: {e}")
            # در صورت خطا در ارسال پاسخ هوشمند، به سراغ منوی اصلی نمی‌رویم
            return

    # -----------------------------------------------------
    # گام سوم: هیچکدام نبود (Default Fallback)
    # -----------------------------------------------------
    # اگر پیام نه Cast بود و نه Keyword، یعنی کاربر چیزی خارج از برنامه گفته
    # پس منوی اصلی را دوباره به او نشان می‌دهیم.

    # اختیاری: اگر در حالت ثبت نام نیست، منو را نشان بده
    current_state = await state.get_state()
    # اگر کاربر وسط پروسه خاصی نیست، منو را بفرست
    if current_state not in [UserFlow.waiting_phone, UserFlow.waiting_for_start_click]:
        await cmd_start(message, state)


# ---------------------------------------------------------
# USER HANDLER (سمت کاربر)
# ---------------------------------------------------------


# @router.message()
# async def user_message_handler(message: Message):
#     """
#     این تابع هر پیامی که هندل نشده باشد را بررسی می‌کند.
#     """
#     # 1. نادیده گرفتن دستورات (اگر با / شروع شود و هندل نشده باشد)
#     if message.text and message.text.startswith("/"):
#         return

#     # 2. دریافت متن پیام کاربر
#     user_input = message.text
#     if not user_input:
#         return  # اگر عکس یا استیکر بود و کپشن نداشت

#     # 3. جستجو در دیتابیس
#     # این تابع باید لیست پیام‌ها را برگرداند یا None
#     reply_data = await db.get_keyword_reply(user_input.strip())

#     if reply_data:
#         # اگر کلمه کلیدی پیدا شد (مثلاً کاربر نوشت 33 و در دیتابیس بود)
#         try:
#             # حلقه روی تمام پیام‌های ذخیره شده
#             for item in reply_data:
#                 msg_id = item['message_id']
#                 chat_id = item['chat_id']

#                 # کپی کردن پیام از کانال آرشیو به کاربر
#                 await message.bot.copy_message(
#                     chat_id=message.from_user.id,
#                     from_chat_id=chat_id,
#                     message_id=msg_id
#                 )
#                 # یک تاخیر خیلی کوتاه برای جلوگیری از بهم ریختن ترتیب (اختیاری)
#                 # await asyncio.sleep(0.1)

#         except Exception as e:
#             logger.error(f"Error sending keyword reply: {e}")
#             # به کاربر چیزی نگوییم بهتر است، یا یک پیام خطای کلی بدهیم
#     else:
#         # اگر کلمه کلیدی نبود، هیچ کاری نکن یا به هوش مصنوعی وصل کن
#         pass


# @router.message(UserFlow.main_menu)
# async def cast_handler(message: Message, bot: Bot):
#     """
#     Checks if the user clicked a button matching a cast name in the DB.
#     Handles both single messages and multi-message (albums/lists).
#     """
#     cast_name = message.text

#     # 1. Search in DB
#     cast_data = await db.get_cast_by_name(cast_name)

#     if not cast_data:
#         keyboard = await kb_dynamic_casts(db)
#         await message.answer(
#             "متوجه نشدم! 🤔\nلطفاً یکی از گزینه‌های منو را انتخاب کنید:",
#             reply_markup=keyboard
#         )
#         return

#     # دریافت داده‌های خام از دیتابیس
#     raw_msg_id = cast_data.get("source_message_id")
#     # برای پشتیبانی از دیتای قدیمی
#     raw_chat_id = cast_data.get("source_chat_id")

#     content_list = []

#     # 2. تشخیص فرمت (تکی یا چندتایی)
#     try:
#         # اگر فرمت جدید (متن JSON) باشد:
#         if isinstance(raw_msg_id, str) and raw_msg_id.startswith("["):
#             content_list = json.loads(raw_msg_id)
#         else:
#             # اگر فرمت قدیمی (عدد تکی) باشد:
#             content_list = [{"message_id": raw_msg_id, "chat_id": raw_chat_id}]
#     except Exception as e:
#         logger.error(f"Error parsing content data: {e}")
#         # تلاش برای بازگشت به حالت تکی در صورت خرابی JSON
#         content_list = [{"message_id": raw_msg_id, "chat_id": raw_chat_id}]

#     if not content_list:
#         await message.answer("محتوایی برای نمایش وجود ندارد.")
#         return

#     # دریافت کیبورد اصلی برای نمایش در پایان
#     keyboard = await kb_dynamic_casts(db)

#     # 3. ارسال پیام‌ها به ترتیب
#     try:
#         total_items = len(content_list)

#         for index, item in enumerate(content_list):
#             # بررسی اینکه آیا این آخرین پیام است؟
#             is_last_message = (index == total_items - 1)

#             # کیبورد را فقط به آخرین پیام می‌چسبانیم تا کاربر سردرگم نشود
#             reply_markup = keyboard if is_last_message else None

#             msg_id = item.get('message_id')
#             chat_id = item.get('chat_id')

#             if msg_id and chat_id:
#                 await bot.copy_message(
#                     chat_id=message.from_user.id,
#                     from_chat_id=chat_id,
#                     message_id=msg_id,
#                     reply_markup=reply_markup
#                 )

#                 # یک مکث کوتاه برای جلوگیری از به هم ریختن ترتیب ارسال در تلگرام
#                 if not is_last_message:
#                     await asyncio.sleep(0.1)

#     except Exception as e:
#         logger.error(f"Error copying cast message: {e}")
#         # در صورت بروز خطا، کیبورد را مجدد ارسال می‌کنیم تا کاربر گیر نکند
#         await message.answer("خطا در بارگذاری برخی فایل‌ها.", reply_markup=keyboard)


# @router.message()
# async def default_handler(message: Message, state: FSMContext):
#     """
#     این تابع هر پیامی که توسط هندلرهای بالا گرفته نشده باشد را دریافت می‌کند.
#     در اینجا ما منطق شروع (cmd_start) را صدا می‌زنیم تا اگر کاربر ثبت‌نام کرده، منو را ببیند
#     و اگر ثبت‌نام نکرده، پروسه ثبت‌نام را طی کند.
#     """
#     await cmd_start(message, state)


# ---------------------------------------------------------
# USER HANDLER (سمت کاربر)
# ---------------------------------------------------------

# @router.message()
# async def user_message_handler(message: Message):
#     """
#     این تابع هر پیامی که هندل نشده باشد را بررسی می‌کند.
#     """
#     # 1. نادیده گرفتن دستورات (اگر با / شروع شود و هندل نشده باشد)
#     if message.text and message.text.startswith("/"):
#         return

#     # 2. دریافت متن پیام کاربر
#     user_input = message.text
#     if not user_input:
#         return  # اگر عکس یا استیکر بود و کپشن نداشت

#     # 3. جستجو در دیتابیس
#     # این تابع باید لیست پیام‌ها را برگرداند یا None
#     reply_data = await db.get_keyword_reply(user_input.strip())

#     if reply_data:
#         # اگر کلمه کلیدی پیدا شد (مثلاً کاربر نوشت 33 و در دیتابیس بود)
#         try:
#             # حلقه روی تمام پیام‌های ذخیره شده
#             for item in reply_data:
#                 msg_id = item['message_id']
#                 chat_id = item['chat_id']

#                 # کپی کردن پیام از کانال آرشیو به کاربر
#                 await message.bot.copy_message(
#                     chat_id=message.from_user.id,
#                     from_chat_id=chat_id,
#                     message_id=msg_id
#                 )
#                 # یک تاخیر خیلی کوتاه برای جلوگیری از بهم ریختن ترتیب (اختیاری)
#                 # await asyncio.sleep(0.1)

#         except Exception as e:
#             logger.error(f"Error sending keyword reply: {e}")
#             # به کاربر چیزی نگوییم بهتر است، یا یک پیام خطای کلی بدهیم
#     else:
#         # اگر کلمه کلیدی نبود، هیچ کاری نکن یا به هوش مصنوعی وصل کن
#         pass

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
