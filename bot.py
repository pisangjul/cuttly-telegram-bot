import os
import re
import time
import logging
import asyncio
from typing import List, Dict, Any, Optional

import cloudscraper
from requests.exceptions import RequestException, Timeout

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# Logging
# =========================
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("LinkBot")

# =========================
# Global state
# =========================
LINKS: List[Dict[str, Any]] = []
ERRORS: List[str] = []
GUARDS: List[str] = []
START_TIME: float = time.time()
PAUSED: bool = False

# Suspicious keywords
SUSPICIOUS_KEYWORDS = ["judi", "slot", "casino", "bet"]

# URL regex
URL_PATTERN = re.compile(r"(?i)\bhttps?://[^\s<>\"']+")

# Cloudscraper instance
scraper = cloudscraper.create_scraper()

# =========================
# Helpers
# =========================
def is_suspicious_domain(url: str) -> bool:
    return any(k in (url or "").lower() for k in SUSPICIOUS_KEYWORDS)

def format_runtime(seconds: float) -> str:
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

async def check_redirect(url: str) -> Dict[str, Any]:
    def _do_request(u: str) -> Dict[str, Any]:
        try:
            resp = scraper.get(u, allow_redirects=True, timeout=10)
            final_url = resp.url
            status_code = resp.status_code
            ok = status_code < 400
            return {
                "original": u,
                "status_code": status_code,
                "final_url": final_url,
                "ok": ok,
                "error": None,
            }
        except Timeout as e:
            return {"original": u, "status_code": None, "final_url": None, "ok": False, "error": f"Timeout: {e}"}
        except RequestException as e:
            return {"original": u, "status_code": None, "final_url": None, "ok": False, "error": f"RequestException: {e}"}
        except Exception as e:
            return {"original": u, "status_code": None, "final_url": None, "ok": False, "error": f"Exception: {e}"}
    return await asyncio.to_thread(_do_request, url)

def render_result_line(item: Dict[str, Any], tag: str) -> str:
    original = item.get("original") or ""
    status_code = item.get("status_code")
    final_url = item.get("final_url") or ""
    ok = item.get("ok")
    error = item.get("error")

    tag_label = f" <i>[{tag}]</i>"
    if ok:
        sc = status_code if status_code is not None else "-"
        return f"<b>Link:</b> {original}{tag_label}\n  ↳ <b>Status:</b> {sc} | <b>Final:</b> {final_url}"
    else:
        sc = status_code if status_code is not None else "-"
        err_text = error or "Unknown error"
        return f"<b>Link:</b> {original}{tag_label}\n  ↳ <b>Status:</b> {sc} | <b>Error:</b> {err_text}"

async def send_batched_lines(context: ContextTypes.DEFAULT_TYPE, chat_id: int, lines: List[str], header: Optional[str] = None) -> None:
    if header:
        await context.bot.send_message(chat_id=chat_id, text=header, parse_mode=ParseMode.HTML)
    if not lines:
        await context.bot.send_message(chat_id=chat_id, text="<i>Tidak ada data untuk ditampilkan.</i>", parse_mode=ParseMode.HTML)
        return
    BATCH_SIZE = 30
    BATCH_DELAY_SEC = 1.5
    for i in range(0, len(lines), BATCH_SIZE):
        chunk = lines[i:i + BATCH_SIZE]
        text = "\n".join(chunk)
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
        if i + BATCH_SIZE < len(lines):
            await asyncio.sleep(BATCH_DELAY_SEC)

# =========================
# Auto-report job
# =========================
async def auto_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = context.job.chat_id
    runtime = format_runtime(time.time() - START_TIME)
    lines: List[str] = []
    for item in LINKS:
        lines.append(render_result_line(item, "link"))
    for e in ERRORS:
        lines.append(f"<b>Error:</b> {e}")
    for g in GUARDS:
        lines.append(f"<b>Guard:</b> {g}")
    header = (
        f"<b>Auto Report:</b>\n"
        f"- Links: {len(LINKS)}\n"
        f"- Errors: {len(ERRORS)}\n"
        f"- Guards: {len(GUARDS)}\n"
        f"- Runtime: {runtime}\n"
    )
    await send_batched_lines(context, chat_id, lines, header=header)
    logger.info("Auto-report dikirim.")

# =========================
# Handlers
# =========================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global PAUSED
    PAUSED = False
    await update.message.reply_text("Bot aktif")
    # Schedule auto-report setiap 5 menit
    context.job_queue.run_repeating(auto_report, interval=300, first=10, chat_id=update.effective_chat.id)
    logger.info("Perintah /start diterima. Auto-report dijadwalkan.")

async def total_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    runtime = format_runtime(time.time() - START_TIME)
    text = (
        f"<b>Total ringkasan:</b>\n"
        f"- Links: {len(LINKS)}\n"
        f"- Errors: {len(ERRORS)}\n"
        f"- Guards: {len(GUARDS)}\n"
        f"- Runtime: {runtime}\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global PAUSED
    PAUSED = True
    await update.message.reply_text("Bot dihentikan sementara. Polling tetap berjalan.", parse_mode=ParseMode.HTML)

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    lower = text.lower()
    if PAUSED:
        await update.message.reply_text("<i>Bot sedang dihentikan sementara. Gunakan /start untuk melanjutkan.</i>", parse_mode=ParseMode.HTML)
        return
    urls = URL_PATTERN.findall(text)
    if urls:
        lines: List[str] = []
        for url in urls:
            result = await check_redirect(url)
            if not result.get("ok", False):
                ERRORS.append(url)
                lines.append(render_result_line(result, "error"))
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f"⚠️ Error pada link: {url}", parse_mode=ParseMode.HTML)
            elif is_suspicious_domain(result.get("final_url") or url):
                GUARDS.append(url)
                lines.append(render_result_line(result, "guard"))
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🚨 Guard terdeteksi: {url}", parse_mode=ParseMode.HTML)
            else:
                LINKS.append(result)
                lines.append(render_result_line(result, "link"))
        await send_batched_lines(context, update.effective_chat.id, lines, header="<b>Hasil pengecekan redirect:</b>")
    else:
        await update.message.reply_text("<i>Kirim link untuk diperiksa.</i>", parse_mode=ParseMode.HTML)

# =========================
# Main
# =========================
def main() -> None:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("Environment variable TELEGRAM_TOKEN tidak ditemukan.")
    logger.info("Bot sedang berjalan (mode polling)…")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("total", total_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.run_polling(allowed_updates=Update.ALL_TYPES, poll_interval=1.0, drop)
