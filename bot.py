import asyncio
import os
import logging
from datetime import datetime
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ======= KONFIGURASI =======
BOT_TOKEN = os.getenv("7577154345", "8566241367:AAFXPaMhnL_KANFA1dVGIqI00NgZMG_yqVA")
CHECK_INTERVAL = 600  # detik = 10 menit

# ======= LOGGING =======
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ======= STATE =======
user_links = {}
monitoring_tasks = {}

# ======= CEK LINK CUTT.LY =======
async def check_link(link: str):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(link, timeout=30000, wait_until="load")
            final_url = page.url
            status = "✅ OK"
            if "guard" in final_url.lower():
                status = "🔒 Guard"
            await browser.close()
            return status, final_url
    except Exception as e:
        return "❌ Error", str(e)

# ======= MONITOR LOOP =======
async def monitor_links(user_id, context: ContextTypes.DEFAULT_TYPE):
    while True:
        if user_id not in user_links:
            break
        results = []
        for link in user_links[user_id]:
            status, dest = await check_link(link)
            results.append(f"{link} → {status} ({dest[:60]})")
            await asyncio.sleep(1)
        now = datetime.now().strftime("%H:%M:%S")
        summary = "\n".join(results)
        await context.bot.send_message(chat_id=user_id, text=f"📊 Update {now}\n{summary}")
        await asyncio.sleep(CHECK_INTERVAL)

# ======= HANDLER =======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    user_links[user_id] = []
    await update.message.reply_text("Kirim daftar link cutt.ly (satu per baris). Ketik /stop untuk berhenti.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    if user_id in monitoring_tasks:
        monitoring_tasks[user_id].cancel()
        del monitoring_tasks[user_id]
    if user_id in user_links:
        del user_links[user_id]
    await update.message.reply_text("⛔ Monitoring dihentikan.")

async def handle_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    if user_id not in user_links:
        await update.message.reply_text("Ketik /start dulu untuk memulai.")
        return

    # Ambil daftar link
    text = update.message.text.strip()
    links = [line.strip() for line in text.splitlines() if line.startswith("http")]
    if not links:
        await update.message.reply_text("Tidak ada link valid ditemukan.")
        return

    user_links[user_id] = links
    await update.message.reply_text(f"🚀 Memulai pengecekan {len(links)} link setiap 10 menit...")

    # Mulai task monitor
    task = asyncio.create_task(monitor_links(user_id, context))
    monitoring_tasks[user_id] = task

# ======= MAIN =======
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_links))
    logger.info("🤖 Bot aktif dan menunggu perintah...")
    app.run_polling()

if __name__ == "__main__":
    main()

