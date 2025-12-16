from aiogram.filters import Command
from aiogram import Router, F, Bot
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import CommandStart
import datetime
# ایمپورت کردن موارد لازم از فایل‌های دیگر
from config import CONF, is_admin
from database import db
from aiogram.utils.keyboard import InlineKeyboardBuilder  # <--- New
import logging

logger = logging.getLogger("admin_bot")
router = Router()

# ---------------------------------------------------------
# STATES (وضعیت‌ها)
# ---------------------------------------------------------


# --- اضافه کردن به بخش STATES ---
class AdminFlow(StatesGroup):
    waiting_for_content = State()
    waiting_for_name = State()
    waiting_for_delete = State()
    # وضعیت‌های جدید برای سیستم پاسخ هوشمند
    waiting_for_trigger_keyword = State()  # منتظر کلمه کلیدی (مثلا 33)
    waiting_for_trigger_content = State()  # منتظر پیام‌های مربوط به آن

# --- اضافه کردن به بخش KEYBOARDS ---


def kb_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📤 آپلود محتوای جدید"),
             KeyboardButton(text="🗑 حذف محتوا")],
            [KeyboardButton(text="🧠 تنظیم پاسخ هوشمند")],
            [KeyboardButton(text="📢 ارسال همگانی")]
        ],
        resize_keyboard=True
    )
# ---------------------------------------------------------
# KEYBOARDS (دکمه‌ها)
# ---------------------------------------------------------


def kb_uploading():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ اتمام و ثبت")],  # دکمه جدید برای پایان
            [KeyboardButton(text="❌ انصراف")]
        ],
        resize_keyboard=True
    )


def kb_cancel():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ انصراف")]],
        resize_keyboard=True
    )


def kb_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📤 آپلود محتوای جدید")],
            [KeyboardButton(text="📢 ارسال همگانی")],
            [KeyboardButton(text="🧠 تنظیم پاسخ هوشمند")],
            [KeyboardButton(text="🗑 حذف محتوا")]
        ],
        resize_keyboard=True
    )

# ---------------------------------------------------------
# HANDLERS (منطق برنامه)
# ---------------------------------------------------------


