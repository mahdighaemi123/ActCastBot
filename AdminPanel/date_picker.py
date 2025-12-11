# date_picker.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData
from calendar import monthrange
import datetime

# این کلاس برای مدیریت دیتای دکمه‌هاست
class DateCallback(CallbackData, prefix="dt"):
    action: str  # year, month, day, hour, submit
    value: int
    stage: str   # start_date یا end_date

def get_years_kb(stage: str):
    current_year = datetime.datetime.now().year
    years = [current_year, current_year - 1, current_year - 2]
    
    buttons = []
    for y in years:
        buttons.append(InlineKeyboardButton(
            text=str(y),
            callback_data=DateCallback(action="year", value=y, stage=stage).pack()
        ))
    
    return InlineKeyboardMarkup(inline_keyboard=[buttons])

def get_months_kb(year: int, stage: str):
    # ماه‌ها را به صورت 3 ردیف 4 تایی می‌چینه
    months = list(range(1, 13))
    rows = []
    temp_row = []
    
    for m in months:
        temp_row.append(InlineKeyboardButton(
            text=f"{m:02d}", # نمایش به صورت 01, 02
            callback_data=DateCallback(action="month", value=m, stage=stage).pack()
        ))
        if len(temp_row) == 4:
            rows.append(temp_row)
            temp_row = []
            
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_days_kb(year: int, month: int, stage: str):
    # محاسبه تعداد روزهای آن ماه خاص
    days_count = monthrange(year, month)[1]
    
    rows = []
    temp_row = []
    
    for d in range(1, days_count + 1):
        temp_row.append(InlineKeyboardButton(
            text=str(d),
            callback_data=DateCallback(action="day", value=d, stage=stage).pack()
        ))
        if len(temp_row) == 7: # هفته‌ای 7 روز
            rows.append(temp_row)
            temp_row = []
    
    if temp_row:
        rows.append(temp_row)
        
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_hours_kb(stage: str):
    # ساعت‌ها 0 تا 23
    rows = []
    temp_row = []
    for h in range(0, 24):
        temp_row.append(InlineKeyboardButton(
            text=f"{h:02d}:00",
            callback_data=DateCallback(action="hour", value=h, stage=stage).pack()
        ))
        if len(temp_row) == 4:
            rows.append(temp_row)
            temp_row = []
            
    return InlineKeyboardMarkup(inline_keyboard=rows)