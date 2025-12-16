import uuid
import asyncio
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from main_bot import main_bot, kb_dynamic_casts
import time
from config import CONF, is_admin
from database import db
from upload_content import kb_main_menu
survey_router = Router()

# ---------------------------------------------------------
# STATES (وضعیت‌های ساخت نظرسنجی)
# ---------------------------------------------------------


class SurveyFlow(StatesGroup):
    waiting_for_question = State()       # دریافت متن اصلی نظرسنجی
    waiting_for_option_text = State()    # دریافت متن دکمه
    waiting_for_option_reply = State()   # دریافت پیامی که بعد از کلیک نمایش داده شود
    confirm_send = State()               # تایید نهایی و ارسال

# ---------------------------------------------------------
# KEYBOARDS (دکمه‌های منوی ساخت)
# ---------------------------------------------------------


def kb_survey_control():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ اتمام و ساخت نظرسنجی")],
            [KeyboardButton(text="❌ انصراف")]
        ],
        resize_keyboard=True
    )


def kb_cancel_only():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ انصراف")]],
        resize_keyboard=True
    )

# ---------------------------------------------------------
# HANDLERS: شروع ساخت نظرسنجی
# ---------------------------------------------------------


@survey_router.message(F.text == "📊 ایجاد نظرسنجی")
async def start_survey_creation(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.clear()
    await message.answer(
        "📝 **ساخت نظرسنجی هوشمند**\n\n"
        "لطفاً **متن اصلی سوال** یا توضیحات نظرسنجی را وارد کنید:",
        reply_markup=kb_cancel_only()
    )
    await state.set_state(SurveyFlow.waiting_for_question)


@survey_router.message(SurveyFlow.waiting_for_question)
async def process_question(message: Message, state: FSMContext):
    if message.text == "❌ انصراف":
        await state.clear()
        await message.answer("لغو شد.")
        return

    # ذخیره سوال و آماده‌سازی لیست گزینه‌ها
    await state.update_data(question_text=message.text, options=[])

    await message.answer(
        "✅ متن سوال ثبت شد.\n\n"
        "حالا **متن دکمه اول** را بفرستید:\n"
        "(مثلاً: «گزینه الف» یا «خرید محصول»)",
        reply_markup=kb_cancel_only()
    )
    await state.set_state(SurveyFlow.waiting_for_option_text)

# ---------------------------------------------------------
# HANDLERS: چرخه افزودن دکمه و پاسخ
# ---------------------------------------------------------


@survey_router.message(SurveyFlow.waiting_for_option_text)
async def process_option_text(message: Message, state: FSMContext):
    text = message.text
    if text == "❌ انصراف":
        await state.clear()
        await message.answer("لغو شد.")
        return

    # اگر کاربر دکمه اتمام را زد (در دورهای بعدی)
    if text == "✅ اتمام و ساخت نظرسنجی":
        await finalize_survey_creation(message, state)
        return

    # ذخیره متن دکمه موقت
    await state.update_data(current_btn_text=text)

    await message.answer(
        f"💬 برای دکمه **«{text}»** چه جوابی ارسال شود؟\n\n"
        "وقتی کاربر روی این دکمه زد، ربات چه متنی را به او نمایش دهد؟",
        reply_markup=kb_cancel_only()
    )
    await state.set_state(SurveyFlow.waiting_for_option_reply)


@survey_router.message(SurveyFlow.waiting_for_option_reply)
async def process_option_reply(message: Message, state: FSMContext):
    reply_text = message.text
    if reply_text == "❌ انصراف":
        await state.clear()
        await message.answer("لغو شد.")
        return

    data = await state.get_data()
    options = data.get("options", [])
    btn_text = data.get("current_btn_text")

    # ساخت یک شناسه کوتاه برای دکمه
    opt_id = str(uuid.uuid4())[:8]

    # افزودن به لیست
    options.append({
        "id": opt_id,
        "text": btn_text,
        "reply": reply_text
    })

    await state.update_data(options=options)

    await message.answer(
        f"✅ دکمه «{btn_text}» با موفقیت اضافه شد.\n\n"
        "👇 دکمه بعدی را وارد کنید یا روی **«اتمام و ساخت»** بزنید.",
        reply_markup=kb_survey_control()
    )
    # بازگشت به حالت دریافت متن دکمه برای دکمه بعدی
    await state.set_state(SurveyFlow.waiting_for_option_text)

# ---------------------------------------------------------
# HANDLERS: اتمام و پیش‌نمایش
# ---------------------------------------------------------


async def finalize_survey_creation(message: Message, state: FSMContext):
    data = await state.get_data()
    options = data.get("options", [])
    question = data.get("question_text")

    if not options:
        await message.answer("⚠️ شما هیچ گزینه‌ای اضافه نکردید!")
        return

    # تولید شناسه یکتا برای کل نظرسنجی
    survey_id = str(uuid.uuid4())
    await state.update_data(survey_id=survey_id)

    # ساخت کیبورد شیشه‌ای برای پیش‌نمایش
    builder = InlineKeyboardBuilder()
    for opt in options:
        # callback format: surv:{survey_id}:{option_id}
        builder.button(text=opt['text'],
                       callback_data=f"surv:{survey_id}:{opt['id']}")
    builder.adjust(1)

    await message.answer(
        "📋 **پیش‌نمایش نظرسنجی:**\n\n"
        f"{question}\n\n"
        "------------------\n"
        "آیا مایل به ارسال همگانی این نظرسنجی هستید؟",
        reply_markup=builder.as_markup()
    )

    # کیبورد تصمیم‌گیری ادمین
    kb_confirm = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="ارسال همگانی"),
             KeyboardButton(text="ارسال تستی")],
            [KeyboardButton(text="❌ لغو")]
        ],
        resize_keyboard=True
    )
    await message.answer("یکی از گزینه‌های زیر را انتخاب کنید:", reply_markup=kb_confirm)
    await state.set_state(SurveyFlow.confirm_send)


