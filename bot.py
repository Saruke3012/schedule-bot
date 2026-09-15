import logging
import json
import os
from datetime import datetime, timedelta
import pandas as pd
import requests
from io import BytesIO
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- НАСТРОЙКИ ---
TELEGRAM_TOKEN = "8907124758:AAGzCXInWkovQtc3TGry7hc14-uU1BTp4T4"
YANDEX_PUBLIC_LINK = "https://disk.yandex.ru/i/4Nh4FeboZMCPJw"

# ⚠️ УКАЖИТЕ ЗДЕСЬ ВАШУ ГРУППУ (точно как в шапке таблицы)
GROUP_NAME = "ТК-И-09-21"

# Название листа, где находится ваша группа.
# 1 курс (9 кл.) — для первого курса
# 1 курс (11 кл.)-2 курс (9 кл.) — для второго
# 2 курс (11 кл.)-3 курс (9 кл) — для третьего
# 3 курс (11 кл.)-4курс (9 кл.) — для четвёртого
SHEET_NAME = "1 курс (11 кл.)-2 курс (9 кл.)"

WEEK_FILE = "week.json"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


def get_yandex_download_url(public_link):
    """Получает прямую ссылку на скачивание публичного файла с Яндекс.Диска."""
    api_url = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
    params = {"public_key": public_link}
    response = requests.get(api_url, params=params)
    response.raise_for_status()
    return response.json()["href"]


def load_schedule_df():
    """Скачивает и читает нужный лист таблицы."""
    download_url = get_yandex_download_url(YANDEX_PUBLIC_LINK)
    file_data = requests.get(download_url).content
    # header=3 — потому что шапка с днями/группами находится в 4-й строке (индекс 3)
    df = pd.read_excel(BytesIO(file_data), sheet_name=SHEET_NAME, header=3)
    # Убираем полностью пустые строки и столбцы
    df = df.dropna(how="all").dropna(axis=1, how="all")
    return df


def load_current_week():
    """Читает текущую неделю из файла. Если файла нет — создаёт с 'Нечетная'."""
    if os.path.exists(WEEK_FILE):
        with open(WEEK_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("week", "Нечетная")
    else:
        save_current_week("Нечетная")
        return "Нечетная"


def save_current_week(week):
    """Сохраняет текущую неделю в файл."""
    with open(WEEK_FILE, "w", encoding="utf-8") as f:
        json.dump({"week": week}, f, ensure_ascii=False)


def get_week_type_for_date(date):
    """Возвращает текущую неделю (из файла), без автоопределения."""
    return load_current_week()


def get_schedule_for_day(group_name: str, day_offset: int = 0):
    """
    Возвращает текст расписания на указанный день.
    day_offset = 0 — сегодня
    day_offset = 1 — завтра
    """
    target_date = datetime.now() + timedelta(days=day_offset)
    days_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    target_day = days_ru[target_date.weekday()]
    target_date_str = target_date.strftime("%d.%m.%Y")
    week_type = get_week_type_for_date(target_date)

    # Определяем слово для заголовка
    if day_offset == 0:
        day_label = "сегодня"
    elif day_offset == 1:
        day_label = "завтра"
    else:
        day_label = f"через {day_offset} дн."

    if target_day == "Воскресенье":
        return f"📅 {day_label.capitalize()} ({target_day}, {target_date_str}) — выходной, пар нет."

    df = load_schedule_df()

    # Ищем столбец с нужной группой
    group_col = None
    for col in df.columns:
        if str(col).strip().lower() == group_name.strip().lower():
            group_col = col
            break

    if group_col is None:
        available = ", ".join(str(c) for c in df.columns if c not in ["Дни", "Часы", "Неделя"])
        return f"⚠️ Группа '{group_name}' не найдена.\nДоступные группы: {available}"

    current_day = None
    result_lines = []

    for _, row in df.iterrows():
        day_cell = row.get("Дни")
        if pd.notna(day_cell) and str(day_cell).strip():
            current_day = str(day_cell).strip().upper()

        if current_day != target_day.upper():
            continue

        week_cell = row.get("Неделя")
        week_cell_val = str(week_cell).strip() if pd.notna(week_cell) else ""

        if week_cell_val:
            if week_cell_val.lower() != week_type.lower():
                continue

        time_cell = row.get("Часы")
        subject_cell = row.get(group_col)

        if pd.isna(subject_cell) or str(subject_cell).strip() == "":
            continue

        time_str = str(time_cell).strip() if pd.notna(time_cell) else "—"
        subject_str = str(subject_cell).strip().replace("\n", " ")
        result_lines.append(f"🕐 {time_str}\n📚 {subject_str}")

    header = f"📅 Расписание на {day_label} ({target_day}, {target_date_str}, {week_type.lower()} неделя)\n"
    header += f"👥 Группа: {group_name}\n\n"

    if not result_lines:
        return header + "Пар нет."

    return header + "\n\n".join(result_lines)


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /schedule — расписание на сегодня
    /schedule tomorrow — расписание на завтра
    """
    try:
        # Проверяем аргумент после команды
        args = context.args if context.args else []
        if args and args[0].lower() in ("tomorrow", "завтра"):
            day_offset = 1
            await update.message.reply_text("🔍 Смотрю расписание на завтра...")
        else:
            day_offset = 0
            await update.message.reply_text("🔍 Смотрю расписание на сегодня...")

        schedule_text = get_schedule_for_day(GROUP_NAME, day_offset)
        await update.message.reply_text(schedule_text)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await update.message.reply_text("❌ Произошла ошибка при получении расписания.")

async def setweek_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/setweek четная  или  /setweek нечетная"""
    if not context.args:
        current = load_current_week()
        await update.message.reply_text(
            f"Сейчас установлена: *{current}* неделя.\n\n"
            f"Чтобы изменить, напишите:\n"
            f"/setweek четная или /setweek нечетная",
            parse_mode="Markdown"
        )
        return

    new_week = context.args[0].strip().lower()
    if new_week in ("четная", "чётная", "чет", "чёт"):
        save_current_week("Четная")
        await update.message.reply_text("✅ Установлена *Четная* неделя.", parse_mode="Markdown")
    elif new_week in ("нечетная", "нечётная", "нечет", "нечёт"):
        save_current_week("Нечетная")
        await update.message.reply_text("✅ Установлена *Нечетная* неделя.", parse_mode="Markdown")
    else:
        await update.message.reply_text(
            "⚠️ Не понял. Напишите:\n/setweek четная или /setweek нечетная",
            parse_mode="Markdown"
        )


import requests
import os

def send_to_telegram(message):
    """Отправляет сообщение в Telegram-группу."""
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, data={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"})

if name == "main":
    # Получаем расписание на сегодня (day_offset=0)
    schedule_text = get_schedule_for_day(GROUP_NAME, day_offset=0)
    send_to_telegram(schedule_text)
    print("✅ Сообщение отправлено.")