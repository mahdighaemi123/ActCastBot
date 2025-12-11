import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import CONF
# روتر را از فایل جدید ایمپورت می‌کنیم
from upload_content import router as upload_router

# Setup Logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("admin_bot")

async def main():
    bot = Bot(
        token=CONF["ADMIN_BOT_TOKEN"],
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )

    dp = Dispatcher()
    
    # اضافه کردن روتری که ساختیم
    dp.include_router(upload_router)

    logger.info("🚀 Admin Bot Started...")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())