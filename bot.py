import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
CUTTLY_API = os.getenv("CUTTLY_API_KEY")  # Tambahkan di Render dashboard > Environment > CUTTLY_API_KEY

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot aktif! Kirim link cutt.ly kamu untuk dicek statusnya.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot berhenti.")

async def check_cuttly_link(link):
    url = f"https://cutt.ly/api/api.php?key={CUTTLY_API}&short={link}"
    response = requests.get(url)
    data = response.json()

    try:
        status = data["url"]["status"]
        if status == 7:
            title = data["url"]["title"]
            full_link = data["url"]["fullLink"]
            return f"✅ Link aktif!\nJudul: {title}\nTujuan: {full_link}"
        elif status == 1:
            return "❌ Link tidak valid."
        elif status == 2:
            return "⚠️ Domain cutt.ly diblokir atau error."
        elif status == 3:
            return "⚠️ Link sudah dihapus atau rusak."
        else:
            return "❓ Tidak diketahui status link ini."
    except Exception:
        return "❌ Gagal memeriksa link."

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "cutt.ly" in text:
        result = await check_cuttly_link(text)
        await update.message.reply_text(result)
    else:
        await update.message.reply_text("Kirim link cutt.ly untuk saya periksa ya!")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot sedang berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()
