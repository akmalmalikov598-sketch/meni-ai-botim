# bot.py  (bitta fayl)
import os, re, json, html, base64, sqlite3, asyncio, logging, time
from threading import Thread
import httpx
from flask import Flask
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          filters, ContextTypes)

BOT_TOKEN = os.environ["BOT_TOKEN"]
GROQ_KEY = os.environ["GROQ_API_KEY"]
STT_MODEL = os.getenv("STT_MODEL", "whisper-large-v3-turbo")
HISTORY_LIMIT = 20

# main() ichida avtomatik tanlanadi (env orqali majburlash ham mumkin)
CHAT_MODEL = "llama-3.1-8b-instant"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

SYSTEM_PROMPT = (
    "Sen ChatGPT darajasidagi aqlli, do'stona AI yordamchisan. "
    "Foydalanuvchi qaysi tilda yozsa, o'sha tilda javob ber (asosan o'zbek tilida). "
    "Aniq, tushunarli va foydali javob ber. Kod so'ralsa, to'liq ishlaydigan kod yoz "
    "va uni ``` bloklarida ber."
)

BASE = "https://api.groq.com/openai/v1"
CHAT_URL = f"{BASE}/chat/completions"
STT_URL = f"{BASE}/audio/transcriptions"
MODELS_URL = f"{BASE}/models"
HEADERS = {"Authorization": f"Bearer {GROQ_KEY}"}

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gptbot")

# ---------- Model tanlash ----------
CHAT_PREFERRED = ["llama-3.3-70b-versatile", "openai/gpt-oss-120b",
                  "llama-3.1-8b-instant", "openai/gpt-oss-20b"]
VISION_PREFERRED = ["meta-llama/llama-4-scout-17b-16e-instruct",
                    "meta-llama/llama-4-maverick-17b-128e-instruct"]

def fetch_model_ids():
    try:
        r = httpx.get(MODELS_URL, headers=HEADERS, timeout=20)
        ids = [m["id"] for m in r.json().get("data", [])]
        log.info("Mavjud modellar: %s", ids)
        return ids
    except Exception as e:
        log.error("Model ro'yxati xato: %s", e)
        return []

def pick_models():
    global CHAT_MODEL, VISION_MODEL
    ids = fetch_model_ids()

    if os.getenv("CHAT_MODEL"):
        CHAT_MODEL = os.getenv("CHAT_MODEL")
    elif ids:
        found = next((m for m in CHAT_PREFERRED if m in ids), None)
        if not found:
            others = [i for i in ids if not any(x in i for x in
                      ("whisper", "guard", "tts", "playai", "orpheus"))]
            found = others[0] if others else CHAT_MODEL
        CHAT_MODEL = found

    if os.getenv("VISION_MODEL"):
        VISION_MODEL = os.getenv("VISION_MODEL")
    elif ids:
        found = next((m for m in VISION_PREFERRED if m in ids), None)
        if not found:
            found = next((i for i in ids if "llama-4" in i or "vision" in i), None)
        VISION_MODEL = found or VISION_MODEL

    log.info("Chat model: %s | Vision model: %s", CHAT_MODEL, VISION_MODEL)

# ---------- Flask keep-alive ----------
app = Flask(__name__)

@app.route("/")
def home():
    return "OK"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

