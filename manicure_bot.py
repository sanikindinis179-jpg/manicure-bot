"""
💅 Бот для мастера маникюра
Все модули объединены в один файл для простого деплоя
"""

import asyncio
import logging
import sqlite3
import calendar
import aiosqlite
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ─── КОНФИГ ───────────────────────────────────────────────────────────────────
BOT_TOKEN           = "8796930951:AAG9dY3YvQ-L_MNBB-LgICl7FRamH3bBMZc"
ADMIN_ID            = 586062785
SCHEDULE_CHANNEL_ID = "@manicure_studio_2026"
CHANNEL_ID          = "@manicure_studio_2026"
CHANNEL_LINK        = "https://t.me/manicure_studio_2026"
MASTER_NAME         = "💅 Маникюр Студия"
DB_PATH             = "manicure.db"

# ─── БАЗА ДАННЫХ ──────────────────────────────────────────────────────────────
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL, time TEXT NOT NULL,
                is_available INTEGER DEFAULT 1,
                is_day_closed INTEGER DEFAULT 0,
                UNIQUE(date, time)
            )""")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL, username TEXT,
                name TEXT NOT NULL, phone TEXT NOT NULL,
                date TEXT NOT NULL, time TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                reminder_sent INTEGER DEFAULT 0
            )""")
        await db.commit()

async def add_slot(date, time):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("INSERT OR IGNORE INTO slots (date, time) VALUES (?, ?)", (date, time))
            await db.commit()
            return True
        except: return False

async def delete_slot(date, time):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM slots WHERE date=? AND time=? AND is_available=1", (date, time))
        await db.commit()

async def get_available_dates():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT DISTINCT date FROM slots
            WHERE is_available=1 AND is_day_closed=0 AND date >= date('now')
            ORDER BY date""") as c:
            return [r[0] for r in await c.fetchall()]

async def get_available_times(date):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT time FROM slots WHERE date=? AND is_available=1 AND is_day_closed=0 ORDER BY time",
            (date,)) as c:
            return [r[0] for r in await c.fetchall()]

async def get_all_times(date):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT time, is_available FROM slots WHERE date=? ORDER BY time", (date,)) as c:
            return await c.fetchall()

async def close_day(date):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE slots SET is_day_closed=1 WHERE date=?", (date,))
        await db.commit()

async def open_day(date):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE slots SET is_day_closed=0 WHERE date=?", (date,))
        await db.commit()

async def mark_slot_unavailable(date, time):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE slots SET is_available=0 WHERE date=? AND time=?", (date, time))
        await db.commit()

async def mark_slot_available(date, time):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE slots SET is_available=1 WHERE date=? AND time=?", (date, time))
        await db.commit()

async def create_booking(user_id, username, name, phone, date, time):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO bookings (user_id, username, name, phone, date, time) VALUES (?,?,?,?,?,?)",
            (user_id, username, name, phone, date, time))
        await db.commit()

async def get_user_booking(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, date, time, name, phone FROM bookings WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
            (user_id,)) as c:
            return await c.fetchone()

async def delete_booking(booking_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT date, time, user_id FROM bookings WHERE id=?", (booking_id,)) as c:
            row = await c.fetchone()
        if row:
            await mark_slot_available(row[0], row[1])
        await db.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
        await db.commit()
        return row

async def get_bookings_by_date(date):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, time, name, phone, username, user_id FROM bookings WHERE date=? ORDER BY time",
            (date,)) as c:
            return await c.fetchall()

async def get_future_bookings():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, user_id, name, date, time FROM bookings
            WHERE datetime(date || ' ' || time) > datetime('now') AND reminder_sent=0""") as c:
            return await c.fetchall()

