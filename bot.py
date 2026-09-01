import asyncio
import os
from datetime import datetime

import aiosqlite
from aiohttp import web
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB = "clani.db"

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not configured")
if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID is not configured")

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


class AddProduct(StatesGroup):
    category = State()
    title = State()
    description = State()
    price = State()
    photo = State()


class AdminReply(StatesGroup):
    user_id = State()


class Broadcast(StatesGroup):
    message = State()


class EditSetting(StatesGroup):
    value = State()


def admin(uid: int) -> bool:
    return uid == ADMIN_ID


async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 0,
                spent REAL DEFAULT 0,
                purchases INTEGER DEFAULT 0,
                created TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                price REAL NOT NULL,
                photo TEXT DEFAULT '',
                available INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        defaults = {
            "shop_name": "Clani Shop",
            "welcome": "✨ Добро пожаловать в Clani Shop!\n\nЗдесь вы найдёте готовые игровые аккаунты по приятным ценам.",
            "about": "Clani Shop начинался как небольшой проект для игроков, которым хотелось быстро и удобно покупать игровые товары. Со временем мы сосредоточились на готовых аккаунтах и сделали каталог удобнее.\n\nСпасибо нашим покупателям за доверие и отзывы. Мы продолжаем развивать магазин и сервис.",
            "payments": "💳 Способы пополнения:\n\nСвяжитесь с администратором через раздел «Помощь» и укажите сумму пополнения."
        }
        for key, value in defaults.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
                (key, value)
            )
        await db.commit()


async def get_setting(key):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row[0] if row else ""


async def set_setting(key, value):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE settings SET value=? WHERE key=?", (value, key))
        await db.commit()


async def ensure_user(uid):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT id FROM users WHERE id=?", (uid,))
        if not await cur.fetchone():
            await db.execute(
                "INSERT INTO users(id,created) VALUES(?,?)",
                (uid, datetime.utcnow().isoformat(timespec="seconds"))
            )
            await db.commit()


def home_keyboard(uid):
    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Купить", callback_data="shop")
    kb.button(text="👤 Профиль", callback_data="profile")
    kb.button(text="💳 Пополнить", callback_data="topup")
    kb.button(text="🏪 О магазине", callback_data="about")
    kb.button(text="🆘 Помощь", callback_data="help")
    if admin(uid):
        kb.button(text="⚙️ Админ-панель", callback_data="admin")
    kb.adjust(2, 2, 1, 1)
    return kb.as_markup()


def back_home():
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Главное меню", callback_data="home")
    return kb.as_markup()


def admin_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить товар", callback_data="a_add")
    kb.button(text="📦 Товары", callback_data="a_products")
    kb.button(text="📊 Статистика", callback_data="a_stats")
    kb.button(text="📢 Рассылка", callback_data="a_broadcast")
    kb.button(text="✏️ Настройки", callback_data="a_settings")
    kb.button(text="◀️ Главное меню", callback_data="home")
    kb.adjust(2, 2, 1, 1)
    return kb.as_markup()


@dp.message(CommandStart())
async def start(message: Message):
    await ensure_user(message.from_user.id)
    name = await get_setting("shop_name")
    welcome = await get_setting("welcome")
    await message.answer(
        f"<b>✨ {name}</b>\n\n{welcome}\n\n<i>Выберите нужный раздел:</i>",
        reply_markup=home_keyboard(message.from_user.id)
    )


@dp.message(Command("admin"))
async def admin_command(message: Message):
    if admin(message.from_user.id):
        await message.answer("⚙️ <b>Админ-панель</b>", reply_markup=admin_keyboard())


@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery):
    name = await get_setting("shop_name")
    await call.message.edit_text(
        f"<b>✨ {name}</b>\n\nЧто хотите сделать?",
        reply_markup=home_keyboard(call.from_user.id)
    )
    await call.answer()


@dp.callback_query(F.data == "shop")
async def shop(call: CallbackQuery):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "SELECT category, COUNT(*) FROM products WHERE available=1 GROUP BY category ORDER BY category"
        )
        categories = await cur.fetchall()

    kb = InlineKeyboardBuilder()
    for category, count in categories:
        kb.button(text=f"🎮 {category} · {count}", callback_data=f"cat:{category}")
    kb.button(text="◀️ Назад", callback_data="home")
    kb.adjust(1)

    text = "<b>🛍 Каталог</b>\n\n"
    text += "Выберите категорию:" if categories else "Каталог пока пуст."
    await call.message.edit_text(text, reply_markup=kb.as_markup())
    await call.answer()


