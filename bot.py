import asyncio
import logging
import re
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
from cipher import load_cipher
from database import Database
from ocr import crop_code, extract_code

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=Config.BOT_TOKEN,
          default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
db = Database(Config.DB_FILE)
CIPHER = load_cipher()

admin_router = Router()
safe_router = Router()
misc_router = Router()

dp.include_router(admin_router)
dp.include_router(safe_router)
dp.include_router(misc_router)

GAME_MARKER = "Взлом сейфа начат!"
USERNAME_RE = re.compile(r"[a-zA-Z0-9_]{4,}")


# ===== DEBUG =============================================================
@dp.message.outer_middleware()
async def debug_in(handler, event: Message, data):
    logger.info(
        "IN | chat=%s type=%s | from=%s | text=%r | caption=%r",
        event.chat.id, event.chat.type,
        event.from_user.id if event.from_user else None,
        (event.text or "")[:60],
        (event.caption or "")[:80],
    )
    return await handler(event, data)


# ==============================================================================


# ================= АДМИНКА (только ЛС) =================
class AdminFSM(StatesGroup):
    waiting_id = State()


def admin_kb():
    b = InlineKeyboardBuilder()
    b.button(text="➕ Добавить пользователя", callback_data="admin:add")
    b.button(text="➖ Удалить пользователя", callback_data="admin:remove")
    b.button(text="📋 Список пользователей", callback_data="admin:list")
    b.adjust(1)
    return b.as_markup()


async def _fetch_username(user_id: int) -> str | None:
    try:
        chat = await bot.get_chat(user_id)
        return chat.username
    except Exception:
        return None


@admin_router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.chat.type != "private":
        await message.answer("🛠 Админ-панель доступна только в личных сообщениях.")
        return
    if message.from_user.id != Config.ADMIN_ID:
        await message.answer("❌ У тебя нет доступа к админ-панели.")
        return
    await message.answer("🛠 <b>Админ-панель</b>", reply_markup=admin_kb())


@admin_router.callback_query(F.data == "admin:add")
async def cb_add(cb: CallbackQuery, state: FSMContext):
    if cb.message.chat.type != "private":
        return await cb.answer("❌ Админ-панель — только в личных сообщениях", show_alert=True)
    if cb.from_user.id != Config.ADMIN_ID:
        return await cb.answer("❌ Нет доступа", show_alert=True)
    await state.set_state(AdminFSM.waiting_id)
    await state.update_data(action="add")
    await cb.message.answer("➕ Введи Telegram ID пользователя (числом).\n/cancel — отмена.")
    await cb.answer()


@admin_router.callback_query(F.data == "admin:remove")
async def cb_remove(cb: CallbackQuery, state: FSMContext):
    if cb.message.chat.type != "private":
        return await cb.answer("❌ Админ-панель — только в личных сообщениях", show_alert=True)
    if cb.from_user.id != Config.ADMIN_ID:
        return await cb.answer("❌ Нет доступа", show_alert=True)
    await state.set_state(AdminFSM.waiting_id)
    await state.update_data(action="remove")
    await cb.message.answer("➖ Введи Telegram ID пользователя для удаления.\n/cancel — отмена.")
    await cb.answer()


@admin_router.callback_query(F.data == "admin:list")
async def cb_list(cb: CallbackQuery):
    if cb.message.chat.type != "private":
        return await cb.answer("❌ Админ-панель — только в личных сообщениях", show_alert=True)
    users = db.get_all_users()
    if users:
        lines = [
            f"• <code>{uid}</code> @{name}" if name else f"• <code>{uid}</code> (ник не известен)"
            for uid, name in users
        ]
        body = "\n".join(lines)
    else:
        body = "(пусто)"
    await cb.message.answer(f"📋 <b>Разрешённые пользователи:</b>\n{body}")
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
    if data["action"] == "add":
        ok, msg = db.add_user(uid, await _fetch_username(uid))
    else:
        ok, msg = db.remove_user(uid)
    await message.answer(msg, reply_markup=admin_kb())
    await state.clear()