async def mark_reminder_sent(booking_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE bookings SET reminder_sent=1 WHERE id=?", (booking_id,))
        await db.commit()

# ─── КЛАВИАТУРЫ ───────────────────────────────────────────────────────────────
MONTHS = ["","января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"]
DAYS_RU = ["понедельник","вторник","среда","четверг","пятница","суббота","воскресенье"]

def pretty_date(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{d.day} {MONTHS[d.month]} {d.year} ({DAYS_RU[d.weekday()]})"

def main_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📅 Записаться", callback_data="book_start"))
    kb.row(InlineKeyboardButton(text="❌ Отменить запись", callback_data="cancel_booking"))
    kb.row(
        InlineKeyboardButton(text="💰 Прайсы", callback_data="prices"),
        InlineKeyboardButton(text="🖼 Портфолио", callback_data="portfolio")
    )
    return kb.as_markup()

def subscribe_kb():
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📢 Подписаться", url=CHANNEL_LINK))
    kb.row(InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription"))
    return kb.as_markup()

def calendar_kb(available_dates, year=None, month=None):
    now = datetime.now()
    year = year or now.year
    month = month or now.month
    month_names = ["","Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"]
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=f"📅 {month_names[month]} {year}", callback_data="ignore"))
    kb.row(*[InlineKeyboardButton(text=d, callback_data="ignore") for d in ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]])
    for week in calendar.monthcalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
            else:
                date_str = f"{year}-{month:02d}-{day:02d}"
                if datetime(year, month, day).date() < now.date():
                    row.append(InlineKeyboardButton(text="✖️", callback_data="ignore"))
                elif date_str in available_dates:
                    row.append(InlineKeyboardButton(text=f"✅{day}", callback_data=f"date_{date_str}"))
                else:
                    row.append(InlineKeyboardButton(text=str(day), callback_data="ignore"))
        kb.row(*row)
    pm = month-1 if month>1 else 12; py = year if month>1 else year-1
    nm = month+1 if month<12 else 1; ny = year if month<12 else year+1
    kb.row(
        InlineKeyboardButton(text="◀️", callback_data=f"cal_{py}_{pm}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu"),
        InlineKeyboardButton(text="▶️", callback_data=f"cal_{ny}_{nm}"),
    )
    return kb.as_markup()

def times_kb(times, date):
    kb = InlineKeyboardBuilder()
    for t in times:
        kb.add(InlineKeyboardButton(text=f"🕐 {t}", callback_data=f"time_{date}_{t}"))
    kb.adjust(3)
    kb.row(InlineKeyboardButton(text="◀️ Назад", callback_data="book_start"))
    return kb.as_markup()

def confirm_kb(date, time):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_{date}_{time}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu")
    )
    return kb.as_markup()

def cancel_confirm_kb(booking_id):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ Да, отменить", callback_data=f"do_cancel_{booking_id}"),
        InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")
    )
    return kb.as_markup()

def back_kb():
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return kb.as_markup()

def portfolio_kb():
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🖼 Смотреть портфолио", url="https://ru.pinterest.com/crystalwithluv/_created/"))
    kb.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return kb.as_markup()

def admin_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📅 Добавить рабочий день", callback_data="admin_add_day"))
    kb.row(InlineKeyboardButton(text="⏰ Добавить слот", callback_data="admin_add_slot"))
    kb.row(InlineKeyboardButton(text="🗑 Удалить слот", callback_data="admin_del_slot"))
    kb.row(InlineKeyboardButton(text="🚫 Закрыть день", callback_data="admin_close_day"))
    kb.row(InlineKeyboardButton(text="✅ Открыть день", callback_data="admin_open_day"))
    kb.row(InlineKeyboardButton(text="📋 Расписание на дату", callback_data="admin_schedule"))
    kb.row(InlineKeyboardButton(text="❌ Отменить запись клиента", callback_data="admin_cancel"))
    kb.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return kb.as_markup()

def admin_back_kb():
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="◀️ Назад в админ-панель", callback_data="admin_panel"))
    return kb.as_markup()