@router.message(CommandStart())
async def cmd_start(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ شما اجازه دسترسی به این ربات را ندارید.")
        return

    await message.answer(
        "👋 سلام! به پنل ادمین **اکت‌کست** خوش آمدید.\n"
        "مدیریت فایل‌ها و دکمه‌ها:",
        reply_markup=kb_main_menu()
    )


# ... existing code ...


@router.message(Command("time"))
async def cmd_server_time(message: Message):
    now = datetime.datetime.now()
    # Format: YYYY-MM-DD HH:MM:SS
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")
    await message.answer(f"🕒 Server Time: `{time_str}`")


@router.message(F.text == "❌ انصراف")
async def cancel_action(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("عملیات لغو شد. به منوی اصلی برگشتید.", reply_markup=kb_main_menu())


def kb_delete_list(casts_list):
    """
    Creates an inline keyboard with a delete button for each item.
    """
    builder = InlineKeyboardBuilder()

    for cast in casts_list:
        # callback_data format: "del:<name>"
        # Note: Telegram callback_data has a 64-byte limit.
        # If names are very long, it's better to use IDs from the database.
        builder.button(text=f"❌ {cast['name']}",
                       callback_data=f"del:{cast['name']}")

    # Add a cancel/close button at the bottom
    builder.button(text="🔙 بستن منو", callback_data="close_menu")

    # Adjust layout: 1 button per row
    builder.adjust(1)
    return builder.as_markup()


# --- Delete Flow (Updated) ---

@router.message(F.text == "🗑 حذف محتوا")
async def start_delete(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    # Clear any previous states just in case
    await state.clear()

    casts = await db.get_all_cast_names()
    if not casts:
        await message.answer("📭 لیست خالی است. هیچ محتوایی برای حذف وجود ندارد.")
        return

    await message.answer(
        "👇 برای حذف هر محتوا، روی دکمه آن کلیک کنید:",
        reply_markup=kb_delete_list(casts)
    )


@router.callback_query(F.data.startswith("del:"))
async def process_delete_callback(callback):
    """
    Handles the click on a delete button.
    """
    # Extract name from callback_data (remove "del:" prefix)
    cast_name = callback.data.split(":", 1)[1]

    # Delete from database
    deleted = await db.delete_cast(cast_name)

    if deleted:
        # Show a small popup notification
        await callback.answer(f"✅ '{cast_name}' حذف شد.", show_alert=False)

        # Refresh the list in the message
        casts = await db.get_all_cast_names()
        if casts:
            await callback.message.edit_reply_markup(reply_markup=kb_delete_list(casts))
        else:
            await callback.message.edit_text("🗑 تمام محتواها حذف شدند.")
    else:
        await callback.answer("❌ خطا: این آیتم یافت نشد یا قبلاً حذف شده است.", show_alert=True)
        # Refresh the list anyway to remove the bad button
        casts = await db.get_all_cast_names()
        await callback.message.edit_reply_markup(reply_markup=kb_delete_list(casts))


@router.callback_query(F.data == "close_menu")
async def close_menu_callback(callback):
    """
    Handles the 'Close Menu' button.
    """
    await callback.message.delete()
    # Optional: Send main menu again or just simple notification
    await callback.answer("منوی حذف بسته شد.")


# ---------------------------------------------------------
# UPLOAD FLOW (چندگانه)
# ---------------------------------------------------------

@router.message(F.text == "📤 آپلود محتوای جدید")
async def start_upload(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    # پاکسازی داده‌های قبلی و ایجاد لیست خالی برای پیام‌ها
    await state.set_data({"media_list": []})

    await message.answer(
        "📂 **حالت آپلود چندگانه**\n\n"
        "محتواهای خود را یکی یکی (یا به صورت آلبوم) ارسال کنید.\n"
        "هر چیزی که بفرستید به لیست اضافه می‌شود.\n\n"
        "پس از اینکه تمام شد، دکمه **'✅ اتمام و ثبت'** را بزنید.",
        reply_markup=kb_uploading()
    )
    await state.set_state(AdminFlow.waiting_for_content)


# هندلر برای دکمه اتمام
@router.message(AdminFlow.waiting_for_content, F.text == "✅ اتمام و ثبت")
async def finish_upload_process(message: Message, state: FSMContext):
    data = await state.get_data()
    media_list = data.get("media_list", [])

    if not media_list:
        await message.answer("⚠️ هنوز هیچ محتوایی ارسال نکرده‌اید!", reply_markup=kb_uploading())
        return

    await message.answer(
        f"✅ تعداد **{len(media_list)}** محتوا دریافت شد.\n\n"
        "حالا لطفاً **نام دکمه** را وارد کنید:",
        reply_markup=kb_cancel()
    )
    await state.set_state(AdminFlow.waiting_for_name)


# هندلر دریافت فایل‌ها (عکس، ویدیو، متن و ...)
@router.message(AdminFlow.waiting_for_content)
async def process_content_step(message: Message, state: FSMContext):
    # اگر کاربر دکمه انصراف را زد (چون هندلر متن عمومی است باید چک شود)
    if message.text == "❌ انصراف":
        await state.clear()
        await message.answer("عملیات لغو شد.", reply_markup=kb_main_menu())
        return

    try:
        # کپی کردن فایل به کانال آرشیو
        sent_message = await message.copy_to(chat_id=CONF["STORAGE_CHANNEL_ID"])

        # دریافت لیست فعلی از حافظه
        data = await state.get_data()
        media_list = data.get("media_list", [])

        # اضافه کردن مشخصات پیام جدید به لیست
        # ما هم چت آیدی و هم مسیج آیدی را نگه می‌داریم
        media_list.append({
            'message_id': sent_message.message_id,
            'chat_id': CONF["STORAGE_CHANNEL_ID"]
        })

        # بروزرسانی حافظه
        await state.update_data(media_list=media_list)

        await message.answer(
            f"➕ فایل شماره {len(media_list)} اضافه شد.\n"
            "فایل بعدی را بفرستید یا روی 'اتمام' کلیک کنید.",
            reply_markup=kb_uploading()
        )

    except Exception as e:
        logger.error(f"Failed to copy to channel: {e}")
        await message.answer(f"❌ خطا در کپی کردن فایل به کانال.\nError: {e}")


@router.message(AdminFlow.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    button_name = message.text
    data = await state.get_data()
    media_list = data.get("media_list", [])

    # نکته مهم: دیتابیس شما باید قابلیت ذخیره لیست را داشته باشد
    # در اینجا ما لیست را به صورت JSON (متن) تبدیل می‌کنیم تا در یک فیلد ذخیره شود
    import json
    serialized_data = json.dumps(media_list)

    # ذخیره در دیتابیس
    # فرض بر این است که تابع add_new_cast شما الان یک رشته طولانی (JSON) را قبول می‌کند
    # یا باید ساختار دیتابیس را تغییر دهید تا لیست را ساپورت کند
    await db.add_new_cast(
        name=button_name,
        # اینجا به جای message_id تکی، کل داده سریالایز شده را می‌فرستیم
        # یا اگر دیتابیس فیلد جداگانه دارد، آن را هندل کنید
        message_id=serialized_data,
        # این شاید دیگر نیاز نباشد چون در لیست هست
        chat_id=CONF["STORAGE_CHANNEL_ID"]
    )

    await state.clear()
    await message.answer(
        f"🎉 مجموعه **'{button_name}'** با {len(media_list)} فایل ساخته شد.",
        reply_markup=kb_main_menu()
    )


# ---------------------------------------------------------
# FLOW: پاسخ هوشمند (Keyword Reply)
# ---------------------------------------------------------

@router.message(F.text == "🧠 تنظیم پاسخ هوشمند")
async def start_smart_reply(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "📝 لطفاً **کلمه کلیدی** یا عددی که کاربر باید بفرستد را وارد کنید.\n"
        "مثال: `33` یا `سلام` یا `قیمت`",
        reply_markup=kb_cancel()
    )
    await state.set_state(AdminFlow.waiting_for_trigger_keyword)


@router.message(AdminFlow.waiting_for_trigger_keyword)
async def process_keyword_input(message: Message, state: FSMContext):
    if message.text == "❌ انصراف":
        await state.clear()
        await message.answer("لغو شد.", reply_markup=kb_main_menu())
        return

    keyword = message.text.strip()

    # ذخیره کلمه کلیدی و ایجاد لیست خالی برای پیام‌ها
    await state.update_data(target_keyword=keyword, media_list=[])

    await message.answer(
        f"✅ کلمه **'{keyword}'** انتخاب شد.\n\n"
        "حالا پیام‌ها، عکس‌ها یا ویس‌هایی که می‌خواهید در جواب ارسال شود را یکی‌یکی بفرستید.\n"
        "در پایان دکمه **'✅ اتمام و ثبت'** را بزنید.",
        reply_markup=kb_uploading()  # استفاده از همان کیبورد آپلود قبلی
    )
    await state.set_state(AdminFlow.waiting_for_trigger_content)


@router.message(AdminFlow.waiting_for_trigger_content)
async def process_smart_content(message: Message, state: FSMContext):
    # اگر کاربر دکمه اتمام را زد
    if message.text == "✅ اتمام و ثبت":
        data = await state.get_data()
        keyword = data.get("target_keyword")
        media_list = data.get("media_list", [])

        if not media_list:
            await message.answer("⚠️ پیامی دریافت نشد.", reply_markup=kb_uploading())
            return

        # ذخیره در دیتابیس (تابع جدیدی که در بالا گفتیم)
        await db.add_keyword_reply(keyword=keyword, content_list=media_list)

        await state.clear()
        await message.answer(
            f"🎉 تنظیمات ذخیره شد.\n"
            f"هرکس بنویسد **{keyword}**، ربات {len(media_list)} پیام برایش ارسال می‌کند.",
            reply_markup=kb_main_menu()
        )
        return

    # اگر کاربر انصراف زد
    if message.text == "❌ انصراف":
        await state.clear()
        await message.answer("لغو شد.", reply_markup=kb_main_menu())
        return

    # دریافت پیام و کپی به کانال آرشیو (مشابه سیستم قبلی)
    try:
        sent_msg = await message.copy_to(chat_id=CONF["STORAGE_CHANNEL_ID"])

        data = await state.get_data()
        media_list = data.get("media_list", [])

        media_list.append({
            'message_id': sent_msg.message_id,
            'chat_id': CONF["STORAGE_CHANNEL_ID"]
        })

        await state.update_data(media_list=media_list)

        await message.answer(f"➕ پیام #{len(media_list)} دریافت شد.", reply_markup=kb_uploading())

    except Exception as e:
        logger.error(f"Error copying msg: {e}")
        await message.answer("خطا در ذخیره پیام.")
