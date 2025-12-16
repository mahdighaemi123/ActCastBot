# broadcast.py
import asyncio
import datetime
import time
import uuid  # Imported for random ID
from aiogram import Router, F, Bot
# Added Inline imports
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    CallbackQuery, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging
from config import is_admin
from database import db
from date_picker import DateCallback, get_years_kb, get_months_kb, get_days_kb, get_hours_kb
from main_bot import main_bot, kb_dynamic_casts
from config import CONF
from upload_content import kb_main_menu

router = Router()
logger = logging.getLogger("broadcast")

# --- States ---
# --- States ---


class BroadcastFlow(StatesGroup):
    choosing_daterange = State()
    collecting_messages = State()
    waiting_for_ids = State()
    waiting_for_batch_id = State()  # 🆕 Added this state

# --- Main Keyboard ---


def kb_filter_start():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⚡️ همه کاربران")],
            [KeyboardButton(text="📅 فیلتر پیشرفته (تاریخ دقیق)")],
            [KeyboardButton(text="🗑 حذف پیام ارسال شده با شناسه")],
            [KeyboardButton(text="👤 انتخاب دستی"),
             KeyboardButton(text="🧪 ارسال تستی")],
            [KeyboardButton(text="❌ انصراف")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=False
    )


def kb_broadcast_actions():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✅ ارسال نهایی"),
                   KeyboardButton(text="❌ انصراف")]],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=False
    )


