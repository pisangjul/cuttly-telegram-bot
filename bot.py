import os
import asyncio
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# Logging untuk debugging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Ambil token dari environment variable
BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 8080))

# Statistik global
stats = {
    "total_links": 0,
    "batch_count": 0,
    "errors": [],
    "guard": [],
    "start_time": None
}

# Command /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats["start_time"] = datetime.now()
    await update.message.reply_text(
        "🤖 Bot aktif!\n"
        "Kirim link cutt.ly kamu di sini.\n"
        "Gunakan /stop untuk melihat hasil akhir."
    )

# Command /stop
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not stats["start_time"]:
        await update.message.reply_text("Bot belum dijalankan.")
        return

    runtime = datetime.now() - stats["start_time"]
    result_text = (
        "📊 **REKAP BOT**\n\n"
        f"🕒 Waktu berjalan: {runtime}\n"
        f"🔗 Total link: {stats['total_links']}\n"
        f"📦 Batch: {stats['batch_count']}\n"
        f"⚠️ Error: {len(stats['errors'])}\n"
        f"🛡️ Guard: {len(stats['guard'])}\n\n"
        f"🔍 Detail Error:\n" +
        "\n".join(stats["errors"][-5:] or ["-"]) +
        "\n\n🧱 Guard Trigger:\n" +
        "\n".join(stats["guard"][-5:] or ["-"])
    )
    await update.message.reply_text(result_text, parse_mode="Markdown")

# Proses link
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()

    if not link.startswith("http"):
        await update.message.reply_text("❌ Format link salah.")
        stats["errors"].append(link)
        return

    try:
        # Simulasi batch process
        stats["total_links"] += 1
        if stats["total_links"] % 10 == 0:
            stats["batch_count"] += 1

        # Guard (contoh: tolak domain tertentu)
        if "guard" in link or "phish" in link:
            stats["guard"].append(link)
            await update.message.reply_text("🛑 Link diblokir oleh guard!")
            return

        # Proses link dummy
        await asyncio.sleep(0.5)
        await update.message.reply_text(f"✅ Link diterima: {link}")

    except Exception as e:
        stats["errors"].append(str(e))
        await update.message.reply_text("⚠️ Gagal memproses link.")

# Main app
async def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN belum diatur di environment.")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    # Jalankan sebagai webhook (wajib di Render)
    webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}"
    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=f"{webhook_url}/{BOT_TOKEN}"
    )

if __name__ == "__main__":
    asyncio.run(main())
