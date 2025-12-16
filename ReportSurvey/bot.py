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
    "MONGO_URL": os.getenv("MONGO_URL", "mongodb://localhost:27017"),
    "DB_NAME": os.getenv("DB_NAME", "act_cast_db"),
    "REPORT_CHANNEL_ID": os.getenv("REPORT_CHANNEL_ID"),  # آیدی گروه آمار
    "INTERVAL": 3600,  # 1 Hour
    "TIMEZONE": "Asia/Tehran"
}

if not CONF["ADMIN_BOT_TOKEN"] or not CONF["REPORT_CHANNEL_ID"]:
    raise ValueError("🔴 Token or Channel ID is missing in .env")

# ---------------------------------------------------------
# 2. REPORTER LOGIC
# ---------------------------------------------------------


class SurveyStatsReporter:
    def __init__(self):
        self.client = AsyncIOMotorClient(CONF["MONGO_URL"])
        self.db = self.client[CONF["DB_NAME"]]
        self.surveys = self.db["surveys"]
        self.users = self.db["users"]

    async def get_user_info_map(self, user_ids):
        """
        اطلاعات یوزرنیم و نام کاربران را بر اساس لیست IDها دریافت می‌کند
        و به صورت یک دیکشنری برمی‌گرداند تا سرعت گزارش‌گیری بالا برود.
        """
        user_map = {}
        if not user_ids:
            return user_map

        # تبدیل لیست به set برای حذف تکراری‌ها
        unique_ids = list(set(user_ids))

        # کوئری زدن به دیتابیس برای دریافت همه این کاربران
        cursor = self.users.find({"user_id": {"$in": unique_ids}})

        async for user in cursor:
            uid = user.get("user_id")
            # ساختن یک رشته شامل نام و یوزرنیم
            full_name = user.get("first_name", "") + " " + \
                user.get("last_name", "") or "Unknown"
            username = f"@{user.get('username')}" if user.get(
                "username") else "No Username"

            user_map[uid] = {
                "full_name": full_name.strip(),
                "username": username
            }
        return user_map

    async def generate_reports(self):
        """
        داده‌ها را جمع‌آوری کرده و خروجی متنی و فایل اکسل را می‌سازد.
        """
        # دریافت تمام نظرسنجی‌ها
        all_surveys = await self.surveys.find({}).to_list(length=None)

        if not all_surveys:
            return None, None

        tz = pytz.timezone(CONF["TIMEZONE"])
        now_str = datetime.now(tz).strftime("%Y-%m-%d %H:%M")

        # --- بخش ۱: آماده‌سازی متن گزارش ---
        report_text = f"📊 **گزارش وضعیت نظرسنجی‌ها**\n📅 زمان: `{now_str}`\n\n"

        # --- بخش ۲: آماده‌سازی اکسل ---
        excel_filename = f"surveys_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

        # استفاده از Pandas ExcelWriter برای ساخت فایل با چند شیت
        try:
            writer = pd.ExcelWriter(excel_filename, engine='openpyxl')
            has_data = False

            for survey in all_surveys:
                survey_id = survey.get("survey_id")
                question = survey.get("question", "بدون سوال")
                options = survey.get("options", [])
                votes = survey.get("votes", {})  # ساختار: {user_id: option_id}

                # >>>> آمار کلی برای متن پیام
                total_votes = len(votes)

                # نگاشت option_id به متن گزینه برای نمایش راحت‌تر
                opt_id_to_text = {opt['id']: opt['text'] for opt in options}

                # شمارش آرا
                vote_counts = {opt['id']: 0 for opt in options}
                for uid, opt_id in votes.items():
                    if opt_id in vote_counts:
                        vote_counts[opt_id] += 1

                # افزودن به متن گزارش
                # خلاصه کردن سوال اگر طولانی باشد
                short_q = (question[:50] +
                           '..') if len(question) > 50 else question

                report_text += f"📌 **{short_q}**\n"
                report_text += f"👥 کل آرا: `{total_votes}`\n"

                for opt in options:
                    count = vote_counts.get(opt['id'], 0)
                    percent = (count / total_votes *
                               100) if total_votes > 0 else 0
                    report_text += f" ▫️ {opt['text']}: {count} ({percent:.1f}%)\n"
                report_text += "──────────────────\n"

                # >>>> ساخت شیت اکسل برای این نظرسنجی
                if total_votes > 0:
                    has_data = True
                    # دریافت اطلاعات کاربران این نظرسنجی
                    user_ids_in_survey = [int(uid) for uid in votes.keys()]
                    user_map = await self.get_user_info_map(user_ids_in_survey)

                    excel_data = []
                    for uid_str, opt_id in votes.items():
                        uid = int(uid_str)
                        u_info = user_map.get(
                            uid, {"full_name": "Unknown", "username": "-"})
                        selected_text = opt_id_to_text.get(
                            opt_id, "Unknown Option")

                        excel_data.append({
                            "User ID": uid,
                            "Full Name": u_info["full_name"],
                            "Username": u_info["username"],
                            "Selected Option": selected_text,
                            "Option ID": opt_id
                        })

                    # تبدیل به DataFrame
                    df = pd.DataFrame(excel_data)

                    # نام شیت (محدودیت ۳۱ کاراکتر اکسل)
                    sheet_name = f"Survey_{survey_id[:8]}"
                    df.to_excel(writer, sheet_name=sheet_name, index=False)

            # ذخیره فایل اکسل
            if has_data:
                writer.close()
            else:
                # اگر هیچ رای‌ای نبود، فایل خالی نسازیم یا یک شیت خالی بسازیم
                writer.close()
                # حذف فایل اگر خالی است (اختیاری)
                # return report_text, None

            return report_text, excel_filename

        except Exception as e:
            logger.error(f"Error generating excel: {e}")
            return f"Error: {e}", None

# ---------------------------------------------------------
# 3. MAIN SCHEDULER
# ---------------------------------------------------------


async def main():
    bot = Bot(
        token=CONF["ADMIN_BOT_TOKEN"],
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    reporter = SurveyStatsReporter()

    logger.info("✅ Survey Reporter Service Started...")

    while True:
        try:
            logger.info("⏳ Starting report generation cycle...")

            # تولید گزارش
            text_msg, excel_path = await reporter.generate_reports()

            if text_msg:
                # 1. ارسال گزارش متنی
                # اگر متن خیلی طولانی بود (بیش از 4096 کاراکتر)، باید تیکه تیکه شود.
                # اینجا فرض بر این است که تعداد نظرسنجی‌ها معقول است.
                if len(text_msg) > 4000:
                    text_msg = text_msg[:4000] + \
                        "\n\n⚠️ متن بریده شد (خیلی طولانی)..."

                await bot.send_message(
                    chat_id=CONF["REPORT_CHANNEL_ID"],
                    text=text_msg
                )

                # 2. ارسال فایل اکسل (اگر وجود داشت)
                if excel_path and os.path.exists(excel_path):
                    file_input = FSInputFile(excel_path)
                    await bot.send_document(
                        chat_id=CONF["REPORT_CHANNEL_ID"],
                        document=file_input,
                        caption="📂 فایل ریز مکالمات و انتخاب کاربران"
                    )

                    # پاک کردن فایل بعد از ارسال برای جلوگیری از پر شدن دیسک
                    os.remove(excel_path)
                    logger.info("Report sent and temp file cleaned.")
                else:
                    logger.info("No excel file generated (maybe no votes).")
            else:
                logger.info("No surveys found in DB.")

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
