import time
import asyncio
import threading
import os
from collections import defaultdict
from urllib.parse import urlparse

from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# ---------------- CONFIG ----------------
BOT_TOKEN = "8500542639:AAE4jyCP-Y19-MVvNAzpopEzP05102TucUQ"
CONTENT_DOMAIN = "mahitimanch.in"
MAX_WORKERS = 2
SPAM_COOLDOWN = 60
# ---------------------------------------


# ---------- FLASK WEB SERVER ----------
web_app = Flask(__name__)

@web_app.route("/")
def home():
    return "Bot is running", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)
# -------------------------------------


# ---------- SELENIUM SETUP ----------
CHROME_PATH = ChromeDriverManager().install()
# ----------------------------------


def is_likely_real(url):
    p = urlparse(url)
    host = p.netloc.lower()
    path = p.path.lower()
    query = p.query

    if "inshorturl.in" in host:
        return False
    if len(host) > 35:
        return False
    if host.count('.') > 3:
        return False
    if any(k in path for k in ("/sl/", "/go/", "/click/", "/aff/")):
        return False
    if len(query.split("&")) > 5:
        return False

    return True


def resolve_link(start_url):
    start_time = time.time()

    options = webdriver.ChromeOptions()
    options.page_load_strategy = "eager"
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument("--disable-font-subpixel-positioning")

    driver = webdriver.Chrome(
        service=Service(CHROME_PATH),
        options=options
    )

    wait = WebDriverWait(driver, 15, poll_frequency=0.4)
    driver.get(start_url)

    # DO NOT CHANGE THIS TIMING
    for _ in range(4):
        wait.until(lambda d: CONTENT_DOMAIN in d.current_url)
        wait.until(EC.presence_of_element_located((By.ID, "tpForm")))
        driver.execute_script("tpForm.submit()")
        time.sleep(1)

    wait.until(EC.presence_of_element_located((By.ID, "gtelinkbtn")))
    driver.execute_script("gtelinkbtn.click()")

    time.sleep(10)

    real_links = []
    seen = set()

    for h in driver.window_handles:
        driver.switch_to.window(h)
        url = driver.current_url
        if url and url not in seen and is_likely_real(url):
            seen.add(url)
            real_links.append(url)

    driver.quit()
    return real_links, time.time() - start_time


# ---------- CONCURRENCY ----------
task_queue = asyncio.Queue()
semaphore = asyncio.Semaphore(MAX_WORKERS)
recent_requests = defaultdict(dict)


async def worker():
    while True:
        update, url = await task_queue.get()
        async with semaphore:
            try:
                links, t = await asyncio.to_thread(resolve_link, url)

                if not links:
                    await update.message.reply_text(
                        "❌ No valid destination found.\nPlease retry."
                    )
                else:
                    msg = "✅ Destination link(s):\n\n"
                    for l in links:
                        msg += f"{l}\n\n"
                    msg += f"⏱ Time taken: {t:.2f} seconds"
                    await update.message.reply_text(msg)

            except Exception:
                await update.message.reply_text(
                    "⚠️ Error while resolving the link.\nPlease try again."
                )

        task_queue.task_done()
# ---------------------------------


# ---------- TELEGRAM ----------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome!\n\n"
        "Send an inshorturl link and I’ll try to find the real destination.\n\n"
        "⚠️ Disclaimer:\n"
        "Sometimes ads or incorrect URLs may appear.\n"
        "If that happens, retry the same link."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.message.from_user.id
    now = time.time()

    if not text.startswith("http"):
        await update.message.reply_text("❌ Send a valid inshorturl link.")
        return

    last_time = recent_requests[user_id].get(text)
    if last_time and now - last_time < SPAM_COOLDOWN:
        await update.message.reply_text(
            "⏳ This link is already being processed. Please wait."
        )
        return

    recent_requests[user_id][text] = now
    await update.message.reply_text("📥 Link received. Processing…")

    await task_queue.put((update, text))
# ----------------------------------


if __name__ == "__main__":
    print("🤖 Bot is running live (web service mode)...")

    # start web server
    threading.Thread(target=run_web, daemon=True).start()

    tg_app = ApplicationBuilder().token(BOT_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start_cmd))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    loop = asyncio.get_event_loop()
    for _ in range(MAX_WORKERS):
        loop.create_task(worker())

    tg_app.run_polling()
