import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from config import CONF

main_bot = Bot(
    token=CONF["BOT_TOKEN"],
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)


async def kb_dynamic_casts(db_service):
    """
    Dynamically creates a ReplyKeyboard based on 'casts' collection in DB.
    """
    casts = await db_service.get_all_casts()

    buttons = []
    for cast in casts:
        buttons.append(KeyboardButton(text=cast.get("name", "Cast")))

    keyboard = []
    row = []
    for btn in buttons:
        row.append(btn)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([KeyboardButton(text="🎧 پشتیبانی")])

    return ReplyKeyboardMarkup(keyboard=keyboard,
                               resize_keyboard=True,
                               one_time_keyboard=False,
                               selective=False)
