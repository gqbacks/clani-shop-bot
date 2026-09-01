import asyncio, os
from datetime import datetime
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB = "clani.db"
if not TOKEN or not ADMIN_ID:
    raise RuntimeError("Set BOT_TOKEN and ADMIN_ID")

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

async def db_init():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY, balance REAL DEFAULT 0, spent REAL DEFAULT 0,
        purchases INTEGER DEFAULT 0, created TEXT NOT NULL)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL,
        title TEXT NOT NULL, description TEXT DEFAULT '', price REAL NOT NULL,
        photo TEXT DEFAULT '', available INTEGER DEFAULT 1)""")
        await db.commit()

async def ensure_user(uid):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT id FROM users WHERE id=?", (uid,))
        if not await cur.fetchone():
            await db.execute("INSERT INTO users(id,created) VALUES(?,?)",
                              (uid, datetime.utcnow().isoformat(timespec="seconds")))
            await db.commit()

def menu():
    b=InlineKeyboardBuilder()
    for t,d in [("🛒 Купить","shop"),("👤 Профиль","profile"),
                ("💳 Пополнить","topup"),("🏪 О магазине","about"),
                ("🆘 Помощь","help")]: b.button(text=t,callback_data=d)
    b.adjust(2,2,1); return b.as_markup()

def back():
    b=InlineKeyboardBuilder(); b.button(text="◀️ Назад",callback_data="home")
    return b.as_markup()

@dp.message(CommandStart())
async def start(m:Message):
    await ensure_user(m.from_user.id)
    await m.answer("<b>✨ Добро пожаловать в Clani Shop</b>\n\n"
                   "Магазин готовых игровых аккаунтов по приятным ценам.\n\n"
                   "<i>Выберите нужный раздел:</i>", reply_markup=menu())

@dp.callback_query(F.data=="home")
async def home(c:CallbackQuery):
    await c.message.edit_text("<b>✨ Clani Shop</b>\n\nЧто хотите сделать?",
                               reply_markup=menu()); await c.answer()

@dp.callback_query(F.data=="shop")
async def shop(c:CallbackQuery):
    async with aiosqlite.connect(DB) as db:
        rows=await (await db.execute(
            "SELECT category,COUNT(*) FROM products WHERE available=1 GROUP BY category")).fetchall()
    b=InlineKeyboardBuilder()
    for cat,n in rows: b.button(text=f"🎮 {cat} · {n}",callback_data=f"cat:{cat}")
    b.button(text="◀️ Назад",callback_data="home"); b.adjust(1)
    await c.message.edit_text("<b>🛍 Каталог</b>\n\nВыберите категорию:",reply_markup=b.as_markup())
    await c.answer()

@dp.callback_query(F.data.startswith("cat:"))
async def cat(c:CallbackQuery):
    cat=c.data[4:]
    async with aiosqlite.connect(DB) as db:
        rows=await (await db.execute(
            "SELECT id,title,price FROM products WHERE category=? AND available=1 ORDER BY id DESC",(cat,))).fetchall()
    b=InlineKeyboardBuilder()
    for pid,title,price in rows:
        b.button(text=f"🟢 {title} — {price:.0f} ₽",callback_data=f"prod:{pid}")
    b.button(text="◀️ К категориям",callback_data="shop"); b.adjust(1)
    await c.message.edit_text(f"<b>🎮 {cat}</b>\n\nВыберите товар:",reply_markup=b.as_markup())
    await c.answer()

@dp.callback_query(F.data.startswith("prod:"))
async def prod(c:CallbackQuery):
    pid=int(c.data[5:])
    async with aiosqlite.connect(DB) as db:
        row=await (await db.execute(
            "SELECT title,description,price,photo FROM products WHERE id=? AND available=1",(pid,))).fetchone()
    if not row: return await c.answer("Товар недоступен",show_alert=True)
    title,desc,price,photo=row
    text=f"<b>📦 {title}</b>\n\n{desc}\n\n<b>Цена:</b> {price:.0f} ₽"
    b=InlineKeyboardBuilder(); b.button(text="🛒 Купить",callback_data=f"buy:{pid}")
    b.button(text="◀️ Каталог",callback_data="shop"); b.adjust(1)
    if photo:
        try:
            await c.message.delete()
            await c.message.answer_photo(photo,caption=text,reply_markup=b.as_markup())
        except Exception: await c.message.edit_text(text,reply_markup=b.as_markup())
    else: await c.message.edit_text(text,reply_markup=b.as_markup())
    await c.answer()

@dp.callback_query(F.data.startswith("buy:"))
async def buy(c:CallbackQuery):
    pid=int(c.data[4:]); await ensure_user(c.from_user.id)
    async with aiosqlite.connect(DB) as db:
        row=await (await db.execute(
            "SELECT title,price FROM products WHERE id=? AND available=1",(pid,))).fetchone()
        bal=(await (await db.execute("SELECT balance FROM users WHERE id=?",(c.from_user.id,))).fetchone())[0]
        if not row: return await c.answer("Товар недоступен",show_alert=True)
        title,price=row
        if bal<price: return await c.answer("Недостаточно средств",show_alert=True)
        await db.execute("UPDATE users SET balance=balance-?,spent=spent+?,purchases=purchases+1 WHERE id=?",
                          (price,price,c.from_user.id)); await db.commit()
    await c.message.edit_text(f"<b>✅ Заказ оформлен</b>\n\n{title}\nСумма: {price:.0f} ₽\n\n"
                               "Администратор выдаст товар после проверки.",reply_markup=back())
    await bot.send_message(ADMIN_ID,f"🛒 Новый заказ\nID: <code>{c.from_user.id}</code>\n{title}\n{price:.0f} ₽")
    await c.answer()

@dp.callback_query(F.data=="profile")
async def profile(c:CallbackQuery):
    await ensure_user(c.from_user.id)
    async with aiosqlite.connect(DB) as db:
        r=await (await db.execute("SELECT balance,spent,purchases,created FROM users WHERE id=?",
                                   (c.from_user.id,))).fetchone()
    bal,spent,pur,created=r
    await c.message.edit_text(f"<b>👤 Профиль</b>\n\n🆔 ID: <code>{c.from_user.id}</code>\n"
                               f"💰 Баланс: <b>{bal:.0f} ₽</b>\n💸 Потрачено: <b>{spent:.0f} ₽</b>\n"
                               f"🛍 Покупок: <b>{pur}</b>\n📅 Регистрация: {created[:10]}",
                               reply_markup=back()); await c.answer()

@dp.callback_query(F.data=="about")
async def about(c:CallbackQuery):
    await c.message.edit_text("<b>🏪 О магазине Clani Shop</b>\n\n"
        "Clani Shop начинался как небольшой проект для игроков, которым хотелось "
        "быстро находить игровые товары без лишней суеты. Со временем мы "
        "сосредоточились на готовых аккаунтах и сделали магазин удобнее.\n\n"
        "За проектом уже стоит сообщество покупателей, которые возвращаются и "
        "оставляют отзывы. Мы продолжаем развивать каталог и сервис.",
        reply_markup=back()); await c.answer()

@dp.callback_query(F.data=="topup")
async def topup(c:CallbackQuery):
    await c.message.edit_text("<b>💳 Пополнение</b>\n\nСпособы оплаты подключим следующим этапом.\n"
                               "Для пополнения обратитесь в раздел «Помощь».",reply_markup=back()); await c.answer()

@dp.callback_query(F.data=="help")
async def help_(c:CallbackQuery):
    await c.message.edit_text("<b>🆘 Помощь</b>\n\nНапишите следующее сообщение — оно будет "
                               "передано администрации.\n\n<i>В ближайшее время вам ответит администратор.</i>",
                               reply_markup=back()); await c.answer()

@dp.message()
async def support(m:Message):
    if m.from_user.id==ADMIN_ID: return
    await ensure_user(m.from_user.id)
    await bot.send_message(ADMIN_ID,f"📩 Пользователь <code>{m.from_user.id}</code> "
                                    f"(@{m.from_user.username or 'без username'}):\n\n{m.text or '[медиа]'}")
    await m.answer("✅ Сообщение отправлено администрации.")

async def main():
    await db_init()
    await dp.start_polling(bot)

if __name__=="__main__": asyncio.run(main())
