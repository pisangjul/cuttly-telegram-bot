# bot.py
import os
import time
import asyncio
import logging
from typing import Dict, Any
import aiohttp
import async_timeout

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ============= KONFIGURASI via ENV =============
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))  # detik, default 300 (5 menit)
CONCURRENCY = int(os.getenv("CONCURRENCY", "10"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))  # detik
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "30"))
BATCH_DELAY = float(os.getenv("BATCH_DELAY", "1.5"))

# ============= LOGGING =============
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ============= STATE GLOBAL =============
links = []           # list of submitted links (raw)
errors = []          # tempat log error manual dari user
guards = []          # catatan guard manual dari user
start_time = time.time()
processing = False

subscribers = set()  # chat_id yang terdaftar untuk menerima hasil periodik

# cache: url -> (timestamp, result_dict)
cache: Dict[str, Any] = {}
cache_lock = asyncio.Lock()

# aiohttp session & semaphore (diinisialisasi di main)
SESSION: aiohttp.ClientSession = None
SEM: asyncio.Semaphore = None

KEYWORDS_GUARD = ("judi", "slot", "casino", "bet", "porn", "gamble", "casinoindonesia")

# ============= UTIL =============
def runtime():
    dur = int(time.time() - start_time)
    jam = dur // 3600
    menit = (dur % 3600) // 60
    detik = dur % 60
    return f"{jam:02d}:{menit:02d}:{detik:02d}"

def batch_text_from_results(results):
    lines = []
    for i, r in enumerate(results, 1):
        url = r.get("url")
        res = r.get("result")
        note = r.get("note") or ""
        loc = r.get("location") or ""
        lines.append(f"{i}. {url}\n→ {res} {note} {loc}")
    return "\n\n".join(lines)

async def classify_url(url: str) -> dict:
    """
    Check URL briefly: HEAD (no follow) then fallback GET partial.
    Return dict with keys: url, status, location, result, note, server
    Uses global SESSION and SEM.
    """
    global SESSION, SEM
    async with SEM:
        now = time.time()
        # cache check
        async with cache_lock:
            item = cache.get(url)
            if item and now - item["ts"] < CACHE_TTL:
                return item["result"]

        try:
            async with async_timeout.timeout(12):
                headers = {"User-Agent": "Mozilla/5.0 (compatible)"}
                try:
                    resp = await SESSION.head(url, allow_redirects=False, headers=headers)
                except Exception:
                    # fallback: GET partial
                    headers["Range"] = "bytes=0-2048"
                    resp = await SESSION.get(url, allow_redirects=False, headers=headers)

                status = resp.status
                loc = resp.headers.get("Location") or resp.headers.get("location")
                server = (resp.headers.get("Server") or "").lower()
                body_snip = ""

                # read small body for detection if needed
                if status == 200:
                    try:
                        body_snip = await resp.text()
                        body_snip = body_snip[:2000].lower()
                    except Exception:
                        body_snip = ""

                # classification logic
                if status >= 500 or status in (403, 429):
                    result = "error"
                    note = f"status {status}"
                elif 300 <= status < 400 and loc:
                    low_loc = loc.lower()
                    if any(k in low_loc for k in KEYWORDS_GUARD):
                        result = "guard"
                        note = f"redirect suspicious"
                    else:
                        result = "redirect"
                        note = f"redirect"
                elif "checking your browser" in body_snip or "cf-chl" in body_snip or "attention required" in body_snip:
                    result = "cloudflare_challenge"
                    note = "CF challenge"
                elif status == 200:
                    if any(k in body_snip for k in KEYWORDS_GUARD):
                        result = "guard"
                        note = "keyword in content"
                    else:
                        result = "ok"
                        note = "200 OK"
                else:
                    result = "unknown"
                    note = f"status {status}"

                out = {"url": url, "status": status, "location": loc, "result": result, "note": note, "server": server}
                # cache store
                async with cache_lock:
                    cache[url] = {"ts": time.time(), "result": out}
                return out

        except asyncio.TimeoutError:
            out = {"url": url, "status": None, "location": None, "result": "error", "note": "timeout"}
            async with cache_lock:
                cache[url] = {"ts": time.time(), "result": out}
            return out
        except Exception as e:
            out = {"url": url, "status": None, "location": None, "result": "error", "note": f"exc: {e}"}
            async with cache_lock:
                cache[url] = {"ts": time.time(), "result": out}
            return out

