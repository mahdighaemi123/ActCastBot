from aiogram import Router, F, Bot
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import CommandStart

# ایمپورت کردن موارد لازم از فایل‌های دیگر
from config import CONF, is_admin
from database import db

import logging

logger = logging.getLogger("admin_bot")
router = Router()

# ---------------------------------------------------------
# STATES (وضعیت‌ها)
# ---------------------------------------------------------


class AdminFlow(StatesGroup):
    waiting_for_content = State()
    waiting_for_name = State()
    waiting_for_delete = State()

# ---------------------------------------------------------
# KEYBOARDS (دکمه‌ها)
# ---------------------------------------------------------


def kb_cancel():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ انصراف")]],
        resize_keyboard=True
    )


def kb_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📤 آپلود محتوای جدید")],
            [KeyboardButton(text="📢 ارسال همگانی")],  # <--- اضافه شده
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
async def process_content(message: Message, state: FSMContext):
    try:
        # کپی کردن فایل به کانال آرشیو
        sent_message = await message.copy_to(chat_id=CONF["STORAGE_CHANNEL_ID"])

        await state.update_data(
            source_message_id=sent_message.message_id,
            source_chat_id=CONF["STORAGE_CHANNEL_ID"]
        )

        await message.answer(
            f"✅ محتوا با موفقیت در کانال ذخیره شد (ID: {sent_message.message_id}).\n\n"
            "حالا لطفاً **نام دکمه** را وارد کنید:",
            reply_markup=kb_cancel()
        )
        await state.set_state(AdminFlow.waiting_for_name)

    except Exception as e:
        logger.error(f"Failed to copy to channel: {e}")
        await message.answer(f"❌ خطا در کپی کردن فایل به کانال.\nError: {e}")


@router.message(AdminFlow.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    button_name = message.text
    data = await state.get_data()

    # ذخیره در دیتابیس
    await db.add_new_cast(
        name=button_name,
        chat_id=data['source_chat_id'],
        message_id=data['source_message_id']
    )

    await state.clear()
    await message.answer(
        f"🎉 دکمه **'{button_name}'** ساخته شد.",
        reply_markup=kb_main_menu()
    )

# --- Delete Flow ---


@router.message(F.text == "🗑 حذف محتوا")
async def start_delete(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    casts = await db.get_all_cast_names()
    if not casts:
        await message.answer("هنوز هیچ محتوایی ثبت نشده است.")
        return

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
        await message.answer(f"✅ محتوای '{name}' حذف شد.", reply_markup=kb_main_menu())
    else:
        await message.answer(f"❌ نام '{name}' پیدا نشد.", reply_markup=kb_cancel())
        return

    await state.clear()
