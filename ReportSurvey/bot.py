import asyncio
import logging
import os
import pandas as pd
from datetime import datetime
import pytz
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from aiogram import Bot
from aiogram.types import FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import re
# ---------------------------------------------------------
# 1. CONFIGURATION
# ---------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [SURVEY REPORTER] - %(levelname)s - %(message)s"
)
logger = logging.getLogger("survey_reporter")

CONF = {
    "ADMIN_BOT_TOKEN": os.getenv("ADMIN_BOT_TOKEN"),
    "MONGODB_URL": os.getenv("MONGODB_URL", "mongodb://localhost:27017"),
    "DB_NAME": os.getenv("DB_NAME", "act_cast_db"),
    "REPORT_CHANNEL_ID": os.getenv("REPORT_CHANNEL_ID"),
    "INTERVAL": 3600,  # 1 Hour
    "TIMEZONE": "Asia/Tehran"
}

if not CONF["ADMIN_BOT_TOKEN"] or not CONF["REPORT_CHANNEL_ID"]:
    raise ValueError("🔴 Token or Channel ID is missing in .env")

# ---------------------------------------------------------
# 2. REPORTER LOGIC
# ---------------------------------------------------------


def convert_to_english_digits(text):
    """Convert Persian digits in the input text to English digits."""
    if not isinstance(text, str):
        return text
    persian_digits = '۰۱۲۳۴۵۶۷۸۹'
    english_digits = '0123456789'
    trans_table = str.maketrans(persian_digits, english_digits)
    return text.translate(trans_table)


def remove_trailing_dot_zero(text):
    """Remove trailing '.0' or '.00' from the input text."""
    if not isinstance(text, str):
        return text
    if text.endswith('.00'):
        return text[:-3]
    elif text.endswith('.0'):
        return text[:-2]
    return text


def standardize_phone_number(phone):
    """Standardize phone numbers to the format '09xxxxxxxxx'."""
    if phone is None or phone == "":
        return phone

    phone = str(phone).strip()
    phone = remove_trailing_dot_zero(phone)
    phone = convert_to_english_digits(phone)
    phone = re.sub(r'\D', '', phone)

    if phone.startswith('+98'):
        phone = '0' + phone[3:]

    elif phone.startswith('0098'):
        phone = '0' + phone[4:]

    elif phone.startswith('98'):
        phone = '0' + phone[2:]

    if len(phone) == 10:
        if not phone.startswith('0'):
            phone = '0' + phone

    return phone


