import os
import re
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from telegram.error import NetworkError, TimedOut, RetryAfter

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_USERS = [
    int(u.strip()) for u in os.getenv("ALLOWED_USERS", "").split(",") if u.strip()
]
VAULT_PATH = "/app/vault"
ATTACHMENTS_PATH = os.path.join(VAULT_PATH, "Attachments")
os.makedirs(ATTACHMENTS_PATH, exist_ok=True)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")


def run_health_server():
    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    server.serve_forever()


def is_authorized(update: Update) -> bool:
    if not ALLOWED_USERS:
        return True
    return update.effective_user.id in ALLOWED_USERS


def get_forward_info(msg):
    if hasattr(msg, "forward_from") and msg.forward_from:
        user = msg.forward_from
        name = user.full_name or user.username or "Unknown"
        link = f"https://t.me/{user.username}" if user.username else None
        return {"name": name, "link": link}
    if hasattr(msg, "forward_from_chat") and msg.forward_from_chat:
        chat = msg.forward_from_chat
        name = chat.title or chat.full_name or "Unknown Chat"
        link = f"https://t.me/{chat.username}" if chat.username else None
        return {"name": name, "link": link}
    return None


def sync_filesystem(path):
    """Принудительная синхронизация файловой системы для указанного пути"""
    try:
        # Обновляем время модификации каталога
        os.utime(path, None)
        logger.debug(f"Обновлено время каталога: {path}")
    except Exception as e:
        logger.warning(f"Не удалось обновить время каталога {path}: {e}")

    try:
        # Пытаемся синхронизировать каталог (если поддерживается)
        fd = os.open(path, os.O_RDONLY)
        os.fsync(fd)
        os.close(fd)
        logger.debug(f"Синхронизирован каталог: {path}")
    except Exception as e:
        logger.debug(f"fsync на каталоге не поддерживается: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Access denied.")
        return

    msg = update.message
    text = msg.text or msg.caption or "Без текста"

    media_link = ""
    try:
        if msg.photo:
            file = await context.bot.get_file(msg.photo[-1].file_id)
            file_name = f"{msg.date.strftime('%Y%m%d-%H%M%S')}_{msg.message_id}.jpg"
            file_path = os.path.join(ATTACHMENTS_PATH, file_name)
            await file.download_to_drive(file_path)
            with open(file_path, "ab") as f:
                f.flush()
                os.fsync(f.fileno())
            # Обновляем время файла
            os.utime(file_path, None)
            media_link = f"![[{file_name}]]"
    except (NetworkError, TimedOut) as e:
        logger.error(f"Ошибка загрузки фото: {e}")
        await update.message.reply_text("Не удалось загрузить фото.")
        return

    timestamp = msg.date.strftime("%Y-%m-%d-%H-%M")
    safe_content = re.sub(r'[\\/*?:"<>|]', "", text)[:30].strip() or "Untitled"

    link = (
        f"https://t.me/c/{str(msg.chat.id)[4:]}/{msg.message_id}"
        if str(msg.chat.id).startswith("-100")
        else f"https://t.me/{msg.from_user.username or 'u'}/{msg.message_id}"
    )

    forward = get_forward_info(msg)
    forward_yaml = ""
    if forward:
        forward_yaml = f"\nforward_from: \"{forward['name']}\""
        if forward["link"]:
            forward_yaml += f"\nforward_link: {forward['link']}"

    md_path = os.path.join(VAULT_PATH, f"{timestamp} - {safe_content}.md")
    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(
                f"---\n"
                f"aliases: [{safe_content}]\n"
                f"tags: [telegram]\n"
                f"source_link: {link}\n"
                f"{forward_yaml}\n"
                f"---\n\n"
                f"{text}\n\n{media_link}"
            )
            f.flush()
            os.fsync(f.fileno())
        # Обновляем время модификации файла
        os.utime(md_path, None)
        # Синхронизируем каталог, чтобы система увидела новый файл
        sync_filesystem(VAULT_PATH)
        logger.info(f"Файл сохранён: {md_path}")
    except Exception as e:
        logger.error(f"Ошибка записи файла: {e}")
        await update.message.reply_text("Не удалось сохранить заметку.")
        return

    await update.message.reply_text(f"Saved: {safe_content}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")
    if isinstance(context.error, (NetworkError, TimedOut, RetryAfter)):
        logger.warning("Сетевая ошибка, бот переподключится.")


if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()

    builder = ApplicationBuilder().token(TOKEN)

    if hasattr(builder, "connect_timeout"):
        builder.connect_timeout(10.0)
    if hasattr(builder, "read_timeout"):
        builder.read_timeout(30.0)
    if hasattr(builder, "pool_timeout"):
        builder.pool_timeout(5.0)
    if hasattr(builder, "get_updates_read_timeout"):
        builder.get_updates_read_timeout(45)
    if hasattr(builder, "get_updates_retries"):
        builder.get_updates_retries(5)

    app = builder.build()
    app.add_handler(
        MessageHandler(filters.TEXT | filters.CAPTION | filters.PHOTO, handle_message)
    )
    app.add_error_handler(error_handler)

    try:
        logger.info("Бот запущен...")
        app.run_polling(drop_pending_updates=True, allowed_updates=["message"])
    except (KeyboardInterrupt, SystemExit):
        logger.info("Завершение работы...")
