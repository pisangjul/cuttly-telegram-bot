import os
import re
import time
import logging
import asyncio
from typing import List, Tuple, Optional

import requests
from urllib.parse import urlparse

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =====================
# Logging
# =====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("LinkBot")

# =====================
# Global State
# =====================
LINKS: List[str] = []    # Link valid (normal)
ERRORS: List[str] = []   # Link bermasalah (gagal redirect / status >= 400 / timeout)
GUARDS: List[str] = []   # Link mencurigakan (domain judi/slot/casino/bet)
START_TIME: float = time.time()
PAUSED: bool = False     # /stop → True (bot pause), /start → False (bot aktif)

# Regex sederhana untuk deteksi URL (termasuk cutt.ly atau lainnya)
URL_REGEX = re.compile(
    r"(?i)\b(?:https?://|www\.)[^\s<>()]+"
)

SUSPICIOUS_KEYWORDS = ("judi", "slot", "casino", "bet")


# =====================
# Util
# =====================
def now_runtime_str() -> str:
    seconds = int(time.time() - START_TIME)
    hrs = seconds // 3600
    mins = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hrs}h {mins}m {secs}s"


def is_suspicious_domain(url: str) -> bool:
    try:
        # Normalisasi jika diawali www.
        if url.startswith("www."):
            url = "http://" + url
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        path = (parsed.path or "").lower()
        text = host + " " + path
        return any(k in text for k in SUSPICIOUS_KEYWORDS)
    except Exception:
        return False


def check_redirect(url: str) -> Tuple[bool, Optional[str], Optional[int], Optional[str]]:
    """
    Mengembalikan:
    - ok (bool): True jika request berhasil (<400), False jika error/timeout
    - final_url (str|None): URL akhir setelah redirect
    - status_code (int|None): kode status HTTP
    - reason (str|None): pesan singkat jika error
    """
    try:
        # Tambahkan skema jika user hanya kirim "www.example.com"
        if url.startswith("www."):
            url = "http://" + url

        resp = requests.get(url, allow_redirects=True, timeout=10)
        status = resp.status_code
        final_url = resp.url
        if status >= 400:
            return False, final_url, status, f"HTTP {status}"
        return True, final_url, status, None
    except requests.Timeout:
        return False, None, None, "Timeout"
    except requests.RequestException as e:
        return False, None, None, f"Error: {e}"


async def send_batched(update: Update, items: List[str], header: str) -> None:
    """
    Kirim list dalam batch 30 item per pesan, jeda 1.5 detik.
    Format HTML, aman untuk jumlah besar.
    """
    if not items:
        await update.message.reply_text(
            f"{header}\n<i>Tidak ada data.</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    batch_size = 30
    delay = 1.5
    total = len(items)
    for i in range(0, total, batch_size):
        batch = items[i:i + batch_size]
        body = "\n".join(f"{idx+1}. {val}" for idx, val in enumerate(batch, start=i))
        text = f"{header}\n<pre>{body}</pre>"
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        if i + batch_size < total:
            await asyncio.sleep(delay)


# =====================
# Handlers
# =====================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global PAUSED
    PAUSED = False
    await update.message.reply_text("Bot aktif", parse_mode=ParseMode.HTML)


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global PAUSED
    PAUSED = True
    await update.message.reply_text("Bot dihentikan sementara (pause).", parse_mode=ParseMode.HTML)


async def total_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "<b>Ringkasan</b>\n"
        f"- Links: <b>{len(LINKS)}</b>\n"
        f"- Errors: <b>{len(ERRORS)}</b>\n"
        f"- Guards: <b>{len(GUARDS)}</b>\n"
        f"- Runtime: <b>{now_runtime_str()}</b>\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global LINKS, ERRORS, GUARDS, PAUSED

    msg = update.message.text.strip()

    # Perintah khusus via teks (tanpa /)
    if msg.lower().startswith("error"):
        ERRORS.append(msg)
        await update.message.reply_text("Ditambahkan ke daftar errors.", parse_mode=ParseMode.HTML)
        return

    if msg.lower().startswith("guard"):
        GUARDS.append(msg)
        await update.message.reply_text("Ditambahkan ke daftar guards.", parse_mode=ParseMode.HTML)
        return

    if msg.lower() == "result":
        # Tampilkan daftar link + hasil pengecekan redirect-nya (ringkas)
        # Kita generate ringkasan detail per link yang sudah ada (LINKS + GUARDS + ERRORS sumber link)
        report_lines: List[str] = []
        combined = []
        # Gabungkan semua sumber link unik dari tiga daftar (yang berbentuk URL)
        # Di sini kita ambil hanya yang terlihat seperti URL dari LINKS, ERRORS, GUARDS
        def extract_urls(items: List[str]) -> List[str]:
            urls = []
            for it in items:
                for m in URL_REGEX.findall(it):
                    urls.append(m)
            return urls

        combined = list(dict.fromkeys(
            extract_urls(LINKS) + extract_urls(ERRORS) + extract_urls(GUARDS)
        ))

        if not combined:
            await update.message.reply_text(
                "<b>Result</b>\n<i>Tidak ada link untuk diringkas.</i>",
                parse_mode=ParseMode.HTML,
            )
            return

        for url in combined:
            ok, final_url, status, reason = check_redirect(url)
            if ok:
                suspicious = is_suspicious_domain(final_url or url)
                tag = "GUARD" if suspicious else "OK"
                final_show = final_url or url
                report_lines.append(f"[{tag}] {url} → {final_show} (HTTP {status})")
            else:
                report_lines.append(f"[ERROR] {url} → {reason or 'Unknown error'}")

        await send_batched(update, report_lines, "<b>Result (ringkasan redirect)</b>")
        return

    # Jika bot sedang pause, abaikan input biasa (tetap biarkan command bekerja)
    if PAUSED:
        await update.message.reply_text(
            "Bot sedang pause. Gunakan /start untuk mengaktifkan kembali.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Deteksi link di pesan
    urls = URL_REGEX.findall(msg)
    if not urls:
        # Tidak ada URL, abaikan
        return

    # Untuk setiap URL: cek redirect dan klasifikasikan
    for url in urls:
        ok, final_url, status, reason = check_redirect(url)
        if not ok:
            ERRORS.append(url)
            logger.info(f"URL error: {url} ({reason})")
            continue

        # Cek domain mencurigakan pada URL akhir (atau URL awal jika None)
        target = final_url or url
        if is_suspicious_domain(target):
            GUARDS.append(url)
            logger.info(f"URL guard: {url} → {target} (HTTP {status})")
        else:
            LINKS.append(url)
            logger.info(f"URL normal: {url} → {target} (HTTP {status})")


# =====================
# Main
# =====================
def main() -> None:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("Environment variable BOT_TOKEN tidak ditemukan.")

    app = ApplicationBuilder().token(token).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("total", total_cmd))

    # Text message handler (semua teks non-command)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    logger.info("Bot sedang berjalan (mode polling)…")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        poll_interval=1.0,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