def admin_bookings_kb(bookings):
    kb = InlineKeyboardBuilder()
    for b in bookings:
        bid, time, name, *_ = b
        kb.row(InlineKeyboardButton(text=f"❌ {time} — {name}", callback_data=f"admin_do_cancel_{bid}"))
    kb.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel"))
    return kb.as_markup()

# ─── FSM ──────────────────────────────────────────────────────────────────────
class BookState(StatesGroup):
    name  = State()
    phone = State()

class AdminState(StatesGroup):
    add_day       = State()
    add_slot_date = State()
    add_slot_time = State()
    del_slot_date = State()
    del_slot_time = State()
    close_day     = State()
    open_day      = State()
    schedule      = State()
    cancel_date   = State()

# ─── РОУТЕР ───────────────────────────────────────────────────────────────────
router = Router()
bot_instance: Bot = None
scheduler = AsyncIOScheduler()

# ─── ПОДПИСКА ─────────────────────────────────────────────────────────────────
async def check_sub(user_id):
    try:
        m = await bot_instance.get_chat_member(CHANNEL_ID, user_id)
        return m.status not in ("left","kicked","banned")
    except: return True

# ─── ПОЛЬЗОВАТЕЛЬ ─────────────────────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(f"👋 Добро пожаловать в <b>{MASTER_NAME}</b>!\n\nВыберите действие:",
                     reply_markup=main_menu_kb(), parse_mode="HTML")

@router.callback_query(F.data == "main_menu")
async def cb_main_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text(f"👋 Добро пожаловать в <b>{MASTER_NAME}</b>!\n\nВыберите действие:",
                                reply_markup=main_menu_kb(), parse_mode="HTML")

@router.callback_query(F.data == "prices")
async def cb_prices(cb: CallbackQuery):
    await cb.message.edit_text(
        "💰 <b>Прайс-лист</b>\n\n💅 Френч — <b>1000₽</b>\n💅 Квадрат — <b>500₽</b>",
        reply_markup=back_kb(), parse_mode="HTML")

@router.callback_query(F.data == "portfolio")
async def cb_portfolio(cb: CallbackQuery):
    await cb.message.edit_text("🖼 <b>Моё портфолио</b>\n\nПосмотрите мои работы 👇",
                                reply_markup=portfolio_kb(), parse_mode="HTML")

@router.callback_query(F.data == "check_subscription")
async def cb_check_sub(cb: CallbackQuery):
    if await check_sub(cb.from_user.id):
        await cb.message.edit_text("✅ Подписка подтверждена!\n\nВыберите действие:", reply_markup=main_menu_kb())
    else:
        await cb.answer("❌ Вы ещё не подписались!", show_alert=True)

@router.callback_query(F.data == "book_start")
async def cb_book_start(cb: CallbackQuery, state: FSMContext):
    if not await check_sub(cb.from_user.id):
        await cb.message.edit_text("📢 Для записи необходимо подписаться на канал",
                                   reply_markup=subscribe_kb())
        return
    existing = await get_user_booking(cb.from_user.id)
    if existing:
        bid, date, time, name, phone = existing
        await cb.message.edit_text(
            f"⚠️ У вас уже есть запись:\n\n📅 <b>{pretty_date(date)}</b>\n🕐 <b>{time}</b>\n👤 {name}\n\nСначала отмените текущую.",
            reply_markup=cancel_confirm_kb(bid), parse_mode="HTML")
        return
    dates = await get_available_dates()
    if not dates:
        await cb.message.edit_text("😔 Свободных окошек пока нет. Загляните позже!", reply_markup=back_kb())
        return
    now = datetime.now()
    await cb.message.edit_text("📅 Выберите удобную дату:\n\n✅ — доступные дни",
                                reply_markup=calendar_kb(dates, now.year, now.month))

@router.callback_query(F.data.startswith("cal_"))
async def cb_cal_nav(cb: CallbackQuery):
    _, year, month = cb.data.split("_")
    dates = await get_available_dates()
    await cb.message.edit_reply_markup(reply_markup=calendar_kb(dates, int(year), int(month)))