# ============= PERIODIC JOB =============
async def periodic_check_job(context: ContextTypes.DEFAULT_TYPE):
    """
    JobQueue callback — runs every CHECK_INTERVAL seconds.
    Will check all links currently in 'links' list and send results to subscribers.
    """
    if not links:
        logging.info("Periodic check: no links to check.")
        return

    current_links = list(set(links))  # unique
    logging.info(f"Periodic check: checking {len(current_links)} links for {len(subscribers)} subscribers.")
    # run checks concurrently with limit
    tasks = [asyncio.create_task(classify_url(u)) for u in current_links]
    results = await asyncio.gather(*tasks)

    # split into guard/error/ok lists
    guards_found = [r for r in results if r["result"] in ("guard", "cloudflare_challenge", "error")]
    oks = [r for r in results if r["result"] == "ok"]
    # prepare message per subscriber
    summary_lines = []
    summary_lines.append(f"⏱ Periodic Check — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    summary_lines.append(f"Total checked: {len(results)}")
    summary_lines.append(f"Found guard/error: {len(guards_found)} | OK: {len(oks)}")
    summary = "\n".join(summary_lines)

    bot = context.bot
    # first send summary
    for chat_id in subscribers:
        try:
            await bot.send_message(chat_id=chat_id, text=summary)
        except Exception as e:
            logging.warning(f"Failed send summary to {chat_id}: {e}")

    # send detailed guard/error lists in batches
    if guards_found:
        for chat_id in subscribers:
            try:
                # prepare batched messages
                for i in range(0, len(guards_found), BATCH_SIZE):
                    batch = guards_found[i:i+BATCH_SIZE]
                    text_batch = batch_text_from_results(batch)
                    await bot.send_message(chat_id=chat_id, text=f"⚠️ Guard/Error batch {i//BATCH_SIZE + 1}\n\n{text_batch}", parse_mode="HTML")
                    await asyncio.sleep(BATCH_DELAY)
            except Exception as e:
                logging.warning(f"Failed send detail to {chat_id}: {e}")

    # Optionally send OK list if small
    # (skip sending all OKs automatically if large — change as needed)
    if len(oks) <= 20 and oks:
        for chat_id in subscribers:
            try:
                await bot.send_message(chat_id=chat_id, text="✅ OK links:\n\n" + batch_text_from_results(oks), parse_mode="HTML")
            except Exception as e:
                logging.warning(f"Failed send oks to {chat_id}: {e}")

# ============= HANDLER =============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    subscribers.add(chat_id)
    await update.message.reply_text(
        "🤖 Bot aktif! Kamu akan menerima hasil periodic check setiap beberapa menit. Kirim link cutt.ly di sini. Ketik /total untuk status."
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in subscribers:
        subscribers.remove(chat_id)
    await update.message.reply_text("⛔ Kamu berhenti berlangganan hasil periodic check.")


async def total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        f"📊 Total link stored: {len(links)}\n"
        f"⚠️ Errors manual: {len(errors)} | 🛡️ Guards manual: {len(guards)}\n"
        f"Subscribed chats: {len(subscribers)}\n"
        f"⏱ Runtime: {runtime()}\n"
    )
    await update.message.reply_text(msg)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text.startswith("http"):
        links.append(text)
        await update.message.reply_text(
            f"✅ Link diterima! ({len(links)} total). Akan dicek pada interval berikutnya."
        )

    elif text.lower().startswith("error"):
        errors.append(text)
        await update.message.reply_text("⚠️ Error dicatat.")

    elif text.lower().startswith("guard"):
        guards.append(text)
        await update.message.reply_text("🛡️ Guard dicatat.")

    elif text.lower() == "result":
        # immediate check for this chat only
        chat_id = update.effective_chat.id
        await update.message.reply_text("🔎 Menjalankan pengecekan cepat untuk link yang ada...")

        current_links = list(set(links))
        tasks = [asyncio.create_task(classify_url(u)) for u in current_links]
        results = await asyncio.gather(*tasks)

        guards_found = [r for r in results if r["result"] in ("guard", "cloudflare_challenge", "error")]
        oks = [r for r in results if r["result"] == "ok"]

        # send summary + details
        summary = f"Quick check: Total {len(results)}, guard/error {len(guards_found)}, ok {len(oks)}"
        await context.bot.send_message(chat_id=chat_id, text=summary)

        if guards_found:
            for i in range(0, len(guards_found), BATCH_SIZE):
                batch = guards_found[i:i + BATCH_SIZE]
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=batch_text_from_results(batch),
                    parse_mode="HTML"
                )
                await asyncio.sleep(BATCH_DELAY)
    else:
        await update.message.reply_text("💡 Kirim link (http...) atau ketik 'result' untuk pengecekan cepat.")


# ============= MAIN =============
def main():
    global SESSION, SEM
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN tidak ditemukan di environment.")
        return

    SEM = asyncio.Semaphore(CONCURRENCY)

    # ======== definisi lifecycle aiohttp ========
    async def _init_session(app):
        global SESSION
        SESSION = aiohttp.ClientSession()
        logging.info("Aiohttp session initialized.")

    async def _close_session(app):
        global SESSION
        if SESSION:
            await SESSION.close()
            logging.info("Aiohttp session closed.")

    # ======== buat app hanya sekali ========
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(_init_session)
        .post_shutdown(_close_session)
        .build()
    )

    # ======== tambahkan semua handler ========
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("total", total))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # ======== aktifkan JobQueue untuk periodic check ========
    if app.job_queue:
        app.job_queue.run_repeating(periodic_check_job, interval=CHECK_INTERVAL, first=10)
    else:
        logging.warning("JobQueue tidak tersedia — pastikan python-telegram-bot[job-queue] terinstal.")

    logging.info("Bot sedang berjalan (mode polling)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
