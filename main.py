import os
import re
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import httpx
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


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Access denied.")
        return

    msg = update.message
    text = msg.text or msg.caption or "Без текста"

    media_link = ""
    if msg.photo:
        file = await context.bot.get_file(msg.photo[-1].file_id)
        file_name = f"{msg.date.strftime('%Y%m%d-%H%M%S')}_{msg.message_id}.jpg"
        await file.download_to_drive(os.path.join(ATTACHMENTS_PATH, file_name))
        media_link = f"![[{file_name}]]"

    timestamp = msg.date.strftime("%Y-%m-%d-%H-%M")
    safe_content = re.sub(r'[\\/*?:"<>|]', "", text)[:30].strip() or "Untitled"
    link = (
        f"https://t.me/c/{str(msg.chat.id)[4:]}/{msg.message_id}"
        if str(msg.chat.id).startswith("-100")
        else f"https://t.me/{msg.from_user.username or 'u'}/{msg.message_id}"
    )

    with open(
        os.path.join(VAULT_PATH, f"{timestamp} - {safe_content}.md"),
        "w",
        encoding="utf-8",
    ) as f:
        f.write(
            f"---\naliases: [{safe_content}]\ntags: [telegram]\n---\n\n{text}\n\n{media_link}"
        )

    await update.message.reply_text(f"Saved: {safe_content}")


if __name__ == "__main__":
    # Запуск Healthcheck в фоне
    threading.Thread(target=run_health_server, daemon=True).start()

    # --- Настройка прокси через стандартные переменные окружения ---
    builder = ApplicationBuilder().token(TOKEN)

    # Читаем прокси из переменных окружения (стандартные имена)
    http_proxy = os.getenv("http_proxy") or os.getenv("HTTP_PROXY")
    https_proxy = os.getenv("https_proxy") or os.getenv("HTTPS_PROXY")

    if http_proxy or https_proxy:
        proxies = {}
        if http_proxy:
            proxies["http://"] = http_proxy
        if https_proxy:
            proxies["https://"] = https_proxy
        # Создаём асинхронный HTTP-клиент с прокси
        client = httpx.AsyncClient(proxies=proxies)
        builder.http_client(client)
        logging.info(f"Прокси настроен: http={http_proxy}, https={https_proxy}")
    else:
        logging.info("Прокси не задан, работаем напрямую")

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
