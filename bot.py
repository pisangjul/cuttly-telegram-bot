import os
import time
import logging
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ============= KONFIGURASI =============
BOT_TOKEN = os.getenv("BOT_TOKEN")
BATCH_SIZE = 30  # jumlah link per batch

# ============= LOGGING =============
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ============= DATA GLOBAL =============
links = []
errors = []
guards = []
start_time = time.time()
processing = False

# ============= FUNGSI PENDUKUNG =============
def runtime():
    dur = int(time.time() - start_time)
    jam = dur // 3600
    menit = (dur % 3600) // 60
    detik = dur % 60
    return f"{jam:02d}:{menit:02d}:{detik:02d}"

def batch_text():
    total = len(links)
    result = "\n".join(f"{i+1}. {link}" for i, link in enumerate(links))
    summary = (
        "\n\n📊 <b>RINGKASAN</b>\n"
        f"Total link: {total}\n"
        f"Total error: {len(errors)}\n"
        f"Total guard: {len(guards)}\n"
        f"Runtime: {runtime()}\n"
    )

    if errors:
        summary += "\n⚠️ <b>Daftar Error</b>\n" + "\n".join(errors)
    if guards:
        summary += "\n🛡️ <b>Daftar Guard</b>\n" + "\n".join(guards)

    return f"{result}{summary}"

async def process_batch(context: ContextTypes.DEFAULT_TYPE, chat_id):
    global links, processing
    if not links:
        await context.bot.send_message(chat_id=chat_id, text="❌ Tidak ada link untuk diproses.")
        return

    processing = True
    await context.bot.send_message(chat_id=chat_id, text="🚀 Memproses batch...")

    for i in range(0, len(links), BATCH_SIZE):
        batch = links[i:i + BATCH_SIZE]
        await asyncio.sleep(1.5)  # delay ringan antar batch
        text_batch = "\n".join(batch)
        await context.bot.send_message(chat_id=chat_id, text=f"📦 Batch {i//BATCH_SIZE + 1}\n{text_batch}")

    await context.bot.send_message(chat_id=chat_id, text=batch_text(), parse_mode="HTML")
    processing = False
    links.clear()
    errors.clear()
    guards.clear()

# ============= HANDLER =============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot aktif! Kirim link cutt.ly kamu di sini.\nKetik /total untuk melihat status.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⛔ Bot dihentikan sementara.")

async def total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        f"📊 Total link: {len(links)}\n"
        f"⚠️ Error: {len(errors)} | 🛡️ Guard: {len(guards)}\n"
        f"⏱ Runtime: {runtime()}\n"
    )
    await update.message.reply_text(msg)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text.startswith("http"):
        links.append(text)
        await update.message.reply_text(f"✅ Link diterima! ({len(links)} total)")
    elif text.lower().startswith("error"):
        errors.append(text)
        await update.message.reply_text("⚠️ Error dicatat.")
    elif text.lower().startswith("guard"):
        guards.append(text)
        await update.message.reply_text("🛡️ Guard dicatat.")
    elif text.lower() == "result":
        await process_batch(context, update.effective_chat.id)
    else:
        await update.message.reply_text("💡 Gunakan format link atau ketik 'result' untuk ringkasan.")

# ============= MAIN =============
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("total", total))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logging.info("Bot sedang berjalan (mode polling)...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