# ---------- SQLite ----------
db = sqlite3.connect("bot.db", check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS msgs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid INTEGER, role TEXT, content TEXT)""")
db.execute("CREATE INDEX IF NOT EXISTS i_uid ON msgs(uid)")
db.commit()

def get_history(uid):
    rows = db.execute(
        "SELECT role, content FROM msgs WHERE uid=? ORDER BY id DESC LIMIT ?",
        (uid, HISTORY_LIMIT)).fetchall()
    return [{"role": r, "content": c} for r, c in reversed(rows)]

def add_msg(uid, role, content):
    db.execute("INSERT INTO msgs(uid, role, content) VALUES(?,?,?)", (uid, role, content))
    db.execute("""DELETE FROM msgs WHERE uid=? AND id NOT IN
        (SELECT id FROM msgs WHERE uid=? ORDER BY id DESC LIMIT ?)""",
        (uid, uid, HISTORY_LIMIT))
    db.commit()

def clear_history(uid):
    db.execute("DELETE FROM msgs WHERE uid=?", (uid,))
    db.commit()

# ---------- Yordamchilar ----------
HTTP = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0))
locks = {}

def user_lock(uid):
    if uid not in locks:
        locks[uid] = asyncio.Lock()
    return locks[uid]

def to_html(t):
    t = html.escape(t, quote=False)
    store = []

    def stash(s):
        store.append(s)
        return f"\x00{len(store) - 1}\x00"

    t = re.sub(r"```\w*\n?(.*?)```",
               lambda m: stash("<pre>" + m.group(1).strip("\n") + "</pre>"), t, flags=re.S)
    t = re.sub(r"`([^`\n]+)`", lambda m: stash("<code>" + m.group(1) + "</code>"), t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", t, flags=re.M)
    t = re.sub(r"\x00(\d+)\x00", lambda m: store[int(m.group(1))], t)
    return t

def split_text(text, size=3800):
    chunks = []
    while len(text) > size:
        cut = text.rfind("\n", 0, size)
        if cut < size // 2:
            cut = size
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    chunks.append(text)
    return chunks

async def deliver(sent, text):
    chunks = split_text(text.strip() or "…")
    for i, c in enumerate(chunks):
        done = False
        for mode in ("HTML", None):
            try:
                body = to_html(c) if mode else c
                if i == 0:
                    await sent.edit_text(body, parse_mode=mode)
                else:
                    await sent.chat.send_message(body, parse_mode=mode)
                done = True
                break
            except BadRequest as e:
                if "not modified" in str(e).lower():
                    done = True
                    break
                continue
            except Exception as e:
                log.warning("deliver xato: %s", e)
                continue
        if not done:
            log.error("Xabar yuborilmadi")

async def stream_reply(message, messages, model):
    sent = await message.reply_text("…")
    full, last = "", 0.0
    payload = {"model": model, "messages": messages, "stream": True,
               "temperature": 0.7, "max_tokens": 4096}
    try:
        async with HTTP.stream("POST", CHAT_URL, headers=HEADERS, json=payload) as r:
            if r.status_code != 200:
                body = (await r.aread()).decode(errors="ignore")[:300]
                raise RuntimeError(f"Groq {r.status_code}: {body}")
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0]["delta"].get("content") or ""
                except Exception:
                    continue
                full += delta
                if full and time.time() - last > 1.4:
                    last = time.time()
                    try:
                        await sent.edit_text(full[:4000] + " ▌")
                    except Exception:
                        pass
    except Exception as e:
        log.error("Stream xato: %s", e)
        if not full:
            await sent.edit_text("⚠️ Xatolik yuz berdi, birozdan so'ng qayta urinib ko'ring.")
            return None
    await deliver(sent, full)
    return full

async def transcribe(audio_bytes, filename):
    r = await HTTP.post(
        STT_URL, headers=HEADERS,
        files={"file": (filename, audio_bytes, "application/octet-stream")},
        data={"model": STT_MODEL, "response_format": "json"})
    if r.status_code != 200:
        raise RuntimeError(r.text[:200])
    return r.json().get("text", "").strip()

# ---------- Handlerlar ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Salom! Men AI yordamchiman.\n\n"
        "✍️ Matn yozing — javob beraman\n"
        "🎤 Ovozli xabar yuboring — tushunaman\n"
        "🖼 Rasm yuboring — tahlil qilaman\n"
        "📄 Fayl (txt, py, md, csv...) yuboring — o'qiyman\n\n"
        "/new — yangi suhbat boshlash")

async def new_chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    clear_history(update.effective_user.id)
    await update.message.reply_text("🧹 Yangi suhbat boshlandi.")

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    async with user_lock(uid):
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + get_history(uid) \
               + [{"role": "user", "content": text}]
        ans = await stream_reply(update.message, msgs, CHAT_MODEL)
        if ans:
            add_msg(uid, "user", text)
            add_msg(uid, "assistant", ans)

async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    m = update.message
    media = m.voice or m.audio
    if media.file_size and media.file_size > 20 * 1024 * 1024:
        return await m.reply_text("⚠️ Fayl juda katta (max 20MB).")
    async with user_lock(uid):
        try:
            f = await media.get_file()
            data = bytes(await f.download_as_bytearray())
            text = await transcribe(data, "audio.ogg")
        except Exception as e:
            log.error("STT xato: %s", e)
            return await m.reply_text("⚠️ Ovozni tushunib bo'lmadi.")
        if not text:
            return await m.reply_text("⚠️ Ovozdan matn topilmadi.")
        await m.reply_text(f"🎤 {text}")
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + get_history(uid) \
               + [{"role": "user", "content": text}]
        ans = await stream_reply(m, msgs, CHAT_MODEL)
        if ans:
            add_msg(uid, "user", text)
            add_msg(uid, "assistant", ans)

async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    m = update.message
    caption = m.caption or "Bu rasmda nima bor? Batafsil tushuntir."
    async with user_lock(uid):
        try:
            f = await m.photo[-1].get_file()
            b64 = base64.b64encode(bytes(await f.download_as_bytearray())).decode()
        except Exception as e:
            log.error("Rasm xato: %s", e)
            return await m.reply_text("⚠️ Rasmni yuklab bo'lmadi.")
        content = [{"type": "text", "text": caption},
                   {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + get_history(uid) \
               + [{"role": "user", "content": content}]
        ans = await stream_reply(m, msgs, VISION_MODEL)
        if ans:
            add_msg(uid, "user", f"[rasm yuborildi] {caption}")
            add_msg(uid, "assistant", ans)

async def on_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    m = update.message
    doc = m.document
    if doc.file_size and doc.file_size > 1024 * 1024:
        return await m.reply_text("⚠️ Fayl juda katta (max 1MB).")
    async with user_lock(uid):
        try:
            f = await doc.get_file()
            raw = bytes(await f.download_as_bytearray())
            content = raw.decode("utf-8", errors="ignore")[:12000]
        except Exception:
            return await m.reply_text("⚠️ Faylni o'qib bo'lmadi.")
        if not content.strip():
            return await m.reply_text("⚠️ Fayl bo'sh yoki matn emas.")
        task = m.caption or "Ushbu faylni tahlil qil va qisqacha tushuntir."
        prompt = f"{task}\n\nFayl: {doc.file_name}\n```\n{content}\n```"
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + get_history(uid) \
               + [{"role": "user", "content": prompt}]
        ans = await stream_reply(m, msgs, CHAT_MODEL)
        if ans:
            add_msg(uid, "user", f"[fayl: {doc.file_name}] {task}")
            add_msg(uid, "assistant", ans)

def main():
    pick_models()
    Thread(target=run_flask, daemon=True).start()
    application = (Application.builder().token(BOT_TOKEN)
                   .concurrent_updates(True).build())
    priv = filters.ChatType.PRIVATE
    application.add_handler(CommandHandler("start", start, filters=priv))
    application.add_handler(CommandHandler("new", new_chat, filters=priv))
    application.add_handler(MessageHandler(priv & filters.TEXT & ~filters.COMMAND, on_text))
    application.add_handler(MessageHandler(priv & (filters.VOICE | filters.AUDIO), on_voice))
    application.add_handler(MessageHandler(priv & filters.PHOTO, on_photo))
    application.add_handler(MessageHandler(priv & filters.Document.ALL, on_document))
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