@dp.callback_query(F.data.startswith("cat:"))
async def category(call: CallbackQuery):
    category_name = call.data[4:]
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "SELECT id,title,price FROM products WHERE category=? AND available=1 ORDER BY id DESC",
            (category_name,)
        )
        products = await cur.fetchall()

    kb = InlineKeyboardBuilder()
    for pid, title, price in products:
        kb.button(text=f"📦 {title} — {price:.0f} ₽", callback_data=f"product:{pid}")
    kb.button(text="◀️ Категории", callback_data="shop")
    kb.adjust(1)

    await call.message.edit_text(
        f"<b>🎮 {category_name}</b>\n\nВыберите товар:",
        reply_markup=kb.as_markup()
    )
    await call.answer()


@dp.callback_query(F.data.startswith("product:"))
async def product(call: CallbackQuery):
    pid = int(call.data[8:])
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "SELECT title,description,price,photo FROM products WHERE id=? AND available=1",
            (pid,)
        )
        row = await cur.fetchone()

    if not row:
        await call.answer("Товар недоступен", show_alert=True)
        return

    title, description, price, photo = row
    text = (
        f"<b>📦 {title}</b>\n\n"
        f"{description or 'Описание не указано.'}\n\n"
        f"💰 <b>{price:.0f} ₽</b>\n"
        f"🔒 Аккаунт не фишинг."
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="🛒 Купить", callback_data=f"buy:{pid}")
    kb.button(text="◀️ Каталог", callback_data="shop")
    kb.adjust(1)

    if photo:
        try:
            await call.message.delete()
            await call.message.answer_photo(photo, caption=text, reply_markup=kb.as_markup())
        except Exception:
            await call.message.answer(text, reply_markup=kb.as_markup())
    else:
        await call.message.edit_text(text, reply_markup=kb.as_markup())
    await call.answer()


@dp.callback_query(F.data.startswith("buy:"))
async def buy(call: CallbackQuery):
    pid = int(call.data[4:])
    await ensure_user(call.from_user.id)

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "SELECT title,price FROM products WHERE id=? AND available=1",
            (pid,)
        )
        product_row = await cur.fetchone()
        if not product_row:
            await call.answer("Товар недоступен", show_alert=True)
            return

        title, price = product_row
        cur = await db.execute("SELECT balance FROM users WHERE id=?", (call.from_user.id,))
        balance = (await cur.fetchone())[0]

        if balance < price:
            await call.answer("Недостаточно средств. Пополните баланс.", show_alert=True)
            return

        await db.execute(
            "UPDATE users SET balance=balance-?, spent=spent+?, purchases=purchases+1 WHERE id=?",
            (price, price, call.from_user.id)
        )
        await db.commit()

    await call.message.edit_text(
        f"<b>✅ Заказ оформлен</b>\n\n"
        f"📦 {title}\n"
        f"💰 {price:.0f} ₽\n\n"
        f"Администратор свяжется с вами для выдачи товара.",
        reply_markup=back_home()
    )
    await bot.send_message(
        ADMIN_ID,
        f"🛒 <b>Новый заказ</b>\n\n"
        f"👤 ID: <code>{call.from_user.id}</code>\n"
        f"📦 {title}\n"
        f"💰 {price:.0f} ₽"
    )
    await call.answer()


@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):
    await ensure_user(call.from_user.id)
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "SELECT balance,spent,purchases,created FROM users WHERE id=?",
            (call.from_user.id,)
        )
        balance, spent, purchases, created = await cur.fetchone()

    await call.message.edit_text(
        f"<b>👤 Профиль</b>\n\n"
        f"🆔 ID: <code>{call.from_user.id}</code>\n"
        f"💰 Баланс: <b>{balance:.0f} ₽</b>\n"
        f"💸 Потрачено: <b>{spent:.0f} ₽</b>\n"
        f"🛍 Покупок: <b>{purchases}</b>\n"
        f"📅 Регистрация: {created[:10]}",
        reply_markup=back_home()
    )
    await call.answer()


@dp.callback_query(F.data == "topup")
async def topup(call: CallbackQuery):
    await call.message.edit_text(
        f"<b>💳 Пополнение баланса</b>\n\n{await get_setting('payments')}",
        reply_markup=back_home()
    )
    await call.answer()


@dp.callback_query(F.data == "about")
async def about(call: CallbackQuery):
    await call.message.edit_text(
        f"<b>🏪 {await get_setting('shop_name')}</b>\n\n{await get_setting('about')}",
        reply_markup=back_home()
    )
    await call.answer()