@survey_router.message(SurveyFlow.confirm_send)
async def confirm_survey_send(message: Message, state: FSMContext, bot: Bot):
    text = message.text
    if text == "❌ لغو":
        await state.clear()
        await message.answer("عملیات لغو شد.", reply_markup=kb_main_menu)
        return

    data = await state.get_data()
    survey_id = data.get("survey_id")
    question = data.get("question_text")
    options = data.get("options")

    # 1. ذخیره نظرسنجی در دیتابیس (فقط بار اول اگر هنوز ذخیره نشده باشد منطق آن را هندل کنید یا کلا overwrite شود)
    # اینجا فرض بر این است که هربار ذخیره شود مشکلی ندارد
    await db.create_survey(survey_id, question, options)

    # تعیین گیرندگان بر اساس دکمه زده شده
    target_users = []
    is_test_mode = False

    if text == "ارسال همگانی":
        await message.answer("⏳ در حال جمع‌آوری کاربران و شروع ارسال همگانی...")
        target_users = await db.users.find({}, {"user_id": 1}).to_list(length=None)

    elif text == "ارسال تستی":
        await message.answer("🧪 در حال ارسال به کاربران تستی...")
        target_users = await db.get_test_users()
        is_test_mode = True

    else:
        return  # دستور ناشناخته

    if not target_users:
        await message.answer("⚠️ کاربری برای ارسال یافت نشد.")
        return

    # ساخت دکمه‌های شیشه‌ای نظرسنجی
    builder = InlineKeyboardBuilder()
    for opt in options:
        builder.button(text=opt['text'],
                       callback_data=f"surv:{survey_id}:{opt['id']}")
    builder.adjust(1)
    markup = builder.as_markup()

    # تولید شناسه یکتا برای این نوبت ارسال (Batch ID)
    batch_id = str(uuid.uuid4())

    count = 0
    blocked = 0

    # شروع لوپ ارسال
    for u in target_users:
        try:
            start_time = time.perf_counter()

            # ارسال پیام
            sent_msg = await main_bot.send_message(chat_id=u['user_id'], text=question, reply_markup=markup)

            # --- ذخیره لاگ پیام برای قابلیت حذف ---
            # متد save_broadcast_log باید در database.py باشد
            await db.save_broadcast_log(
                batch_id=batch_id,
                user_id=u['user_id'],
                message_id=sent_msg.message_id
            )
            # ---------------------------------------

            count += 1

            # تاخیر کوچک برای جلوگیری از فلود (فقط در حالت همگانی مهم‌تر است)
            elapsed = time.perf_counter() - start_time
            if elapsed < 0.05:
                await asyncio.sleep(max(0, 0.05 - elapsed))

        except Exception as e:
            # logger.error(f"Failed to send: {e}")
            blocked += 1

    # پیام پایانی با دکمه حذف
    summary = (
        f"✅ **ارسال {'تستی' if is_test_mode else 'همگانی'} پایان یافت.**\n\n"
        f"📤 موفق: {count}\n"
        f"🚫 ناموفق: {blocked}\n"
        f"🆔 شناسه بچ: `{batch_id}`"
    )

    # ساخت دکمه حذف برای همین بچ
    del_markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 حذف پیام‌های این ارسال",
                              callback_data=f"del_batch:{batch_id}")]
    ])

    await message.answer(summary, reply_markup=del_markup)

    await message.answer("منو:", reply_markup=kb_main_menu)
    await state.clear()
