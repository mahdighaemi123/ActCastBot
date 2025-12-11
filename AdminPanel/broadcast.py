# broadcast.py
import asyncio
import datetime
import time
from aiogram import Router, F, Bot
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging
from config import is_admin
from database import db
# ایمپورت ابزارهای تاریخ که ساختیم
from date_picker import DateCallback, get_years_kb, get_months_kb, get_days_kb, get_hours_kb
from main_bot import main_bot

router = Router()

# --- States ---
logger = logging.getLogger("admin_bot")


class BroadcastFlow(StatesGroup):
    choosing_daterange = State()    # در حال کار با دکمه‌های شیشه‌ای
    collecting_messages = State()   # دریافت پیام‌ها

# --- Main Keyboard ---


def kb_filter_start():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 فیلتر پیشرفته (تاریخ دقیق)")],
            [KeyboardButton(text="⚡️ همه کاربران")],
            [KeyboardButton(text="❌ انصراف")]
        ],
        resize_keyboard=True
    )


def kb_broadcast_actions():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✅ ارسال نهایی"),
                   KeyboardButton(text="❌ انصراف")]],
        resize_keyboard=True
    )

# --- Start Handler ---


@router.message(F.text == "📢 ارسال همگانی")
async def start_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await message.answer("مخاطبین را انتخاب کنید:", reply_markup=kb_filter_start())

# --- Basic Filters ---


@router.message(F.text == "⚡️ همه کاربران")
async def filter_all(message: Message, state: FSMContext):
    # بازه زمانی از 0 تا الان (یعنی همه)
    await state.update_data(start_ts=0, end_ts=time.time())
    await message.answer("✅ همه کاربران انتخاب شدند.\nپیام‌های خود را ارسال کنید:", reply_markup=kb_broadcast_actions())
    await state.set_state(BroadcastFlow.collecting_messages)

# --- Advanced Filter Flow (Start) ---


@router.message(F.text == "📅 فیلتر پیشرفته (تاریخ دقیق)")
async def filter_custom_start(message: Message, state: FSMContext):
    await message.answer("📅 لطفاً **سال شروع** (Start Date) را انتخاب کنید:", reply_markup=get_years_kb("start"))
    # دیتای موقت برای نگه داشتن انتخاب‌ها
    await state.update_data(temp_sel={})
    await state.set_state(BroadcastFlow.choosing_daterange)

# --- Handling Callbacks (The UX Magic) ---


@router.callback_query(DateCallback.filter())
async def process_date_selection(callback: CallbackQuery, callback_data: DateCallback, state: FSMContext):
    action = callback_data.action
    value = callback_data.value
    stage = callback_data.stage  # 'start' or 'end'

    # گرفتن دیتای فعلی
    data = await state.get_data()
    temp = data.get("temp_sel", {})

    # 1. انتخاب سال
    if action == "year":
        temp[f"{stage}_year"] = value
        await state.update_data(temp_sel=temp)
        await callback.message.edit_text(
            f"سال {value} انتخاب شد.\nحالا **ماه** را انتخاب کنید:",
            reply_markup=get_months_kb(value, stage)
        )

    # 2. انتخاب ماه
    elif action == "month":
        temp[f"{stage}_month"] = value
        year = temp[f"{stage}_year"]
        await state.update_data(temp_sel=temp)
        await callback.message.edit_text(
            f"ماه {value} انتخاب شد.\nحالا **روز** را انتخاب کنید:",
            reply_markup=get_days_kb(year, value, stage)
        )

    # 3. انتخاب روز
    elif action == "day":
        temp[f"{stage}_day"] = value
        await state.update_data(temp_sel=temp)
        await callback.message.edit_text(
            f"روز {value} انتخاب شد.\nحالا **ساعت** را انتخاب کنید:",
            reply_markup=get_hours_kb(stage)
        )

    # 4. انتخاب ساعت (پایان یک مرحله)
    elif action == "hour":
        temp[f"{stage}_hour"] = value

        # تبدیل تاریخ انتخابی به Timestamp
        dt_obj = datetime.datetime(
            year=temp[f"{stage}_year"],
            month=temp[f"{stage}_month"],
            day=temp[f"{stage}_day"],
            hour=value
        )
        ts = dt_obj.timestamp()

        # ذخیره نهایی
        if stage == "start":
            await state.update_data(start_ts=ts)
            # حالا برویم سراغ تاریخ پایان
            await callback.message.edit_text(
                "✅ تاریخ شروع ثبت شد.\n\n🏁 حالا **سال پایان** (End Date) را انتخاب کنید:",
                reply_markup=get_years_kb("end")
            )
        else:  # stage == "end"
            await state.update_data(end_ts=ts)

            # محاسبه تعداد کاربران
            start_ts = data.get("start_ts")
            end_ts = ts

            users = await db.get_users_in_range(start_ts, end_ts)
            count = len(users)

            await callback.message.delete()  # حذف دکمه‌های شیشه‌ای
            await callback.message.answer(
                f"✅ فیلتر زمانی کامل شد.\n"
                f"📅 از: {datetime.datetime.fromtimestamp(start_ts)}\n"
                f"📅 تا: {datetime.datetime.fromtimestamp(end_ts)}\n\n"
                f"👥 تعداد کاربران پیدا شده: **{count}** نفر\n\n"
                "👇 حالا پیام‌های خود را ارسال کنید:",
                reply_markup=kb_broadcast_actions()
            )
            await state.set_state(BroadcastFlow.collecting_messages)
            # لیست پیام‌ها رو خالی کن برای شروع جدید
            await state.update_data(messages=[])

    await callback.answer()

# --- Message Collection & Sending (مانند قبل با تغییرات جزئی) ---


@router.message(BroadcastFlow.collecting_messages)
async def collect_broadcast_msgs(message: Message, state: FSMContext, bot: Bot):
    if message.text == "❌ انصراف":
        await state.clear()
        # برگرد به منوی اول برادکست
        await message.answer("لغو شد.", reply_markup=kb_filter_start())
        return

    if message.text == "✅ ارسال نهایی":
        data = await state.get_data()
        msgs = data.get("messages", [])
        start_ts = data.get("start_ts")
        end_ts = data.get("end_ts")

        if not msgs:
            await message.answer("هیچ پیامی ارسال نکردید!")
            return

        users = await db.get_users_in_range(start_ts, end_ts)
        if not users:
            await message.answer("کاربری پیدا نشد.")
            return

        await message.answer(f"🚀 در حال ارسال برای {len(users)} نفر...")

        # --- LOOP SENDING ---
        success = 0
        blocked = 0
        for u in users:
            try:
                for m in msgs:
                    await main_bot.copy_message(u['user_id'], m['chat_id'], m['message_id'])
                    await asyncio.sleep(0.05)
                success += 1
            except Exception as e:
                logger.error(f"single send error: {e}")
                blocked += 1

            await asyncio.sleep(0.1)

        await message.answer(f"تمام شد.\nموفق: {success}\nناموفق: {blocked}")
        await state.clear()
        return

    # ذخیره پیام
    current = (await state.get_data()).get("messages", [])
    current.append({"chat_id": message.chat.id,
                   "message_id": message.message_id})
    await state.update_data(messages=current)
    await message.answer("📥 دریافت شد.")