@dp.callback_query(F.data == "help")
async def help_menu(call: CallbackQuery):
    await call.message.edit_text(
        "<b>🆘 Помощь</b>\n\n"
        "Напишите следующим сообщением ваш вопрос.\n"
        "Он будет передан администрации.\n\n"
        "<i>В ближайшее время вам ответит администратор.</i>",
        reply_markup=back_home()
    )
    await call.answer()


# ---------------- ADMIN ----------------

@dp.callback_query(F.data == "admin")
async def admin_panel(call: CallbackQuery):
    if not admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await call.message.edit_text(
        "⚙️ <b>Админ-панель Clani Shop</b>",
        reply_markup=admin_keyboard()
    )
    await call.answer()


@dp.callback_query(F.data == "a_add")
async def add_start(call: CallbackQuery, state: FSMContext):
    if not admin(call.from_user.id):
        return
    await state.set_state(AddProduct.category)
    await call.message.edit_text(
        "➕ <b>Добавление товара</b>\n\n"
        "Введите категорию.\n"
        "Например: <code>5000 Robux</code>"
    )
    await call.answer()


@dp.message(AddProduct.category)
async def add_category(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        return
    await state.update_data(category=message.text.strip())
    await state.set_state(AddProduct.title)
    await message.answer("Введите название товара:")


@dp.message(AddProduct.title)
async def add_title(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        return
    await state.update_data(title=message.text.strip())
    await state.set_state(AddProduct.description)
    await message.answer("Введите описание товара:")


@dp.message(AddProduct.description)
async def add_description(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        return
    await state.update_data(description=message.text.strip())
    await state.set_state(AddProduct.price)
    await message.answer("Введите цену в рублях, например <code>499</code>:")


@dp.message(AddProduct.price)
async def add_price(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        return
    try:
        price = float(message.text.replace(",", "."))
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите положительное число, например <code>499</code>.")
        return

    await state.update_data(price=price)
    await state.set_state(AddProduct.photo)
    await message.answer("Отправьте фото товара или напишите <code>нет</code>.")


@dp.message(AddProduct.photo)
async def add_photo(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        return

    data = await state.get_data()
    photo = message.photo[-1].file_id if message.photo else ""

    async with aiosqlite.connect(DB) as db:
        await db.execute(
            """INSERT INTO products(category,title,description,price,photo)
               VALUES(?,?,?,?,?)""",
            (
                data["category"],
                data["title"],
                data["description"],
                data["price"],
                photo
            )
        )
        await db.commit()

    await state.clear()
    await message.answer("✅ Товар добавлен в каталог.", reply_markup=admin_keyboard())


@dp.callback_query(F.data == "a_products")
async def products_admin(call: CallbackQuery):
    if not admin(call.from_user.id):
        return

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "SELECT id,title,price,available FROM products ORDER BY id DESC"
        )
        rows = await cur.fetchall()

    kb = InlineKeyboardBuilder()
    for pid, title, price, available in rows:
        status = "🟢" if available else "🔴"
        kb.button(
            text=f"{status} {title} · {price:.0f} ₽",
            callback_data=f"toggle:{pid}"
        )
    kb.button(text="◀️ Админка", callback_data="admin")
    kb.adjust(1)

    await call.message.edit_text(
        "<b>📦 Товары</b>\n\n"
        "Нажмите товар, чтобы включить/выключить его в каталоге."
        if rows else
        "<b>📦 Товары</b>\n\nПока товаров нет.",
        reply_markup=kb.as_markup()
    )
    await call.answer()


@dp.callback_query(F.data.startswith("toggle:"))
async def toggle_product(call: CallbackQuery):
    if not admin(call.from_user.id):
        return

    pid = int(call.data[7:])
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE products SET available=CASE available WHEN 1 THEN 0 ELSE 1 END WHERE id=?",
            (pid,)
        )
        await db.commit()

    await call.answer("Статус изменён")
    await products_admin(call)


@dp.callback_query(F.data == "a_stats")
async def statistics(call: CallbackQuery):
    if not admin(call.from_user.id):
        return

    async with aiosqlite.connect(DB) as db:
        users = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        products = (await (await db.execute("SELECT COUNT(*) FROM products")).fetchone())[0]
        spent = (await (await db.execute(
            "SELECT COALESCE(SUM(spent),0) FROM users"
        )).fetchone())[0]

    await call.message.edit_text(
        f"<b>📊 Статистика</b>\n\n"
        f"👥 Пользователей: <b>{users}</b>\n"
        f"📦 Товаров: <b>{products}</b>\n"
        f"💰 Потрачено: <b>{spent:.0f} ₽</b>",
        reply_markup=admin_keyboard()
    )
    await call.answer()


@dp.callback_query(F.data == "a_settings")
async def settings(call: CallbackQuery):
    if not admin(call.from_user.id):
        return

    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Название", callback_data="set:shop_name")
    kb.button(text="✏️ Приветствие", callback_data="set:welcome")
    kb.button(text="✏️ О магазине", callback_data="set:about")
    kb.button(text="✏️ Пополнение", callback_data="set:payments")
    kb.button(text="◀️ Админка", callback_data="admin")
    kb.adjust(1)

    await call.message.edit_text(
        "<b>⚙️ Настройки</b>\n\n"
        "Все эти тексты можно менять прямо в Telegram.",
        reply_markup=kb.as_markup()
    )
    await call.answer()


@dp.callback_query(F.data.startswith("set:"))
async def setting_start(call: CallbackQuery, state: FSMContext):
    if not admin(call.from_user.id):
        return

    key = call.data[4:]
    await state.update_data(key=key)
    await state.set_state(EditSetting.value)

    await call.message.edit_text(
        f"✏️ Отправьте новое значение для <code>{key}</code>.\n\n"
        "Для отмены отправьте /admin."
    )
    await call.answer()


@dp.message(EditSetting.value)
async def setting_save(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        return

    data = await state.get_data()
    await set_setting(data["key"], message.text or "")
    await state.clear()
    await message.answer("✅ Настройка сохранена.", reply_markup=admin_keyboard())


@dp.callback_query(F.data == "a_broadcast")
async def broadcast_start(call: CallbackQuery, state: FSMContext):
    if not admin(call.from_user.id):
        return

    await state.set_state(Broadcast.message)
    await call.message.edit_text(
        "📢 <b>Рассылка</b>\n\n"
        "Отправьте сообщение, которое нужно разослать всем пользователям."
    )
    await call.answer()


@dp.message(Broadcast.message)
async def broadcast_send(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT id FROM users")
        users = await cur.fetchall()

    sent = 0
    for (uid,) in users:
        try:
            await message.copy_to(uid)
            sent += 1
        except Exception:
            pass

    await state.clear()
    await message.answer(
        f"✅ Рассылка завершена.\nДоставлено: <b>{sent}</b>",
        reply_markup=admin_keyboard()
    )


# ---------------- SUPPORT ----------------

@dp.message()
async def support_message(message: Message):
    if admin(message.from_user.id):
        return

    await ensure_user(message.from_user.id)

    text = message.text or "Пользователь отправил медиа/файл."
    kb = InlineKeyboardBuilder()
    kb.button(text="💬 Ответить", callback_data=f"reply:{message.from_user.id}")

    await bot.send_message(
        ADMIN_ID,
        f"📩 <b>Новое сообщение</b>\n\n"
        f"👤 {message.from_user.full_name}\n"
        f"🆔 <code>{message.from_user.id}</code>\n\n"
        f"{text}",
        reply_markup=kb.as_markup()
    )

    await message.answer(
        "✅ Сообщение отправлено администрации.\n\n"
        "В ближайшее время вам ответит администратор."
    )


@dp.callback_query(F.data.startswith("reply:"))
async def reply_start(call: CallbackQuery, state: FSMContext):
    if not admin(call.from_user.id):
        return

    uid = int(call.data[6:])
    await state.update_data(user_id=uid)
    await state.set_state(AdminReply.user_id)
    await call.message.answer(
        f"💬 Напишите сообщение для пользователя <code>{uid}</code>."
    )
    await call.answer()


@dp.message(AdminReply.user_id)
async def reply_send(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        return

    data = await state.get_data()
    uid = data["user_id"]

    try:
        await message.copy_to(
            uid,
            caption="💬 <b>Сообщение от администрации Clani Shop</b>"
            if message.caption else None
        )
        await message.answer("✅ Ответ отправлен.", reply_markup=admin_keyboard())
    except Exception:
        await message.answer("❌ Не удалось доставить сообщение.")

    await state.clear()


async def health(request):
    return web.Response(text="Clani Shop is running!")

async def start_web():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    port = int(os.getenv("PORT", "10000"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Web server started on port {port}")

async def main():
    await init_db()
    await start_web()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