async def execute_batch_deletion(batch_id: str, status_message: Message):
    """
    Shared function to delete messages for a given batch_id.
    Updates the status_message with progress.
    """
    # 1. Get logs from DB
    logs = await db.get_broadcast_logs(batch_id)

    if not logs:
        await status_message.edit_text(f"❌ پیامی برای شناسه `{batch_id}` در دیتابیس یافت نشد.")
        return

    total = len(logs)
    await status_message.edit_text(f"🗑 پیدا شد: {total} پیام.\n⏳ شروع عملیات حذف برای Batch ID: `{batch_id}`...")

    deleted_count = 0
    errors = 0

    for i, log in enumerate(logs):
        try:
            await main_bot.delete_message(chat_id=log['user_id'], message_id=log['message_id'])
            deleted_count += 1
        except Exception as e:
            errors += 1

        if i % 100 == 0:
            await status_message.edit_text(
                f"⏳ در حال حذف... ({i+1}/{total})\n"
                f"🗑 حذف شده: {deleted_count}\n"
                f"⚠️ خطا: {errors}"
            )

        await asyncio.sleep(0.035)

    await status_message.edit_text(
        f"✅ **عملیات حذف پایان یافت.**\n\n"
        f"🆔 Batch ID: `{batch_id}`\n"
        f"🔢 کل پیام‌ها: {total}\n"
        f"🗑 موفق: {deleted_count}\n"
        f"⚠️ ناموفق/پاک شده: {errors}"
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
    await state.update_data(start_ts=0, end_ts=time.time())
    await message.answer("✅ همه کاربران انتخاب شدند.\nپیام‌های خود را ارسال کنید:", reply_markup=kb_broadcast_actions(), resize_keyboard=True,
                         one_time_keyboard=False,
                         selective=False)
    await state.set_state(BroadcastFlow.collecting_messages)

# --- Advanced Filter Flow (Start) ---


@router.message(F.text == "📅 فیلتر پیشرفته (تاریخ دقیق)")
async def filter_custom_start(message: Message, state: FSMContext):
    await message.answer("📅 لطفاً **سال شروع** (Start Date) را انتخاب کنید:", reply_markup=get_years_kb("start"))
    await state.update_data(temp_sel={})
    await state.set_state(BroadcastFlow.choosing_daterange)

# --- Handling Callbacks ---


@router.callback_query(DateCallback.filter())
async def process_date_selection(callback: CallbackQuery, callback_data: DateCallback, state: FSMContext):
    action = callback_data.action
    value = callback_data.value
    stage = callback_data.stage

    data = await state.get_data()
    temp = data.get("temp_sel", {})

    if action == "year":
        temp[f"{stage}_year"] = value
        await state.update_data(temp_sel=temp)
        await callback.message.edit_text(
            f"سال {value} انتخاب شد.\nحالا **ماه** را انتخاب کنید:",
            reply_markup=get_months_kb(value, stage)
        )

    elif action == "month":
        temp[f"{stage}_month"] = value
        year = temp[f"{stage}_year"]
        await state.update_data(temp_sel=temp)
        await callback.message.edit_text(
            f"ماه {value} انتخاب شد.\nحالا **روز** را انتخاب کنید:",
            reply_markup=get_days_kb(year, value, stage)
        )

    elif action == "day":
        temp[f"{stage}_day"] = value
        await state.update_data(temp_sel=temp)
        await callback.message.edit_text(
            f"روز {value} انتخاب شد.\nحالا **ساعت** را انتخاب کنید:",
            reply_markup=get_hours_kb(stage)
        )

    elif action == "hour":
        temp[f"{stage}_hour"] = value
        dt_obj = datetime.datetime(
            year=temp[f"{stage}_year"],
            month=temp[f"{stage}_month"],
            day=temp[f"{stage}_day"],
            hour=value
        )
        ts = dt_obj.timestamp()

        if stage == "start":
            await state.update_data(start_ts=ts)
            await callback.message.edit_text(
                "✅ تاریخ شروع ثبت شد.\n\n🏁 حالا **سال پایان** (End Date) را انتخاب کنید:",
                reply_markup=get_years_kb("end")
            )
        else:
            await state.update_data(end_ts=ts)
            start_ts = data.get("start_ts")
            end_ts = ts
            users = await db.get_users_in_range(start_ts, end_ts)
            count = len(users)

            await callback.message.delete()
            await callback.message.answer(
                f"✅ فیلتر زمانی کامل شد.\n"
                f"📅 از: {datetime.datetime.fromtimestamp(start_ts)}\n"
                f"📅 تا: {datetime.datetime.fromtimestamp(end_ts)}\n\n"
                f"👥 تعداد کاربران پیدا شده: **{count}** نفر\n\n"
                "👇 حالا پیام‌های خود را ارسال کنید:",
                reply_markup=kb_broadcast_actions(),
                resize_keyboard=True,
                one_time_keyboard=False,
                selective=False
            )
            await state.set_state(BroadcastFlow.collecting_messages)
            await state.update_data(messages=[])

    await callback.answer()

# --- Message Collection & Sending ---


@router.message(BroadcastFlow.collecting_messages)
async def collect_broadcast_msgs(message: Message, state: FSMContext, bot: Bot):
    if message.text == "❌ انصراف":
        await state.clear()
        await message.answer("لغو شد.", reply_markup=kb_filter_start())
        return

    if message.text == "✅ ارسال نهایی":
        data = await state.get_data()
        msgs = data.get("messages", [])

        # Check Mode
        mode = data.get("mode", "range")  # range, test, manual, all
        target_users_list = data.get("target_users", [])

        # Logic to determine recipients
        users = []
        start_ts = 0
        end_ts = 0

        if mode == "range" or mode == "all":
            # Existing Logic
            start_ts = data.get("start_ts", 0)
            end_ts = data.get("end_ts", time.time())
            users = await db.get_users_in_range(start_ts, end_ts)

        elif mode in ["test", "manual"]:
            # New Logic for Test/Manual
            users = target_users_list
            # Set fake timestamps for logging purposes
            start_ts = 0
            end_ts = 0

        if not msgs:
            await message.answer("هیچ پیامی ارسال نکردید!")
            return

        if not users:
            await message.answer("کاربری برای ارسال پیدا نشد.")
            return

        # 1. Create a random batch ID
        batch_id = str(uuid.uuid4())

        await message.answer(f"🚀 در حال ارسال برای {len(users)} نفر ({mode})...\n🆔 شناسه ارسال: `{batch_id}`")

        # Save batch info
        await db.save_broadcast_batch(batch_id, start_ts, end_ts, len(users), msgs)

        success = 0
        blocked = 0

        # --- LOOP SENDING ---
        for u in users:
            try:
                for m in msgs:
                    start_time = time.perf_counter()

                    keyboards = await kb_dynamic_casts(db)
                    sent_msg = await main_bot.copy_message(u['user_id'], m['chat_id'], m['message_id'], reply_markup=keyboards)
                    await db.save_broadcast_log(batch_id, u['user_id'], sent_msg.message_id)

                    elapsed = time.perf_counter() - start_time
                    if elapsed < 0.04:
                        await asyncio.sleep(max(0, 0.04 - elapsed))

                success += 1
            except Exception as e:
                logger.error(f"single send error: {e}")
                blocked += 1

        await asyncio.sleep(0.1)

        await db.update_broadcast_batch_stats(batch_id, success, blocked)

        # Create Delete Button
        delete_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🗑 حذف پیام‌های این ارسال (Delete All)", callback_data=f"del_batch:{batch_id}")]
        ])

        await message.answer(
            f"✅ تمام شد.\n"
            f"🆔 Batch ID: `{batch_id}`\n"
            f"🟢 موفق: {success}\n"
            f"🔴 ناموفق: {blocked}\n\n"
            f"⚠️ اگر اشتباهی رخ داده، با دکمه زیر می‌توانید پیام‌های ارسال شده را حذف کنید:",
            reply_markup=delete_kb
        )
        await asyncio.sleep(0.1)

        await state.clear()
        await message.answer("🏠 بازگشت به منوی اصلی:", reply_markup=kb_main_menu())
        return

    current = (await state.get_data()).get("messages", [])

    sent_msg = await bot.copy_message(
        chat_id=CONF["STORAGE_CHANNEL_ID"],
        from_chat_id=message.chat.id,
        message_id=message.message_id
    )

    current.append({
        "chat_id": CONF["STORAGE_CHANNEL_ID"],
        "message_id": sent_msg.message_id
    })

    await state.update_data(messages=current)
    await message.answer("📥 دریافت شد.", reply_markup=kb_broadcast_actions(), resize_keyboard=True,
                         one_time_keyboard=False,
                         selective=False)


