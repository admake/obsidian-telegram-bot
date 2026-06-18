import os
import re
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_USERS = [
    int(u.strip()) for u in os.getenv("ALLOWED_USERS", "").split(",") if u.strip()
]
VAULT_PATH = "/app/vault"
ATTACHMENTS_PATH = os.path.join(VAULT_PATH, "Attachments")
os.makedirs(ATTACHMENTS_PATH, exist_ok=True)


# --- Healthcheck Server ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")


def run_health_server():
    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    server.serve_forever()


# --- Логика бота ---
def is_authorized(update: Update) -> bool:
    if not ALLOWED_USERS:
        return True
    return update.effective_user.id in ALLOWED_USERS


def get_forward_info(msg):
    """Извлекает информацию о пересылке (forward_from)"""
    if msg.forward_from:
        user = msg.forward_from
        name = user.full_name or user.username or "Unknown"
        link = f"https://t.me/{user.username}" if user.username else None
        return {"name": name, "link": link}
    elif msg.forward_from_chat:
        chat = msg.forward_from_chat
        name = chat.title or chat.full_name or "Unknown Chat"
        link = f"https://t.me/{chat.username}" if chat.username else None
        return {"name": name, "link": link}
    return None


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Access denied.")
        return

    msg = update.message
    text = msg.text or msg.caption or "Без текста"

    # --- Обработка медиа (фото) ---
    media_link = ""
    if msg.photo:
        file = await context.bot.get_file(msg.photo[-1].file_id)
        file_name = f"{msg.date.strftime('%Y%m%d-%H%M%S')}_{msg.message_id}.jpg"
        file_path = os.path.join(ATTACHMENTS_PATH, file_name)
        await file.download_to_drive(file_path)
        # Принудительная синхронизация файла
        with open(file_path, "ab") as f:
            f.flush()
            os.fsync(f.fileno())
        media_link = f"![[{file_name}]]"

    # --- Формирование метаданных ---
    timestamp = msg.date.strftime("%Y-%m-%d-%H-%M")
    safe_content = re.sub(r'[\\/*?:"<>|]', "", text)[:30].strip() or "Untitled"

    # Ссылка на сообщение
    link = (
        f"https://t.me/c/{str(msg.chat.id)[4:]}/{msg.message_id}"
        if str(msg.chat.id).startswith("-100")
        else f"https://t.me/{msg.from_user.username or 'u'}/{msg.message_id}"
    )

    # Информация о пересылке
    forward = get_forward_info(msg)
    forward_yaml = ""
    if forward:
        forward_yaml = f"\nforward_from: \"{forward['name']}\""
        if forward["link"]:
            forward_yaml += f"\nforward_link: {forward['link']}"

    # --- Запись .md файла с принудительной синхронизацией ---
    md_path = os.path.join(VAULT_PATH, f"{timestamp} - {safe_content}.md")
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

    await update.message.reply_text(f"Saved: {safe_content}")


if __name__ == "__main__":
    # Запуск Healthcheck в фоне
    threading.Thread(target=run_health_server, daemon=True).start()

    # Инициализация бота — прокси автоматически берётся из http_proxy/https_proxy
    builder = ApplicationBuilder().token(TOKEN)
    app = builder.build()
    app.add_handler(
        MessageHandler(filters.TEXT | filters.CAPTION | filters.PHOTO, handle_message)
    )

    # Запуск бота
    try:
        logging.info("Бот запущен...")
        app.run_polling()
    except (KeyboardInterrupt, SystemExit):
        logging.info("Завершение работы...")
