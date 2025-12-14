from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
)
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import CONF
# روتر را از فایل جدید ایمپورت می‌کنیم
from upload_content import router as upload_router
from broadcast import router as broadcast_router

import asyncio
import logging
from typing import Callable, Dict, Any, Awaitable

from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import TelegramObject

from config import CONF
from upload_content import router as upload_router
from broadcast import router as broadcast_router

# Setup Logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

logger = logging.getLogger("admin_bot")


class GlobalLockMiddleware(BaseMiddleware):
    """
    This middleware forces updates to be processed one by one.
    It uses an asyncio Lock to pause new updates until the current one finishes.
    """

    def __init__(self):
        self.lock = asyncio.Lock()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        async with self.lock:
            return await handler(event, data)


async def main():
    bot = Bot(
        token=CONF["ADMIN_BOT_TOKEN"],
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )

    dp = Dispatcher()

    dp.update.outer_middleware(GlobalLockMiddleware())

    dp.include_router(upload_router)
    dp.include_router(broadcast_router)

    logger.info("🚀 Admin Bot Started...")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
