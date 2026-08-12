import logging
import time
from io import BytesIO

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from PIL import Image

from config import Config
from database import Database
from cipher import load_cipher
from ocr import crop_code, extract_code

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=Config.BOT_TOKEN,
          default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
db = Database(Config.DB_FILE)
CIPHER = load_cipher()

admin_router, safe_router, misc_router = Router(), Router(), Router()
WAITING: dict[tuple[int, int], float] = {}   # (chat_id, user_id) -> время нажатия «Готов»


# ================= АДМИНКА =================
class AdminFSM(StatesGroup):
    waiting_id = State()


def admin_kb():
    b = InlineKeyboardBuilder()
    b.button(text="➕ Добавить пользователя", callback_data="admin:add")
    b.button(text="➖ Удалить пользователя", callback_data="admin:remove")
    b.button(text="📋 Список пользователей", callback_data="admin:list")
    b.adjust(1)
    return b.as_markup()


@admin_router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != Config.ADMIN_ID:
        await message.answer("❌ У тебя нет доступа к админ-панели.")
        return
    await message.answer("🛠 <b>Админ-панель</b>", reply_markup=admin_kb())


@admin_router.callback_query(F.data == "admin:add")
async def cb_add(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != Config.ADMIN_ID:
        return await cb.answer("❌ Нет доступа", show_alert=True)
    await state.set_state(AdminFSM.waiting_id)
    await state.update_data(action="add")
    await cb.message.answer("➕ Введи Telegram ID пользователя (числом).\n/cancel — отмена.")
    await cb.answer()


@admin_router.callback_query(F.data == "admin:remove")
async def cb_remove(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != Config.ADMIN_ID:
        return await cb.answer("❌ Нет доступа", show_alert=True)
    await state.set_state(AdminFSM.waiting_id)
    await state.update_data(action="remove")
    await cb.message.answer("➖ Введи Telegram ID пользователя для удаления.\n/cancel — отмена.")
    await cb.answer()


@admin_router.callback_query(F.data == "admin:list")
async def cb_list(cb: CallbackQuery):
    users = db.get_all_users()
    text = "📋 <b>Разрешённые пользователи:</b>\n" + (
        "\n".join(f"• <code>{u}</code>" for u in users) if users else "(пусто)")
    await cb.message.answer(text)
    await cb.answer()


@admin_router.message(AdminFSM.waiting_id)
async def admin_id_input(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        return await message.answer("❌ Отменено.", reply_markup=admin_kb())
    if not text.isdigit():
        return await message.answer("⚠️ ID — это число. Попробуй ещё раз.")
    uid = int(text)
    data = await state.get_data()
    ok, msg = (db.add_user(uid) if data["action"] == "add" else db.remove_user(uid))
    await message.answer(msg, reply_markup=admin_kb())
    await state.clear()


# ================= СЕЙФ =================
@safe_router.message(F.text.func(lambda t: t.strip().lower().startswith(".аз сейф")))
async def on_safe_command(message: Message):
    if not db.is_authorized(message.from_user.id):
        if message.chat.type == "private":
            await message.answer(
                f"❌ <b>Нет доступа.</b>\nТвой ID: <code>{message.from_user.id}</code>\n"
                "Попроси админа добавить тебя.")
        return
    b = InlineKeyboardBuilder()
    b.button(text="✅ Готов", callback_data="safe_ready")
    await message.answer(
        "🔐 Готов взломать сейф Celestiana.\n\n"
        "Жми <b>«Готов»</b>, затем отправь Селестине <code>.аз сейф</code> и:\n"
        "• перешли мне картинку с кодом (если играешь в личке),\n"
        "• или просто жди (если я сижу в том же чате и вижу её сам).",
        reply_markup=b.as_markup())


@safe_router.callback_query(F.data == "safe_ready")
async def on_ready(cb: CallbackQuery):
    if not db.is_authorized(cb.from_user.id):
        return await cb.answer("❌ Нет доступа", show_alert=True)
    WAITING[(cb.message.chat.id, cb.from_user.id)] = time.time()
    await cb.answer("⏳ Жду картинку с кодом!")


@safe_router.message(F.photo)
async def on_photo(message: Message):
    sender = message.from_user.id
    is_private = message.chat.type == "private"

    fwd_celestiana = False
    fo = message.forward_origin
    if fo is not None and fo.type == "user" and fo.sender_user.id == Config.CELESTIANA_ID:
        fwd_celestiana = True
    direct_celestiana = sender == Config.CELESTIANA_ID

    now = time.time()
    if is_private:
        if not db.is_authorized(sender):
            return
        targets = [(message.chat.id, sender)]
    else:
        # групповой режим: видим сообщения Celestiana напрямую
        if not (direct_celestiana or fwd_celestiana):
            return
        targets = [k for k, t in list(WAITING.items())
                   if k[0] == message.chat.id and now - t <= Config.WAIT_TIMEOUT]
        if not targets:
            return

    photo = message.photo[-1]
    buf = BytesIO()
    try:
        file = await bot.get_file(photo.file_id)
        await bot.download_file(file.file_path, destination=buf)
        buf.seek(0)
        img = Image.open(buf).convert("RGB")
        letters = extract_code(crop_code(img))
    except Exception:
        logger.exception("OCR failed")
        letters = ""

    parts, bad = [], []
    for ch in letters:
        if ch in CIPHER:
            parts.append(CIPHER[ch])
        else:
            bad.append(ch)
    digits = "".join(parts)

    if letters and not bad and 4 <= len(letters) <= 5:
        text = (f"🔓 Распознано: <code>{letters}</code>\n"
                f"🔑 Код: <code>{digits}</code>\n\n"
                f"Отправь Селестине:\n<code>.аз сейф {digits}</code>")
    else:
        text = f"⚠️ Распознано с ошибкой: <code>{letters or '—'}</code>\nПроверь картинку вручную."

    if is_private:
        await message.answer(text)
    else:
        await message.answer(text)  # одно сообщение в чат на всех ждущих
    for k in targets:
        WAITING.pop(k, None)


# ================= ПРОЧЕЕ =================
@misc_router.message(Command("cancel"))
async def cmd_cancel(message: Message):
    WAITING.pop((message.chat.id, message.from_user.id), None)
    await message.answer("❌ Ожидание сейфа отменено.")


@misc_router.message(Command("myid"))
async def cmd_myid(message: Message):
    await message.answer(f"🆔 Твой ID: <code>{message.from_user.id}</code>")


@misc_router.message(CommandStart())
async def cmd_start(message: Message):
    if db.is_authorized(message.from_user.id):
        await message.answer(
            "👋 Доступ есть!\n\n"
            "Как пользоваться:\n"
            "1. Напиши мне <code>.аз сейф</code>\n"
            "2. Нажми «Готов»\n"
            "3. Отправь Селестине <code>.аз сейф</code>\n"
            "4. Перешли мне картинку с кодом (или я увижу сам в общем чате)\n"
            "5. Скопируй готовый код и вставь Селестине\n\n"
            "Админ: <code>/admin</code>")
    else:
        await message.answer(
            f"❌ <b>Нет доступа.</b>\nТвой ID: <code>{message.from_user.id}</code>\n"
            "Попроси админа добавить тебя через /admin.")


@misc_router.message(Command("help"))
async def cmd_help(message: Message):
    await cmd_start(message)


async def main():
    db.add_user(Config.ADMIN_ID)  # админ всегда в списке
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