# ================= СЕЙФ (только группы) =================
async def _extract_player(message: Message) -> tuple[int, str | None] | None:
    """Достаёт ID (и ник) игрока из ссылки в начале сообщения Celestiana."""
    raw = message.caption or message.text or ""
    entities = list(message.caption_entities or []) + list(message.entities or [])
    username = None

    for ent in entities:
        if ent.type == "text_mention" and ent.user is not None:
            return ent.user.id, ent.user.username

        if ent.type == "text_link" and ent.url:
            m = re.search(r"tg://user\?id=(\d+)", ent.url)
            if m:
                return int(m.group(1)), None
            m = re.match(r"^(?:https?://)?t\.me/([a-zA-Z0-9_]{4,})/?$", ent.url)
            if m:
                username = m.group(1)
                continue
            link_text = raw[ent.offset:ent.offset + ent.length].strip().lstrip("@")
            if USERNAME_RE.fullmatch(link_text):
                username = link_text

        if ent.type == "mention" and username is None:
            username = raw[ent.offset:ent.offset + ent.length].lstrip("@")

    if username is None:
        m = re.match(r"\s*@?([a-zA-Z0-9_]{4,})\s*,", raw)
        if m:
            username = m.group(1)

    if username:
        try:
            chat = await bot.get_chat(username)
            return chat.id, chat.username
        except Exception:
            logger.warning("Не удалось зарезолвить ник @%s в ID", username)
    return None


@safe_router.message(F.photo)
async def on_photo(message: Message):
    fo = message.forward_origin
    fwd_id = fo.sender_user.id if (fo is not None and fo.type == "user" and fo.sender_user) else None
    logger.info("PHOTO | from=%s | fwd=%s | chat_type=%s | caption=%r",
                message.from_user.id, fwd_id, message.chat.type, (message.caption or "")[:80])

    # в личке с ботом НЕ расшифровываем никогда
    if message.chat.type == "private":
        logger.info("skip: private")
        return

    # принимаем либо напрямую от Celestiana, либо ПЕРЕСЛАННОЕ от неё сообщение
    from_celestiana = message.from_user.id == Config.CELESTIANA_ID
    fwd_celestiana = fwd_id == Config.CELESTIANA_ID
    if not (from_celestiana or fwd_celestiana):
        logger.info("skip: не Celestiana (from=%s, fwd=%s)", message.from_user.id, fwd_id)
        return

    # анонс и фото — одно сообщение: маркер и ссылка на игрока в подписи
    if GAME_MARKER not in (message.caption or ""):
        logger.info("skip: маркер не найден в подписи")
        return

    player = await _extract_player(message)
    if player is None:
        logger.warning("Не удалось извлечь игрока из сообщения %s", message.message_id)
        return
    player_id, player_username = player

    # проверка допуска: именно игрок из ссылки, а не отправитель сообщения
    if not db.is_authorized(player_id):
        logger.info("Игрок %s (@%s) без допуска — сейф пропущен",
                    player_id, player_username)
        return
    db.update_username(player_id, player_username)

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
        text = (f"⚠️ Распознано с ошибкой: <code>{letters or '—'}</code>\n"
                "Проверь картинку вручную.")

    await message.reply(text)


# ================= ПРОЧЕЕ =================
@misc_router.message(Command("myid"))
async def cmd_myid(message: Message):
    await message.answer(f"🆔 Твой ID: <code>{message.from_user.id}</code>")


@misc_router.message(CommandStart())
async def cmd_start(message: Message):
    if db.is_authorized(message.from_user.id):
        db.update_username(message.from_user.id, message.from_user.username)
        await message.answer(
            "👋 Доступ есть!\n\n"
            "Я работаю в группах, где есть Celestiana:\n"
            "1. Отправь <code>.аз сейф</code> в группе\n"
            "2. Селестина пришлёт картинку с кодом\n"
            "3. Перешли эту картинку(вместе с подписью с твоим ником) в тот же чат\n"
            "4. Я отвечу расшифрованным кодом — скопируй и отправь ей\n\n"
            "В личных сообщениях я ничего не расшифровываю.\n")
    else:
        await message.answer(
            f"❌ <b>Нет доступа.</b>\nТвой ID: <code>{message.from_user.id}</code>\n"
            "Попроси админа добавить тебя через /admin.")


@misc_router.message(Command("help"))
async def cmd_help(message: Message):
    await cmd_start(message)


async def main():
    db.add_user(Config.ADMIN_ID, await _fetch_username(Config.ADMIN_ID))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