@router.callback_query(F.data.startswith("date_"))
async def cb_date(cb: CallbackQuery, state: FSMContext):
    date = cb.data.replace("date_", "")
    times = await get_available_times(date)
    if not times:
        await cb.answer("😔 На эту дату нет свободного времени", show_alert=True)
        return
    await state.update_data(selected_date=date)
    await cb.message.edit_text(f"📅 <b>{pretty_date(date)}</b>\n\n🕐 Выберите удобное время:",
                                reply_markup=times_kb(times, date), parse_mode="HTML")

@router.callback_query(F.data.startswith("time_"))
async def cb_time(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split("_", 2)
    date, time = parts[1], parts[2]
    await state.update_data(selected_date=date, selected_time=time)
    await state.set_state(BookState.name)
    await cb.message.edit_text(
        f"✅ Выбрано: <b>{pretty_date(date)}</b> в <b>{time}</b>\n\n👤 Введите ваше <b>имя</b>:",
        parse_mode="HTML")

@router.message(BookState.name)
async def process_name(msg: Message, state: FSMContext):
    if len(msg.text.strip()) < 2:
        await msg.answer("❌ Введите корректное имя (минимум 2 символа):"); return
    await state.update_data(name=msg.text.strip())
    await state.set_state(BookState.phone)
    await msg.answer(f"👤 Имя: <b>{msg.text.strip()}</b>\n\n📞 Введите ваш <b>номер телефона</b>:",
                     parse_mode="HTML")

@router.message(BookState.phone)
async def process_phone(msg: Message, state: FSMContext):
    phone = msg.text.strip()
    if len(''.join(filter(str.isdigit, phone))) < 10:
        await msg.answer("❌ Введите корректный номер (минимум 10 цифр):"); return
    data = await state.get_data()
    await state.update_data(phone=phone)
    await msg.answer(
        f"📋 <b>Подтвердите запись:</b>\n\n"
        f"📅 {pretty_date(data['selected_date'])}\n"
        f"🕐 {data['selected_time']}\n"
        f"👤 {data['name']}\n📞 {phone}",
        reply_markup=confirm_kb(data['selected_date'], data['selected_time']),
        parse_mode="HTML")

@router.callback_query(F.data.startswith("confirm_"))
async def cb_confirm(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split("_", 2)
    date, time = parts[1], parts[2]
    data = await state.get_data()
    times = await get_available_times(date)
    if time not in times:
        await cb.answer("😔 Это время уже занято! Выберите другое.", show_alert=True)
        await state.clear(); return
    name     = data.get("name","—")
    phone    = data.get("phone","—")
    username = cb.from_user.username or "—"
    await mark_slot_unavailable(date, time)
    await create_booking(cb.from_user.id, username, name, phone, date, time)

    # Планируем напоминание
    booking = await get_user_booking(cb.from_user.id)
    if booking:
        schedule_reminder(booking[0], cb.from_user.id, date, time)

    await state.clear()
    await cb.message.edit_text(
        f"✅ <b>Запись подтверждена!</b>\n\n📅 {pretty_date(date)}\n🕐 {time}\n👤 {name}\n📞 {phone}\n\nЖдём вас! 💅",
        reply_markup=back_kb(), parse_mode="HTML")
    try:
        await bot_instance.send_message(ADMIN_ID,
            f"🔔 <b>Новая запись!</b>\n\n📅 {pretty_date(date)} в {time}\n👤 {name}\n📞 {phone}\n✈️ @{username}",
            parse_mode="HTML")
    except: pass
    try:
        await bot_instance.send_message(SCHEDULE_CHANNEL_ID,
            f"📅 <b>Новая запись</b>\n🗓 {pretty_date(date)} в {time}\n✅ Занято", parse_mode="HTML")
    except: pass

@router.callback_query(F.data == "cancel_booking")
async def cb_cancel(cb: CallbackQuery):
    booking = await get_user_booking(cb.from_user.id)
    if not booking:
        await cb.message.edit_text("📭 У вас нет активных записей.", reply_markup=back_kb()); return
    bid, date, time, name, phone = booking
    await cb.message.edit_text(
        f"❓ Отменить запись?\n\n📅 {pretty_date(date)} в {time}\n👤 {name}",
        reply_markup=cancel_confirm_kb(bid), parse_mode="HTML")

@router.callback_query(F.data.startswith("do_cancel_"))
async def cb_do_cancel(cb: CallbackQuery):
    booking_id = int(cb.data.replace("do_cancel_", ""))
    row = await delete_booking(booking_id)
    cancel_reminder(booking_id)
    await cb.message.edit_text("✅ Запись отменена. Надеемся увидеть вас снова! 💅", reply_markup=back_kb())
    try:
        await bot_instance.send_message(ADMIN_ID,
            f"❌ <b>Клиент отменил запись</b>\n📅 {row[0]} в {row[1]}\n@{cb.from_user.username or cb.from_user.id}",
            parse_mode="HTML")
    except: pass

# ─── АДМИН ────────────────────────────────────────────────────────────────────
def is_admin(uid): return uid == ADMIN_ID

@router.message(Command("admin"))
async def cmd_admin(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): await msg.answer("⛔️ Нет доступа."); return
    await state.clear()
    await msg.answer("🔧 <b>Админ-панель</b>\n\nВыберите действие:", reply_markup=admin_menu_kb(), parse_mode="HTML")

@router.callback_query(F.data == "admin_panel")
async def cb_admin_panel(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await state.clear()
    await cb.message.edit_text("🔧 <b>Админ-панель</b>", reply_markup=admin_menu_kb(), parse_mode="HTML")

@router.callback_query(F.data == "admin_add_day")
async def cb_add_day(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await state.set_state(AdminState.add_day)
    ex = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    await cb.message.edit_text(f"📅 Введите дату (<code>ГГГГ-ММ-ДД</code>)\nПример: <code>{ex}</code>",
                                reply_markup=admin_back_kb(), parse_mode="HTML")

@router.message(AdminState.add_day)
async def process_add_day(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    try: datetime.strptime(msg.text.strip(), "%Y-%m-%d")
    except: await msg.answer("❌ Неверный формат. Пример: 2026-03-15"); return
    default_times = ["10:00","11:00","12:00","13:00","14:00","15:00","16:00","17:00","18:00"]
    count = sum([1 for t in default_times if await add_slot(msg.text.strip(), t)])
    await state.clear()
    await msg.answer(f"✅ День <b>{msg.text.strip()}</b> добавлен!\n⏰ Слотов: {count} (10:00–18:00)",
                     reply_markup=admin_menu_kb(), parse_mode="HTML")

@router.callback_query(F.data == "admin_add_slot")
async def cb_add_slot_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await state.set_state(AdminState.add_slot_date)
    await cb.message.edit_text("⏰ Введите дату для добавления слота (<code>ГГГГ-ММ-ДД</code>):",
                                reply_markup=admin_back_kb(), parse_mode="HTML")

@router.message(AdminState.add_slot_date)
async def process_add_slot_date(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    try: datetime.strptime(msg.text.strip(), "%Y-%m-%d")
    except: await msg.answer("❌ Неверный формат:"); return
    await state.update_data(slot_date=msg.text.strip())
    await state.set_state(AdminState.add_slot_time)
    await msg.answer(f"📅 Дата: <b>{msg.text.strip()}</b>\n\nВведите время (<code>ЧЧ:ММ</code>):", parse_mode="HTML")

@router.message(AdminState.add_slot_time)
async def process_add_slot_time(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    try: datetime.strptime(msg.text.strip(), "%H:%M")
    except: await msg.answer("❌ Неверный формат. Пример: 15:30"); return
    data = await state.get_data()
    await add_slot(data['slot_date'], msg.text.strip())
    await state.clear()
    await msg.answer(f"✅ Слот <b>{data['slot_date']}</b> в <b>{msg.text.strip()}</b> добавлен!",
                     reply_markup=admin_menu_kb(), parse_mode="HTML")

@router.callback_query(F.data == "admin_del_slot")
async def cb_del_slot(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await state.set_state(AdminState.del_slot_date)
    await cb.message.edit_text("🗑 Введите дату для удаления слота (<code>ГГГГ-ММ-ДД</code>):",
                                reply_markup=admin_back_kb(), parse_mode="HTML")

@router.message(AdminState.del_slot_date)
async def process_del_slot_date(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    try: datetime.strptime(msg.text.strip(), "%Y-%m-%d")
    except: await msg.answer("❌ Неверный формат:"); return
    slots = await get_all_times(msg.text.strip())
    if not slots:
        await msg.answer("❌ Нет слотов на эту дату.", reply_markup=admin_menu_kb())
        await state.clear(); return
    text = f"📅 <b>{msg.text.strip()}</b>\n\n"
    for t, avail in slots:
        text += f"{'✅' if avail else '🔴'} {t}\n"
    text += "\nВведите время для удаления (<code>ЧЧ:ММ</code>):"
    await state.update_data(del_date=msg.text.strip())
    await state.set_state(AdminState.del_slot_time)
    await msg.answer(text, parse_mode="HTML")

@router.message(AdminState.del_slot_time)
async def process_del_slot_time(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    data = await state.get_data()
    await delete_slot(data['del_date'], msg.text.strip())
    await state.clear()
    await msg.answer(f"✅ Слот {msg.text.strip()} удалён с {data['del_date']}", reply_markup=admin_menu_kb())

@router.callback_query(F.data == "admin_close_day")
async def cb_close_day_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await state.set_state(AdminState.close_day)
    await cb.message.edit_text("🚫 Введите дату для закрытия (<code>ГГГГ-ММ-ДД</code>):",
                                reply_markup=admin_back_kb(), parse_mode="HTML")

@router.message(AdminState.close_day)
async def process_close_day(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    try: datetime.strptime(msg.text.strip(), "%Y-%m-%d")
    except: await msg.answer("❌ Неверный формат:"); return
    await close_day(msg.text.strip())
    await state.clear()
    await msg.answer(f"🚫 День <b>{msg.text.strip()}</b> закрыт.", reply_markup=admin_menu_kb(), parse_mode="HTML")

@router.callback_query(F.data == "admin_open_day")
async def cb_open_day_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await state.set_state(AdminState.open_day)
    await cb.message.edit_text("✅ Введите дату для открытия (<code>ГГГГ-ММ-ДД</code>):",
                                reply_markup=admin_back_kb(), parse_mode="HTML")

@router.message(AdminState.open_day)
async def process_open_day(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    try: datetime.strptime(msg.text.strip(), "%Y-%m-%d")
    except: await msg.answer("❌ Неверный формат:"); return
    await open_day(msg.text.strip())
    await state.clear()
    await msg.answer(f"✅ День <b>{msg.text.strip()}</b> открыт.", reply_markup=admin_menu_kb(), parse_mode="HTML")

@router.callback_query(F.data == "admin_schedule")
async def cb_schedule(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await state.set_state(AdminState.schedule)
    await cb.message.edit_text("📋 Введите дату для просмотра расписания (<code>ГГГГ-ММ-ДД</code>):",
                                reply_markup=admin_back_kb(), parse_mode="HTML")

@router.message(AdminState.schedule)
async def process_schedule(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    date = msg.text.strip()
    try: datetime.strptime(date, "%Y-%m-%d")
    except: await msg.answer("❌ Неверный формат:"); return
    bookings = await get_bookings_by_date(date)
    slots    = await get_all_times(date)
    text     = f"📋 <b>Расписание на {date}</b>\n\n"
    if not slots:
        text += "Нет слотов на эту дату."
    else:
        booked = {b[1]: b for b in bookings}
        for t, avail in slots:
            if t in booked:
                b = booked[t]
                text += f"🔴 {t} — <b>{b[2]}</b> | {b[3]}\n"
            elif not avail:
                text += f"🔴 {t} — занято\n"
            else:
                text += f"✅ {t} — свободно\n"
    await state.clear()
    await msg.answer(text, reply_markup=admin_menu_kb(), parse_mode="HTML")

@router.callback_query(F.data == "admin_cancel")
async def cb_admin_cancel(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await state.set_state(AdminState.cancel_date)
    await cb.message.edit_text("❌ Введите дату для отмены записи (<code>ГГГГ-ММ-ДД</code>):",
                                reply_markup=admin_back_kb(), parse_mode="HTML")

@router.message(AdminState.cancel_date)
async def process_cancel_date(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    date = msg.text.strip()
    try: datetime.strptime(date, "%Y-%m-%d")
    except: await msg.answer("❌ Неверный формат:"); return
    bookings = await get_bookings_by_date(date)
    if not bookings:
        await msg.answer(f"📭 Нет записей на {date}", reply_markup=admin_menu_kb())
        await state.clear(); return
    await state.clear()
    await msg.answer(f"❌ Выберите запись для отмены на <b>{date}</b>:",
                     reply_markup=admin_bookings_kb(bookings), parse_mode="HTML")

@router.callback_query(F.data.startswith("admin_do_cancel_"))
async def cb_admin_do_cancel(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    booking_id = int(cb.data.replace("admin_do_cancel_", ""))
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, date, time, name FROM bookings WHERE id=?", (booking_id,)) as c:
            row = await c.fetchone()
    await delete_booking(booking_id)
    cancel_reminder(booking_id)
    await cb.message.edit_text("✅ Запись отменена.", reply_markup=admin_menu_kb())
    if row:
        try:
            await bot_instance.send_message(row[0],
                f"❌ <b>Ваша запись отменена мастером</b>\n📅 {row[1]} в {row[2]}\n\nДля новой записи: /start",
                parse_mode="HTML")
        except: pass

@router.callback_query(F.data == "ignore")
async def cb_ignore(cb: CallbackQuery): await cb.answer()

# ─── НАПОМИНАНИЯ ──────────────────────────────────────────────────────────────
async def send_reminder(user_id, time, booking_id):
    try:
        await bot_instance.send_message(user_id,
            f"⏰ <b>Напоминание о записи!</b>\n\nНапоминаем, что вы записаны на маникюр завтра в <b>{time}</b>.\nЖдём вас! 💅",
            parse_mode="HTML")
        await mark_reminder_sent(booking_id)
    except Exception as e:
        logging.error(f"Reminder error: {e}")

def schedule_reminder(booking_id, user_id, date, time):
    try:
        visit_dt  = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        remind_dt = visit_dt - timedelta(hours=24)
        if remind_dt <= datetime.now(): return
        scheduler.add_job(send_reminder, "date", run_date=remind_dt,
                          args=[user_id, time, booking_id],
                          id=f"reminder_{booking_id}", replace_existing=True)
    except Exception as e:
        logging.error(f"Schedule error: {e}")

def cancel_reminder(booking_id):
    try:
        job = scheduler.get_job(f"reminder_{booking_id}")
        if job: scheduler.remove_job(f"reminder_{booking_id}")
    except: pass

async def restore_reminders():
    bookings = await get_future_bookings()
    for bid, user_id, name, date, time in bookings:
        schedule_reminder(bid, user_id, date, time)
    logging.info(f"Restored {len(bookings)} reminders")

# ─── ЗАПУСК ───────────────────────────────────────────────────────────────────
async def main():
    global bot_instance
    await init_db()
    bot_instance = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    scheduler.start()
    await restore_reminders()
    logging.info("🤖 Бот запущен!")
    await dp.start_polling(bot_instance, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
