import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import CONF

main_bot = Bot(
    token=CONF["BOT_TOKEN"],
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)