# --- Test Mode Handler ---
@router.message(F.text == "🧪 ارسال تستی")
async def filter_test_users(message: Message, state: FSMContext):
    test_users = await db.get_test_users()

    if not test_users:
        await message.answer("❌ هیچ کاربر تستی (test: true) در دیتابیس یافت نشد.")
        return

    # Store the specific list of users in state
    await state.update_data(target_users=test_users, mode="test")

    await message.answer(
        f"🧪 حالت تست فعال شد.\n👥 تعداد گیرندگان: {len(test_users)} نفر\n\n👇 پیام خود را ارسال کنید:",
        reply_markup=kb_broadcast_actions()
    )
    await state.set_state(BroadcastFlow.collecting_messages)


# --- Manual Selection Handlers ---
@router.message(F.text.contains("انتخاب دستی"))
async def filter_manual_start(message: Message, state: FSMContext):
    await message.answer(
        "👤 لطفاً **شناسه عددی (User ID)** کاربران مورد نظر را ارسال کنید.\n"
        "می‌توانید چندین شناسه را با فاصله یا خط جدید جدا کنید.\n\n"
        "مثال:\n`123456789 987654321`",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="❌ انصراف")]], resize_keyboard=True
        )
    )
    await state.set_state(BroadcastFlow.waiting_for_ids)


@router.message(BroadcastFlow.waiting_for_ids)
async def filter_manual_process(message: Message, state: FSMContext):
    if message.text == "❌ انصراف":
        await state.clear()
        await message.answer("لغو شد.", reply_markup=kb_filter_start())
        return

    # Parse IDs from text
    raw_text = message.text.replace("\n", " ").replace(",", " ")
    id_list = []

    try:
        for item in raw_text.split():
            if item.isdigit():
                # specific structure for your loop: {'user_id': 123}
                id_list.append({'user_id': int(item)})
    except Exception:
        await message.answer("❌ فرمت اشتباه است. فقط عدد ارسال کنید.")
        return

    if not id_list:
        await message.answer("❌ هیچ ID معتبری یافت نشد. دوباره تلاش کنید.")
        return

    await state.update_data(target_users=id_list, mode="manual")
    await message.answer(
        f"✅ {len(id_list)} کاربر انتخاب شدند.\n👇 پیام خود را ارسال کنید:",
        reply_markup=kb_broadcast_actions()
    )
    await state.set_state(BroadcastFlow.collecting_messages)

# --- Helper: Core Deletion Logic ---


# --- Manual Batch Deletion Handlers ---

@router.message(F.text == "🗑 حذف با شناسه (Batch ID)")
async def filter_delete_by_id_start(message: Message, state: FSMContext):
    await message.answer(
        "🆔 لطفاً **شناسه ارسال (Batch ID)** را ارسال کنید:\n\n"
        "_(این شناسه یک کد طولانی است که هنگام ارسال همگانی به شما نمایش داده شد)_",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="❌ انصراف")]], resize_keyboard=True
        )
    )
    await state.set_state(BroadcastFlow.waiting_for_batch_id)


@router.message(BroadcastFlow.waiting_for_batch_id)
async def process_manual_batch_delete(message: Message, state: FSMContext):
    if message.text == "❌ انصراف":
        await state.clear()
        await message.answer("لغو شد.", reply_markup=kb_filter_start())
        return

    batch_id = message.text.strip()

    # Basic validation for UUID format (optional, but good practice)
    if len(batch_id) < 10:
        await message.answer("❌ فرمت شناسه به نظر اشتباه می‌رسد. لطفاً دوباره تلاش کنید.")
        return

    # Send a status message to edit later
    status_msg = await message.answer(f"🔎 در حال جستجوی شناسه `{batch_id}` ...")

    # Run the shared deletion logic
    await execute_batch_deletion(batch_id, status_msg)

    await state.clear()
    await message.answer("🏠 بازگشت به منوی اصلی:", reply_markup=kb_main_menu())


# --- Update: Callback Handler for Inline Delete ---

@router.callback_query(F.data.startswith("del_batch:"))
async def delete_broadcast_batch(callback: CallbackQuery):
    batch_id = callback.data.split(":")[1]

    await callback.answer("⏳ عملیات شروع شد...", show_alert=False)

    # We edit the message containing the button to be the status message
    await execute_batch_deletion(batch_id, callback.message)
