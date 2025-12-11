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
from main_bot import main_bot
from config import CONF
from broadcast import kb_filter_start, kb_dynamic_casts

router = Router()
logger = logging.getLogger("broadcast")

# --- States ---


class BroadcastFlow(StatesGroup):
    choosing_daterange = State()
    collecting_messages = State()

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
    await state.update_data(start_ts=0, end_ts=time.time())
    await message.answer("✅ همه کاربران انتخاب شدند.\nپیام‌های خود را ارسال کنید:", reply_markup=kb_broadcast_actions())
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
                reply_markup=kb_broadcast_actions()
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
        start_ts = data.get("start_ts")
        end_ts = data.get("end_ts")

        if not msgs:
            await message.answer("هیچ پیامی ارسال نکردید!")
            return

        users = await db.get_users_in_range(start_ts, end_ts)
        if not users:
            await message.answer("کاربری پیدا نشد.")
            return

        # 1. Create a random batch ID for this broadcast
        batch_id = str(uuid.uuid4())

        await message.answer(f"🚀 در حال ارسال برای {len(users)} نفر...\n🆔 شناسه ارسال: `{batch_id}`")

        success = 0
        blocked = 0

        # --- LOOP SENDING ---
        for u in users:
            try:
                for m in msgs:
                    # 2. Send message
                    sent_msg = await main_bot.copy_message(u['user_id'], m['chat_id'], m['message_id'], reply_markup=kb_dynamic_casts)
                    await db.save_broadcast_log(batch_id, u['user_id'], sent_msg.message_id)

                    await asyncio.sleep(0.05)
                success += 1
            except Exception as e:
                logger.error(f"single send error: {e}")
                blocked += 1

            await asyncio.sleep(0.1)

        # 4. Create Delete Button for Admin
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
        await message.answer("🏠 بازگشت به منوی اصلی:", reply_markup=kb_filter_start())
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
    await message.answer("📥 دریافت شد.")


# --- NEW HANDLER: Delete the broadcast batch ---
@router.callback_query(F.data.startswith("del_batch:"))
async def delete_broadcast_batch(callback: CallbackQuery):
    # Extract batch_id
    batch_id = callback.data.split(":")[1]

    await callback.answer("⏳ در حال حذف پیام‌ها...", show_alert=False)
    await callback.message.edit_text(f"🗑 در حال حذف پیام‌های شناسه `{batch_id}` ... لطفا صبر کنید.")

    # 5. Get logs from DB (You must create this function in database.py)
    # It should return a list of dicts: [{'user_id': 123, 'message_id': 456}, ...]
    logs = await db.get_broadcast_logs(batch_id)

    if not logs:
        await callback.message.edit_text("❌ پیامی برای این شناسه در دیتابیس یافت نشد.")
        return

    deleted_count = 0
    for log in logs:
        try:
            await main_bot.delete_message(chat_id=log['user_id'], message_id=log['message_id'])
            deleted_count += 1
            await asyncio.sleep(0.03)  # Flood limit prevention
        except Exception as e:
            logger.error(
                f"Failed to delete {log['message_id']} for {log['user_id']}: {e}")

    await callback.message.edit_text(
        f"✅ عملیات حذف پایان یافت.\n\n"
        f"🆔 Batch ID: `{batch_id}`\n"
        f"🗑 تعداد حذف شده: {deleted_count} از {len(logs)}"
    )