class SurveyStatsReporter:
    def __init__(self):
        self.client = AsyncIOMotorClient(CONF["MONGODB_URL"])
        self.db = self.client[CONF["DB_NAME"]]
        self.surveys = self.db["surveys"]
        self.users = self.db["users"]

    async def get_user_info_map(self, user_ids):
        """
        اطلاعات یوزرنیم و نام کاربران را دریافت می‌کند.
        """
        user_map = {}
        if not user_ids:
            return user_map

        unique_ids = list(set(user_ids))
        cursor = self.users.find({"user_id": {"$in": unique_ids}})

        async for user in cursor:
            uid = user.get("user_id")
            full_name = (user.get("first_name", "") + " " +
                         user.get("last_name", "")).strip() or "Unknown"
            username = f"@{user.get('username')}" if user.get(
                "username") else "No Username"

            user_map[uid] = {
                "full_name": full_name,
                "username": username
            }
        return user_map

    async def generate_individual_reports(self):
        """
        برای هر نظرسنجی یک دیکشنری شامل متن و مسیر فایل اکسل برمی‌گرداند.
        خروجی: لیستی از گزارش‌ها
        """
        all_surveys = await self.surveys.find({}).to_list(length=None)

        if not all_surveys:
            return []

        tz = pytz.timezone(CONF["TIMEZONE"])
        now_str = datetime.now(tz).strftime("%Y-%m-%d | %H:%M")

        reports_list = []

        for survey in all_surveys:
            try:
                survey_id = survey.get("survey_id")
                question = survey.get("question", "بدون سوال")
                options = survey.get("options", [])
                votes = survey.get("votes", {})

                # 1. آماده‌سازی متن گزارش تکی
                total_votes = len(votes)

                # خلاصه متن سوال
                short_q = (question[:100] +
                           '...') if len(question) > 100 else question

                text_report = (
                    f"📊 **گزارش نظرسنجی**\n"
                    f"📅 زمان: `{now_str}`\n"
                    f"❓ **سوال:** {short_q}\n"
                    f"👥 **تعداد کل آرا:** `{total_votes}`\n"
                    f"──────────────────\n"
                )

                # شمارش آرا
                vote_counts = {opt['id']: 0 for opt in options}
                opt_id_to_text = {opt['id']: opt['text'] for opt in options}

                for uid, opt_id in votes.items():
                    if opt_id in vote_counts:
                        vote_counts[opt_id] += 1

                # افزودن جزئیات گزینه‌ها به متن
                for opt in options:
                    count = vote_counts.get(opt['id'], 0)
                    percent = (count / total_votes *
                               100) if total_votes > 0 else 0
                    text_report += f"🔹 **{opt['text']}**: {count} ({percent:.1f}%)\n"

                # 2. آماده‌سازی فایل اکسل تکی (فقط اگر رای وجود داشته باشد)
                excel_path = None
                if total_votes > 0:
                    user_ids_in_survey = [int(uid) for uid in votes.keys()]
                    user_map = await self.get_user_info_map(user_ids_in_survey)

                    excel_data = []
                    for uid_str, opt_id in votes.items():
                        uid = int(uid_str)
                        u_info = user_map.get(
                            uid, {"name": "Unknown", "username": "-"})
                        selected_text = opt_id_to_text.get(
                            opt_id, "Unknown Option")

                        excel_data.append({
                            "User ID": uid,
                            "Phone": standardize_phone_number(u_info["phone"]),
                            "Name": u_info["name"],
                            "Username": u_info["username"],
                            "Selected Option": selected_text,
                            "Time": now_str
                        })

                    # ساخت فایل اکسل اختصاصی برای این نظرسنجی
                    df = pd.DataFrame(excel_data)
                    # استفاده از 8 کاراکتر اول ID برای نام فایل
                    safe_filename = f"report_{survey_id[:8]}_{datetime.now().strftime('%M%S')}.xlsx"
                    df.to_excel(safe_filename, index=False)
                    excel_path = safe_filename

                # افزودن به لیست گزارش‌ها
                reports_list.append({
                    "text": text_report,
                    "excel_file": excel_path,
                    "survey_id": survey_id,
                    "short_q": short_q,
                })

            except Exception as e:
                logger.error(
                    f"Error processing survey {survey.get('survey_id')}: {e}")
                continue

        return reports_list

# ---------------------------------------------------------
# 3. MAIN SCHEDULER
# ---------------------------------------------------------


async def main():
    bot = Bot(
        token=CONF["ADMIN_BOT_TOKEN"],
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    reporter = SurveyStatsReporter()

    logger.info("✅ Survey Reporter Service Started (Individual Mode)...")

    while True:
        try:
            logger.info("⏳ Starting report generation cycle...")

            # دریافت لیست گزارش‌ها
            reports = await reporter.generate_individual_reports()

            if reports:
                logger.info(f"📤 Sending {len(reports)} survey reports...")

                for rep in reports:
                    # 1. ارسال متن
                    await bot.send_message(
                        chat_id=CONF["REPORT_CHANNEL_ID"],
                        text=rep["text"]
                    )

                    # 2. ارسال فایل اکسل (اگر وجود داشت)
                    excel_path = rep["excel_file"]
                    if excel_path and os.path.exists(excel_path):
                        file_input = FSInputFile(excel_path)
                        await bot.send_document(
                            chat_id=CONF["REPORT_CHANNEL_ID"],
                            document=file_input,
                            caption=f"📂 فایل اکسل جزئیات نظرسنجی:\n {rep['short_q'][:100]}"
                        )

                        # حذف فایل
                        os.remove(excel_path)

                    # تاخیر کوتاه بین هر نظرسنجی برای جلوگیری از اسپم شدن
                    await asyncio.sleep(2)

                logger.info("✅ All reports sent successfully.")
            else:
                logger.info("No surveys found.")

        except Exception as e:
            logger.error(f"❌ Critical Error: {e}")

        # انتظار برای سیکل بعدی (۱ ساعت)
        logger.info(f"💤 Sleeping for {CONF['INTERVAL']} seconds...")
        await asyncio.sleep(CONF['INTERVAL'])

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
