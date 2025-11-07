# bot.py
import os
import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")  # ambil token dari env
CHAT_ID = os.environ.get("CHAT_ID")      # optional: simpan chat id juga di env

if not BOT_TOKEN:
    raise SystemExit("ERROR: BOT_TOKEN environment variable not set")

# contoh state sederhana
waiting_for_links = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    waiting_for_links[chat_id] = True
    await update.message.reply_text("📋 Kirim daftar link (satu baris per link). Ketik /stop untuk batal.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    waiting_for_links.pop(chat_id, None)
    await update.message.reply_text("🛑 Monitoring dibatalkan.")

async def receive_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not waiting_for_links.get(chat_id):
        # jika belum di-mode input, abaikan atau jawab singkat
        await update.message.reply_text("Kirim /start dulu untuk mulai.")
        return

    text = update.message.text.strip()
    links = [l.strip() for l in text.splitlines() if l.strip()]
    await update.message.reply_text(f"🧩 {len(links)} link diterima. Memulai pengecekan...")

    # contoh: langsung kirim setiap link (gantikan dengan fungsi cek sebenarnya)
    for url in links:
        # di sini panggil fungsi async untuk resolve redirect / API / playwright dsb.
        await context.bot.send_message(chat_id=chat_id, text=f"Memeriksa: {url}")
        await asyncio.sleep(0.5)  # jangan spam

    waiting_for_links.pop(chat_id, None)
    await context.bot.send_message(chat_id=chat_id, text="✅ Selesai.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_links))

    print("🚀 Bot siap. Menjalankan polling...")
    app.run_polling()  # blocking

if __name__ == "__main__":
    main()
