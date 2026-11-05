# bot.py — AI Super Bot (bitta fayl)
import os, re, io, json, html, base64, sqlite3, asyncio, logging, time, random, uuid, traceback
from datetime import datetime, timedelta, timezone
from threading import Thread
from urllib.parse import quote, unquote, urlparse, parse_qs
import httpx
from flask import Flask
from telegram import (Update, InlineKeyboardButton as _InlineKeyboardButton, InlineKeyboardMarkup as Kb,
                      LabeledPrice, InlineQueryResultArticle, InputTextMessageContent, BotCommand)
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import (Application, CommandHandler, MessageHandler, CallbackQueryHandler,
                          InlineQueryHandler, PreCheckoutQueryHandler, filters, ContextTypes)

# Ikkinchi argument callback_data; URL faqat url= orqali beriladi.
def Btn(text, data=None, *, url=None):
    return _InlineKeyboardButton(text=text, callback_data=data, url=url)

# ================= SOZLAMALAR =================
BOT_TOKEN = os.environ["BOT_TOKEN"]
KEYS = [k.strip() for k in os.environ["GROQ_API_KEY"].split(",") if k.strip()]  # bir nechta kalit: vergul bilan
ADMINS = {int(x) for x in re.findall(r"\d+", os.getenv("ADMIN_IDS", ""))}
CHANNELS = [c.strip() for c in os.getenv("CHANNELS", "").split(",") if c.strip()]  # @kanal1,@kanal2
CARD = os.getenv("CARD_NUMBER", "")
CARD_OWNER = os.getenv("CARD_OWNER", "")
TAVILY = os.getenv("TAVILY_API_KEY", "")
ADS = os.getenv("ADS_TEXT", "")
DB_PATH = os.getenv("DB_PATH", "bot.db")
STT_MODEL = os.getenv("STT_MODEL", "whisper-large-v3-turbo")
START_BONUS = int(os.getenv("START_BONUS", "10"))
DAILY_BONUS = int(os.getenv("DAILY_BONUS", "5"))
REF_BONUS = int(os.getenv("REF_BONUS", "10"))
HISTORY_LIMIT = 16

PLANS = {
    "free": {"name": "Free", "emoji": "🆓", "limit": int(os.getenv("LIMIT_FREE", "15"))},
    "pro": {"name": "Pro", "emoji": "💎", "limit": int(os.getenv("LIMIT_PRO", "150")),
            "price": int(os.getenv("PRICE_PRO", "29000")), "stars": int(os.getenv("STARS_PRO", "150"))},
    "premium": {"name": "Premium", "emoji": "👑", "limit": int(os.getenv("LIMIT_PREMIUM", "1000")),
                "price": int(os.getenv("PRICE_PREMIUM", "59000")), "stars": int(os.getenv("STARS_PREMIUM", "300"))},
}

ROLES = {
    "default": ("🤖 Universal", "Sen aqlli, do'stona universal yordamchisan."),
    "dev": ("👨‍💻 Dasturchi", "Sen senior dasturchisan. To'liq ishlaydigan, toza kod yoz, qisqa tushuntir."),
    "teacher": ("👩‍🏫 O'qituvchi", "Sen sabrli o'qituvchisan. Mavzuni oddiy tilda, misollar bilan tushuntir, oxirida bitta tekshiruv savoli ber."),
    "psy": ("🧘 Psixolog", "Sen mehribon, yaxshi tinglaydigan yordamchisan. Tashxis qo'yma; jiddiy holatda mutaxassisga murojaat qilishni maslahat ber."),
    "eng": ("🇬🇧 Ingliz tili ustozi", "Sen ingliz tili ustozisan. Xatolarni tuzat, sababini qisqa tushuntir, yangi so'zlar va misollar ber."),
    "ielts": ("🎓 IELTS ustozi", "Sen IELTS ekspertisan. Writing/Speaking javoblarini band bo'yicha baholab, aniq tavsiyalar ber."),
    "biz": ("💼 Biznes maslahatchi", "Sen tajribali biznes maslahatchisan. Aniq qadamlar, raqamlar va xavflarni ko'rsat. O'zbekiston bozorini hisobga ol."),
    "law": ("⚖️ Huquq (UZ)", "Sen O'zbekiston qonunchiligi bo'yicha umumiy ma'lumot beruvchisan. Bu rasmiy yuridik maslahat emasligini eslat."),
    "med": ("🩺 Salomatlik", "Sen salomatlik bo'yicha umumiy ma'lumot beruvchisan. Shifokor o'rnini bosmasligini eslat, xavfli belgilarda shifokorga yo'nalt."),
    "cv": ("📋 Resume/CV", "Sen HR mutaxassisisan. Professional resume, cover letter va intervyu tayyorgarligida yordam ber."),
    "fun": ("😄 Hazilkash", "Sen quvnoq, hazilkash do'stsan. Qisqa, kulgili, lekin foydali javob ber."),
}
BASE_SYS = ("Foydalanuvchi qaysi tilda yozsa, o'sha tilda javob ber (asosan o'zbek, lotin yozuvida). "
            "Aniq va foydali bo'l. Kod so'ralsa, to'liq kodni ``` bloklarida ber.")

BASE = "https://api.groq.com/openai/v1"
CHAT_URL, STT_URL = f"{BASE}/chat/completions", f"{BASE}/audio/transcriptions"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
TZ = timezone(timedelta(hours=5))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aibot")

def now(): return int(time.time())
def today(): return datetime.now(TZ).strftime("%Y-%m-%d")
def esc(s): return html.escape(str(s or ""), quote=False)

# ================= FLASK =================
app_flask = Flask(__name__)
@app_flask.route("/")
def home(): return "OK"
def run_flask(): app_flask.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

# ================= BAZA =================
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript(f"""
CREATE TABLE IF NOT EXISTS users(
 id INTEGER PRIMARY KEY, name TEXT, username TEXT, created INT, last_seen INT,
 plan TEXT DEFAULT 'free', plan_until INT DEFAULT 0, used INT DEFAULT 0, day TEXT,
 bonus INT DEFAULT {START_BONUS}, banned INT DEFAULT 0, role TEXT DEFAULT 'default',
 mode TEXT DEFAULT 'chat', search INT DEFAULT 0, voice INT DEFAULT 0, memon INT DEFAULT 1,
 model TEXT DEFAULT '', memory TEXT DEFAULT '', ref_by INT DEFAULT 0, refs INT DEFAULT 0,
 last_bonus TEXT DEFAULT '', total INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS msgs(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INT, role TEXT, content TEXT);
CREATE INDEX IF NOT EXISTS i_uid ON msgs(uid);
CREATE TABLE IF NOT EXISTS docs(uid INTEGER PRIMARY KEY, name TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INT, plan TEXT, days INT,
 amount INT, status TEXT, ts INT, file_id TEXT);
CREATE TABLE IF NOT EXISTS promos(code TEXT PRIMARY KEY, bonus INT, max_uses INT, used INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS promo_used(code TEXT, uid INT);
CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INT, ts INT, text TEXT, done INT DEFAULT 0);
""")
db.commit()

def q(sql, a=()): return db.execute(sql, a).fetchall()
def q1(sql, a=()):
    r = db.execute(sql, a).fetchone()
    return dict(r) if r else None
def ex(sql, a=()):
    cur = db.execute(sql, a); db.commit(); return cur
def setu(uid, **kw):
    ex("UPDATE users SET " + ",".join(f"{k}=?" for k in kw) + " WHERE id=?", (*kw.values(), uid))
def fresh(uid): return q1("SELECT * FROM users WHERE id=?", (uid,))

def get_user(tg):
    u = q1("SELECT * FROM users WHERE id=?", (tg.id,))
    if not u:
        ex("INSERT INTO users(id,name,username,created,last_seen,day) VALUES(?,?,?,?,?,?)",
           (tg.id, tg.full_name, tg.username or "", now(), now(), today()))
        return fresh(tg.id)
    if u["plan"] != "free" and u["plan_until"] < now():
        setu(tg.id, plan="free"); u["plan"] = "free"
    if u["day"] != today():
        setu(tg.id, used=0, day=today()); u["used"] = 0
    ex("UPDATE users SET last_seen=?, name=?, username=? WHERE id=?", (now(), tg.full_name, tg.username or "", tg.id))
    return u

def can_use(u, cost):
    return u["id"] in ADMINS or PLANS[u["plan"]]["limit"] - u["used"] + u["bonus"] >= cost

def consume(u, cost):
    if u["id"] in ADMINS:
        ex("UPDATE users SET total=total+1 WHERE id=?", (u["id"],)); return
    daily = max(0, PLANS[u["plan"]]["limit"] - u["used"])
    fd = min(daily, cost); fb = cost - fd
    ex("UPDATE users SET used=used+?, bonus=bonus-?, total=total+1 WHERE id=?", (fd, fb, u["id"]))
    u["used"] += fd; u["bonus"] -= fb

def grant_plan(uid, plan, days):
    u = fresh(uid)
    base = max(now(), u["plan_until"]) if u["plan"] == plan else now()
    setu(uid, plan=plan, plan_until=base + days * 86400)

def get_history(uid):
    rows = q("SELECT role, content FROM msgs WHERE uid=? ORDER BY id DESC LIMIT ?", (uid, HISTORY_LIMIT))
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
def add_msg(uid, role, content):
    ex("INSERT INTO msgs(uid,role,content) VALUES(?,?,?)", (uid, role, content))
    ex("DELETE FROM msgs WHERE uid=? AND id NOT IN (SELECT id FROM msgs WHERE uid=? ORDER BY id DESC LIMIT ?)",
       (uid, uid, HISTORY_LIMIT))
def clear_history(uid): ex("DELETE FROM msgs WHERE uid=?", (uid,))

# ================= GROQ / MODELLAR =================
HTTP = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0))
CHAT_PREF = ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "llama-3.1-8b-instant", "openai/gpt-oss-20b",
             "meta-llama/llama-4-scout-17b-16e-instruct"]
VISION_PREF = ["meta-llama/llama-4-scout-17b-16e-instruct", "meta-llama/llama-4-maverick-17b-128e-instruct"]
SKIP = ("whisper", "guard", "tts", "playai", "orpheus", "allam")
CHAT_MODELS, VISION_MODELS, FAST = list(CHAT_PREF), list(VISION_PREF), "llama-3.1-8b-instant"
key_i = 0

def hdr(): return {"Authorization": f"Bearer {KEYS[key_i % len(KEYS)]}"}
def rotate():
    global key_i
    key_i += 1

def init_models():
    global CHAT_MODELS, VISION_MODELS, FAST
    try:
        ids = [m["id"] for m in httpx.get(f"{BASE}/models", headers=hdr(), timeout=20).json().get("data", [])]
    except Exception as e:
        log.error("Model ro'yxati xato: %s", e); ids = []
    log.info("Mavjud modellar: %s", ids)
    if ids:
        chat = [m for m in CHAT_PREF if m in ids] or [i for i in ids if not any(x in i for x in SKIP)]
        vis = [m for m in VISION_PREF if m in ids] or [i for i in ids if "llama-4" in i]
        CHAT_MODELS = chat or CHAT_MODELS
        VISION_MODELS = vis or VISION_MODELS
    if os.getenv("CHAT_MODEL"): CHAT_MODELS.insert(0, os.getenv("CHAT_MODEL"))
    if os.getenv("VISION_MODEL"): VISION_MODELS.insert(0, os.getenv("VISION_MODEL"))
    FAST = "llama-3.1-8b-instant" if "llama-3.1-8b-instant" in CHAT_MODELS else CHAT_MODELS[-1]
    log.info("Chat: %s | Vision: %s | Fast: %s", CHAT_MODELS, VISION_MODELS, FAST)

def models_for(u):
    first = [u["model"]] if u["model"] in CHAT_MODELS else []
    return first + [m for m in CHAT_MODELS if m not in first]

async def chat_stream(messages, models, on_delta):
    err = None
    for model in models:
        for _ in range(len(KEYS)):
            full = ""
            try:
                p = {"model": model, "messages": messages, "stream": True, "temperature": 0.7, "max_tokens": 4096}
                async with HTTP.stream("POST", CHAT_URL, headers=hdr(), json=p) as r:
                    if r.status_code != 200:
                        err = f"{r.status_code} {(await r.aread()).decode(errors='ignore')[:200]}"
                        log.warning("Groq %s: %s", model, err)
                        if r.status_code in (401, 429):
                            rotate(); continue
                        break
                    async for line in r.aiter_lines():
                        if not line.startswith("data: "): continue
                        d = line[6:].strip()
                        if d == "[DONE]": break
                        try: delta = json.loads(d)["choices"][0]["delta"].get("content") or ""
                        except Exception: continue
                        full += delta
                        await on_delta(full)
                    return full, model
            except Exception as e:
                err = e
                if full: return full, model
                break
    raise RuntimeError(err)

async def llm(messages, models=None, json_mode=False, max_tokens=1500, temperature=0.5):
    models = models or ([FAST] + CHAT_MODELS)
    err = None
    for model in models:
        for _ in range(len(KEYS)):
            p = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
            if json_mode: p["response_format"] = {"type": "json_object"}
            try:
                r = await HTTP.post(CHAT_URL, headers=hdr(), json=p)
            except Exception as e:
                err = e; break
            if r.status_code == 200:
                return r.json()["choices"][0]["message"].get("content") or ""
            err = f"{r.status_code} {r.text[:150]}"
            if r.status_code in (401, 429):
                rotate(); continue
            break
    raise RuntimeError(err)

async def transcribe(audio, filename="audio.ogg"):
    for _ in range(len(KEYS)):
        r = await HTTP.post(STT_URL, headers=hdr(), files={"file": (filename, audio, "application/octet-stream")},
                            data={"model": STT_MODEL, "response_format": "json"})
        if r.status_code == 200: return r.json().get("text", "").strip()
        if r.status_code in (401, 429): rotate(); continue
        break
    raise RuntimeError(r.text[:200])

# ================= MATN YORDAMCHILARI =================
def to_html(t):
    t = html.escape(t, quote=False); store = []
    def stash(s):
        store.append(s); return f"\x00{len(store) - 1}\x00"
    t = re.sub(r"```\w*\n?(.*?)```", lambda m: stash("<pre>" + m.group(1).strip("\n") + "</pre>"), t, flags=re.S)
    t = re.sub(r"`([^`\n]+)`", lambda m: stash("<code>" + m.group(1) + "</code>"), t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", t, flags=re.M)
    return re.sub(r"\x00(\d+)\x00", lambda m: store[int(m.group(1))], t)

def split_text(text, size=3800):
    chunks = []
    while len(text) > size:
        cut = text.rfind("\n", 0, size)
        if cut < size // 2: cut = size
        chunks.append(text[:cut]); text = text[cut:].lstrip("\n")
    chunks.append(text); return chunks

async def deliver(sent, text, kb=None):
    chunks = split_text(text.strip() or "…")
    for i, c in enumerate(chunks):
        mk = kb if i == len(chunks) - 1 else None
        for mode in ("HTML", None):
            try:
                body = to_html(c) if mode else c
                if i == 0: await sent.edit_text(body, parse_mode=mode, reply_markup=mk)
                else: await sent.chat.send_message(body, parse_mode=mode, reply_markup=mk)
                break
            except BadRequest as e:
                if "not modified" in str(e).lower(): break
            except Exception as e:
                log.warning("deliver: %s", e)

async def stream_reply(m, messages, models, kb=None, suffix=""):
    sent = await m.reply_text("⏳")
    last = [0.0]
    async def on_delta(full):
        if time.time() - last[0] > 1.5:
            last[0] = time.time()
            try: await sent.edit_text(full[-3900:] + " ▌")
            except Exception: pass
    try:
        full, model = await chat_stream(messages, models, on_delta)
    except Exception as e:
        log.error("Stream xato: %s", e)
        await sent.edit_text("⚠️ Server band. Birozdan so'ng qayta urinib ko'ring.")
        return None
    await deliver(sent, (full.strip() or "…") + suffix, kb)
    return full

BG = set()
def bg(coro):
    t = asyncio.create_task(coro); BG.add(t); t.add_done_callback(BG.discard)

def sys_prompt(u, query=""):
    s = BASE_SYS + "\nHozirgi sana: " + datetime.now(TZ).strftime("%Y-%m-%d %H:%M") + " (Toshkent)."
    s += "\nRol: " + ROLES.get(u["role"], ROLES["default"])[1]
    if u["memon"] and u["memory"]: s += "\nFoydalanuvchi haqida eslab qolingan: " + u["memory"]
    d = q1("SELECT name, text FROM docs WHERE uid=?", (u["id"],))
    if d:
        t = d["text"]
        if len(t) > 8000:
            chunks = [t[i:i + 1800] for i in range(0, len(t), 1800)]
            words = {w for w in re.findall(r"\w{4,}", query.lower())}
            scored = sorted(range(1, len(chunks)), key=lambda i: -sum(1 for w in words if w in chunks[i].lower()))[:3]
            t = "\n...\n".join(chunks[i] for i in [0] + sorted(scored))
        s += f"\n\nFoydalanuvchi yuklagan hujjat ({d['name']}) mazmuni:\n{t}"
    return s

# ================= QIDIRUV / HAVOLA / HUJJAT =================
async def web_search(query):
    try:
        if TAVILY:
            r = await HTTP.post("https://api.tavily.com/search", timeout=30,
                                json={"api_key": TAVILY, "query": query, "max_results": 5, "include_answer": True})
            d = r.json(); out = []
            if d.get("answer"): out.append("Qisqa javob: " + d["answer"])
            for x in d.get("results", [])[:5]:
                out.append(f"- {x['title']} ({x['url']}): {x['content'][:400]}")
            return "\n".join(out)
        r = await HTTP.get("https://html.duckduckgo.com/html/", params={"q": query}, headers={"User-Agent": UA}, timeout=20)
        items = re.findall(r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
                           r.text, flags=re.S)
        out = []
        for href, title, snip in items[:5]:
            if "uddg=" in href: href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
            cl = lambda s: html.unescape(re.sub(r"<[^>]+>", "", s)).strip()
            out.append(f"- {cl(title)} ({href}): {cl(snip)[:400]}")
        return "\n".join(out)
    except Exception as e:
        log.warning("Qidiruv xato: %s", e); return ""

async def fetch_page(url):
    r = await HTTP.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=25)
    t = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer)[^>]*>.*?</\1>", " ", r.text)
    tm = re.search(r"(?is)<title[^>]*>(.*?)</title>", t)
    title = html.unescape(tm.group(1)).strip() if tm else url
    t = html.unescape(re.sub(r"(?s)<[^>]+>", " ", t))
    return title, re.sub(r"\s+", " ", t).strip()[:9000]

def yt_id(url):
    m = re.search(r"(?:youtu\.be/|v=|shorts/)([\w-]{11})", url)
    return m.group(1) if m else None

def yt_transcript(vid):
    from youtube_transcript_api import YouTubeTranscriptApi as Y
    langs = ["uz", "ru", "en"]
    try:
        data = Y().fetch(vid, languages=langs)
        return " ".join(getattr(x, "text", None) or x["text"] for x in data)[:12000]
    except Exception:
        data = Y.get_transcript(vid, languages=langs)
        return " ".join(x["text"] for x in data)[:12000]

def extract_doc(name, raw):
    n = name.lower()
    if n.endswith(".pdf"):
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(raw)).pages[:80])
    if n.endswith(".docx"):
        import docx
        d = docx.Document(io.BytesIO(raw)); parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for r in t.rows: parts.append(" | ".join(c.text for c in r.cells))
        return "\n".join(parts)
    if n.endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True); out = []
        for ws in wb.worksheets[:5]:
            out.append(f"## {ws.title}")
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i > 300: break
                out.append(" | ".join("" if c is None else str(c) for c in row))
        return "\n".join(out)
    return raw.decode("utf-8", "ignore")

# ================= OVOZ (TTS) =================
async def tts_bytes(text):
    import edge_tts
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"[*_`#]", "", text)[:1500]
    cyr = len(re.findall(r"[а-яА-ЯёЁ]", text))
    en = len(re.findall(r"\b(the|is|and|you|to|of|what|how|are|this)\b", text.lower()))
    voice = "ru-RU-SvetlanaNeural" if cyr > len(text) * 0.3 else ("en-US-JennyNeural" if en >= 3 else "uz-UZ-MadinaNeural")
    buf = bytearray()
    async for ch in edge_tts.Communicate(text, voice).stream():
        if ch["type"] == "audio": buf += ch["data"]
    return bytes(buf)

# ================= KLAVIATURALAR / MATNLAR =================
def menu_text(u, note=""):
    p = PLANS[u["plan"]]
    until = f" (→ {datetime.fromtimestamp(u['plan_until'], TZ):%d.%m.%Y})" if u["plan"] != "free" else ""
    return (f"{note}✨ <b>AI Yordamchi</b>\n\n"
            f"🎭 Rol: <b>{ROLES.get(u['role'], ROLES['default'])[0]}</b>\n"
            f"{p['emoji']} Tarif: <b>{p['name']}</b>{until}\n"
            f"⚡ Bugun: <b>{u['used']}/{p['limit']}</b> · 🎁 Bonus: <b>{u['bonus']}</b>\n\n"
            "Savol yozing, 🎤 ovoz, 🖼 rasm yoki 📄 fayl yuboring 👇")

def main_kb(u, admin=False):
    on = lambda v: "✅" if v else "▫️"
    rows = [[Btn("💬 Yangi suhbat", "m:new"), Btn("🎭 Rollar", "m:roles")],
            [Btn("🎨 Rasm yaratish", "m:img"), Btn("🌐 Tarjimon", "m:tr")],
            [Btn("📄 Hujjat yozish", "m:doc"), Btn("🧩 Viktorina", "m:quiz")],
            [Btn("📚 Uy vazifasi", "m:hw"), Btn(f"{on(u['search'])} Web qidiruv", "m:search")],
            [Btn(f"{on(u['voice'])} Ovozli javob", "m:voice"), Btn("🧠 Xotira", "m:mem")],
            [Btn("👤 Profil", "m:prof"), Btn("💎 Tariflar", "m:plans")],
            [Btn("👥 Do'st taklif", "m:ref"), Btn("🎁 Kunlik bonus", "m:bonus")],
            [Btn("🎟 Promokod", "m:promo"), Btn("⚙️ Sozlamalar", "m:set")]]
    if admin: rows.append([Btn("🛠 Admin panel", "adm:home")])
    return Kb(rows)

ANS_KB = Kb([[Btn("🔊 Ovozlash", "tts"), Btn("🏠 Menyu", "m:home")]])
BACK = Kb([[Btn("◀️ Orqaga", "m:home")]])

async def show(update, text, kb=None):
    cq = update.callback_query
    if cq:
        try:
            await cq.edit_message_text(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                await cq.message.reply_text(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    else:
        await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)

async def paywall(m):
    await m.reply_text("⚠️ <b>Limit tugadi.</b>\n\nBugungi xabarlaringiz tugadi. Tanlang 👇", parse_mode="HTML",
                       reply_markup=Kb([[Btn("💎 Tariflar", "m:plans")],
                                        [Btn("👥 Do'st taklif +bonus", "m:ref"), Btn("🎁 Kunlik bonus", "m:bonus")]]))

async def missing_subs(bot, uid):
    bad = []
    for ch in CHANNELS:
        try:
            mem = await bot.get_chat_member(ch, uid)
            if mem.status in ("left", "kicked"): bad.append(ch)
        except Exception as e:
            log.warning("Obuna tekshiruv %s: %s", ch, e)
    return bad

async def sub_wall(m, ctx, uid):
    if uid in ADMINS or not CHANNELS: return False
    miss = await missing_subs(ctx.bot, uid)
    if not miss: return False
    rows = [[Btn(f"📢 {c}", url="https://t.me/" + c.lstrip("@"))] for c in miss] + [[Btn("✅ Tekshirish", "chk")]]
    await m.reply_text("🔒 Botdan foydalanish uchun kanallarga obuna bo'ling:", reply_markup=Kb(rows))
    return True

last_hit = {}
async def gate(update, ctx, cost=1):
    tg, m = update.effective_user, update.effective_message
    u = get_user(tg)
    if u["banned"]:
        await m.reply_text("🚫 Siz bloklangansiz."); return None
    t = time.time()
    if t - last_hit.get(tg.id, 0) < 1.0 and tg.id not in ADMINS: return None
    last_hit[tg.id] = t
    if await sub_wall(m, ctx, tg.id): return None
    if not can_use(u, cost):
        await paywall(m); return None
    return u

async def afford(m, u, cost):
    if can_use(u, cost): return True
    await paywall(m); return False

# ================= ASOSIY OQIM =================
locks = {}
def user_lock(uid):
    if uid not in locks: locks[uid] = asyncio.Lock()
    return locks[uid]

async def chat_flow(m, ctx, u, text, extra="", cost=1):
    uid = u["id"]
    async with user_lock(uid):
        user_text = text
        if extra: user_text = f"{text}\n\n{extra}"
        elif u["search"]:
            await m.chat.send_action(ChatAction.TYPING)
            res = await web_search(text)
            if res: user_text = f"{text}\n\n[Internetdan topilgan ma'lumotlar — ulardan foydalanib javob ber va manbalarni ayt]\n{res}"
        msgs = [{"role": "system", "content": sys_prompt(u, text)}] + get_history(uid) + [{"role": "user", "content": user_text}]
        n = u["total"] + 1
        suffix = "\n\n📢 " + ADS if (u["plan"] == "free" and ADS and n % 5 == 0) else ""
        full = await stream_reply(m, msgs, models_for(u), ANS_KB, suffix)
        if not full: return
        consume(u, cost); add_msg(uid, "user", text); add_msg(uid, "assistant", full)
        if u["voice"]:
            try: await m.reply_voice(await tts_bytes(full))
            except Exception as e: log.warning("TTS: %s", e)
        if u["memon"] and n % 6 == 0: bg(update_memory(uid))

async def update_memory(uid):
    try:
        u = fresh(uid)
        conv = "\n".join(f"{h['role']}: {h['content'][:300]}" for h in get_history(uid)[-8:])
        old = u["memory"] or "(bo'sh)"
        new = await llm([{"role": "system", "content": "Foydalanuvchi haqidagi MUHIM doimiy faktlarni (ism, kasb, shahar, qiziqish, maqsad) qisqa ro'yxat qilib yangila. Parol, karta, pasport, salomatlik kabi maxfiy narsalarni yozma. Faqat yangilangan ro'yxatni qaytar (600 belgigacha). Yangi ma'lumot bo'lmasa avvalgisini qaytar."},
                         {"role": "user", "content": f"Avvalgi xotira:\n{old}\n\nSuhbat:\n{conv}"}], models=[FAST], max_tokens=300)
        setu(uid, memory=new.strip()[:700])
    except Exception as e:
        log.warning("Xotira xato: %s", e)

async def link_flow(m, ctx, u, text, url):
    wait = await m.reply_text("🔗 Sahifani o'qiyapman...")
    try:
        vid = yt_id(url)
        if vid: title, body = "YouTube video", await asyncio.to_thread(yt_transcript, vid)
        else: title, body = await fetch_page(url)
    except Exception as e:
        log.warning("Havola xato: %s", e)
        await wait.edit_text("⚠️ Havolani o'qib bo'lmadi (yopiq yoki subtitr yo'q)."); return
    await wait.delete()
    task = text.replace(url, "").strip() or "Qisqacha xulosa qil: asosiy g'oyalar ro'yxati bilan."
    await chat_flow(m, ctx, u, task, extra=f"[Havola: {url}\nSarlavha: {title}\nMazmuni:\n{body}]")

async def make_image(m, ctx, u, prompt):
    await m.chat.send_action(ChatAction.UPLOAD_PHOTO)
    wait = await m.reply_text("🎨 Chizyapman...")
    try:
        en = (await llm([{"role": "system", "content": "Translate the user's idea into one vivid, detailed English image-generation prompt. Output only the prompt."},
                         {"role": "user", "content": prompt}], max_tokens=200)).strip()
    except Exception:
        en = prompt
    ctx.user_data["last_img"] = prompt
    data = None
    for extra in ("&model=flux", ""):
        url = f"https://image.pollinations.ai/prompt/{quote(en)}?width=1024&height=1024&nologo=true&seed={random.randint(1, 10**6)}{extra}"
        try:
            r = await HTTP.get(url, timeout=120, follow_redirects=True)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                data = r.content; break
        except Exception as e:
            log.warning("Rasm xato: %s", e)
    try: await wait.delete()
    except Exception: pass
    if not data:
        await m.reply_text("⚠️ Rasm yaratib bo'lmadi, keyinroq urinib ko'ring."); return False
    await m.reply_photo(data, caption=f"🎨 {prompt[:200]}",
                        reply_markup=Kb([[Btn("🔄 Yana variant", "img:again"), Btn("🏠 Menyu", "m:home")]]))
    return True

async def make_docx(m, topic):
    wait = await m.reply_text("📝 Yozyapman...")
    try:
        md = await llm([{"role": "system", "content": "Sen professional muallifsan. Topshiriq bo'yicha to'liq hujjat yoz. Markdown: '# Sarlavha', '## Bo'lim', '- ro'yxat'. Foydalanuvchi tilida yoz (o'zbek bo'lsa lotin yozuvida)."},
                        {"role": "user", "content": topic}], models=CHAT_MODELS, max_tokens=3500, temperature=0.6)
        import docx
        d = docx.Document()
        for line in md.splitlines():
            s = line.strip()
            if not s: continue
            s2 = re.sub(r"\*\*|__|`", "", s)
            if s.startswith("### "): d.add_heading(s2[4:], 3)
            elif s.startswith("## "): d.add_heading(s2[3:], 2)
            elif s.startswith("# "): d.add_heading(s2[2:], 1)
            elif s[:2] in ("- ", "* "): d.add_paragraph(s2[2:], style="List Bullet")
            else: d.add_paragraph(s2)
        buf = io.BytesIO(); d.save(buf); buf.seek(0)
    except Exception as e:
        log.error("Docx xato: %s", e)
        await wait.edit_text("⚠️ Hujjat yaratib bo'lmadi."); return False
    name = re.sub(r"\W+", "_", topic)[:30].strip("_") or "hujjat"
    await wait.delete()
    await m.reply_document(buf, filename=f"{name}.docx", caption="📄 Tayyor!", reply_markup=Kb([[Btn("🏠 Menyu", "m:home")]]))
    return True

async def make_quiz(m, topic):
    wait = await m.reply_text("🧩 Savollar tuzyapman...")
    try:
        raw = await llm([{"role": "system", "content": "Faqat JSON qaytar."},
                         {"role": "user", "content": f'"{topic}" mavzusida 5 ta test savoli tuz (foydalanuvchi tilida). Format: {{"questions":[{{"q":"...","options":["a","b","c","d"],"answer":0,"explain":"..."}}]}}'}],
                        models=CHAT_MODELS, json_mode=True, max_tokens=2000)
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        sent = 0
        for it in data["questions"][:5]:
            opts = [str(o)[:100] for o in it["options"][:4]]
            ans = int(it["answer"])
            if len(opts) < 2 or ans >= len(opts): continue
            await m.chat.send_poll(question=str(it["q"])[:300], options=opts, type="quiz", correct_option_id=ans,
                                   explanation=str(it.get("explain") or "")[:190], is_anonymous=False)
            sent += 1
        await wait.delete()
        return sent > 0
    except Exception as e:
        log.error("Quiz xato: %s", e)
        await wait.edit_text("⚠️ Viktorina tuzib bo'lmadi, qayta urinib ko'ring."); return False

async def route(m, ctx, u, text):
    mode, uid = u["mode"], u["id"]
    if mode == "image":
        if not await afford(m, u, 3): return
        setu(uid, mode="chat")
        if await make_image(m, ctx, u, text): consume(u, 3)
    elif mode == "doc":
        if not await afford(m, u, 3): return
        setu(uid, mode="chat")
        if await make_docx(m, text): consume(u, 3)
    elif mode == "quiz":
        if not await afford(m, u, 2): return
        setu(uid, mode="chat")
        if await make_quiz(m, text): consume(u, 2)
    elif mode.startswith("tr:"):
        lang = {"uz": "o'zbek (lotin yozuvi)", "ru": "rus", "en": "ingliz"}.get(mode[3:], "ingliz")
        try:
            out = await llm([{"role": "system", "content": f"Sen professional tarjimonsan. Foydalanuvchi matnini {lang} tiliga tarjima qil. Faqat tarjimani yoz."},
                             {"role": "user", "content": text}], models=CHAT_MODELS, max_tokens=2000)
            await m.reply_text(out, reply_markup=Kb([[Btn("🔊", "tts"), Btn("🔁 Til", "m:tr"), Btn("🏠 Chiqish", "m:home")]]))
            consume(u, 1)
        except Exception:
            await m.reply_text("⚠️ Tarjima xatosi, qayta urinib ko'ring.")
    else:
        url = re.search(r"https?://\S+", text)
        if url and len(text.replace(url.group(0), "").strip()) < 60:
            await link_flow(m, ctx, u, text, url.group(0))
        else:
            await chat_flow(m, ctx, u, text)

# ================= HANDLERLAR =================
async def on_text(update, ctx):
    m = update.effective_message; text = m.text or ""
    if update.effective_chat.type != "private":
        uname = (ctx.bot.username or "").lower()
        replied = m.reply_to_message and m.reply_to_message.from_user and m.reply_to_message.from_user.id == ctx.bot.id
        if f"@{uname}" not in text.lower() and not replied: return
        text = re.sub(f"(?i)@{uname}", "", text).strip()
        if not text: return
    aw = ctx.user_data.get("await")
    if aw and await handle_await(update, ctx, aw, text): return
    u = await gate(update, ctx, 1)
    if u: await route(m, ctx, u, text)

async def handle_await(update, ctx, aw, text):
    m, uid = update.effective_message, update.effective_user.id
    if aw == "receipt":
        await m.reply_text("📸 To'lov chekining rasmini yuboring yoki /menu bosing."); return True
    if aw == "promo":
        ctx.user_data.pop("await", None); await redeem(m, uid, text); return True
    if uid in ADMINS:
        if aw == "adm_user":
            ctx.user_data.pop("await", None)
            ids = re.findall(r"\d+", text)
            t, kb = user_card(int(ids[0])) if ids else ("❌ ID kiriting", None)
            await m.reply_text(t, parse_mode="HTML", reply_markup=kb); return True
        if aw.startswith("bc:"):
            ctx.user_data.pop("await", None)
            bg(do_broadcast(ctx, uid, aw[3:], m)); await m.reply_text("📣 Yuborish boshlandi..."); return True
    return False

async def on_voice(update, ctx):
    m = update.effective_message; media = m.voice or m.audio
    u = await gate(update, ctx, 1)
    if not u: return
    if media.file_size and media.file_size > 20 * 1024 * 1024:
        return await m.reply_text("⚠️ Fayl juda katta (max 20MB).")
    try:
        f = await media.get_file()
        text = await transcribe(bytes(await f.download_as_bytearray()))
    except Exception as e:
        log.error("STT xato: %s", e)
        return await m.reply_text("⚠️ Ovozni tushunib bo'lmadi.")
    if not text: return await m.reply_text("⚠️ Ovozdan matn topilmadi.")
    await m.reply_text(f"🎤 {text}")
    await route(m, ctx, u, text)

async def on_photo(update, ctx):
    m, uid = update.effective_message, update.effective_user.id
    aw = ctx.user_data.get("await") or ""
    if aw == "receipt": return await receipt(update, ctx)
    if aw.startswith("bc:") and uid in ADMINS:
        ctx.user_data.pop("await"); bg(do_broadcast(ctx, uid, aw[3:], m))
        return await m.reply_text("📣 Yuborish boshlandi...")
    u = await gate(update, ctx, 2)
    if not u: return
    hw = u["mode"] == "hw"
    caption = m.caption or ("Bu uy vazifasi/masala. Rasmdagi topshiriqni o'qib, bosqichma-bosqich yech va javobini ayt." if hw
                            else "Bu rasmda nima bor? Batafsil tushuntir. Agar matn yoki masala bo'lsa, o'qib yech.")
    try:
        f = await m.photo[-1].get_file()
        b64 = base64.b64encode(bytes(await f.download_as_bytearray())).decode()
    except Exception:
        return await m.reply_text("⚠️ Rasmni yuklab bo'lmadi.")
    content = [{"type": "text", "text": caption}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]
    msgs = [{"role": "system", "content": sys_prompt(u, caption)}] + get_history(uid) + [{"role": "user", "content": content}]
    async with user_lock(uid):
        full = await stream_reply(m, msgs, VISION_MODELS, ANS_KB)
        if full:
            consume(u, 2); add_msg(uid, "user", f"[rasm] {caption}"); add_msg(uid, "assistant", full)
            if hw: setu(uid, mode="chat")

async def on_document(update, ctx):
    m, uid = update.effective_message, update.effective_user.id
    doc = m.document
    if uid in ADMINS and (m.caption or "").strip() == "/restore":
        f = await doc.get_file(); await f.download_to_drive("restore.db")
        def _r():
            src = sqlite3.connect("restore.db"); src.backup(db); src.close()
        await asyncio.to_thread(_r)
        return await m.reply_text("✅ Baza tiklandi.")
    u = await gate(update, ctx, 2)
    if not u: return
    if doc.file_size and doc.file_size > 15 * 1024 * 1024:
        return await m.reply_text("⚠️ Fayl juda katta (max 15MB).")
    name = doc.file_name or "fayl.txt"
    try:
        f = await doc.get_file(); raw = bytes(await f.download_as_bytearray())
        text = (await asyncio.to_thread(extract_doc, name, raw)).strip()
    except Exception as e:
        log.error("Hujjat xato: %s", e)
        return await m.reply_text("⚠️ Faylni o'qib bo'lmadi (PDF, DOCX, XLSX, TXT, kod fayllar qo'llanadi).")
    if not text: return await m.reply_text("⚠️ Fayl bo'sh yoki skan qilingan rasm.")
    ex("INSERT OR REPLACE INTO docs(uid,name,text) VALUES(?,?,?)", (uid, name, text[:60000]))
    await m.reply_text(f"📎 <b>{esc(name)}</b> yuklandi ({len(text)} belgi). Endi savol bera olasiz. O'chirish: ⚙️ Sozlamalar.", parse_mode="HTML")
    await chat_flow(m, ctx, u, m.caption or "Hujjatni tahlil qil: qisqa xulosa va asosiy punktlar.", cost=2)

async def on_inline(update, ctx):
    iq = update.inline_query; text = (iq.query or "").strip()
    u = q1("SELECT banned FROM users WHERE id=?", (iq.from_user.id,))
    if u and u["banned"]: return await iq.answer([])
    if len(text) < 4 or text[-1] not in "?.!":
        hint = InlineQueryResultArticle(id="hint", title="✍️ Savolingizni yozing va oxiriga ? qo'ying",
                                        input_message_content=InputTextMessageContent("✍️ Savol oxiriga ? qo'ying"))
        return await iq.answer([hint], cache_time=1)
    try:
        ans = (await llm([{"role": "system", "content": BASE_SYS + " Qisqa javob ber."}, {"role": "user", "content": text}], max_tokens=500)).strip()[:3900]
    except Exception:
        return await iq.answer([])
    await iq.answer([InlineQueryResultArticle(id=uuid.uuid4().hex, title="💡 AI javobi", description=ans[:100],
                     input_message_content=InputTextMessageContent(f"❓ {text}\n\n{ans}"))], cache_time=60)

# ================= TO'LOV =================
async def receipt(update, ctx):
    m, tg = update.effective_message, update.effective_user
    plan = ctx.user_data.pop("pay_plan", "pro"); ctx.user_data.pop("await", None)
    price = PLANS[plan]["price"]
    pid = ex("INSERT INTO payments(uid,plan,days,amount,status,ts,file_id) VALUES(?,?,?,?,?,?,?)",
             (tg.id, plan, 30, price, "pending", now(), m.photo[-1].file_id)).lastrowid
    cap = f"💳 To'lov #{pid}\n👤 {tg.full_name} (@{tg.username or '-'}) <code>{tg.id}</code>\n{PLANS[plan]['emoji']} {PLANS[plan]['name']} — {price:,} so'm"
    for a in ADMINS:
        try:
            await ctx.bot.send_photo(a, m.photo[-1].file_id, caption=cap, parse_mode="HTML",
                                     reply_markup=Kb([[Btn("✅ Tasdiqlash", f"pay_ok:{pid}"), Btn("❌ Rad", f"pay_no:{pid}")]]))
        except Exception as e: log.warning("Adminga chek: %s", e)
    await m.reply_text("✅ Chek adminga yuborildi. Tasdiqlangach tarif avtomatik yoqiladi.")

async def on_precheckout(update, ctx): await update.pre_checkout_query.answer(ok=True)

async def on_paid(update, ctx):
    m = update.effective_message; pay = m.successful_payment
    plan, days = pay.invoice_payload.split(":"); uid = update.effective_user.id
    grant_plan(uid, plan, int(days))
    ex("INSERT INTO payments(uid,plan,days,amount,status,ts) VALUES(?,?,?,?,?,?)", (uid, plan, int(days), pay.total_amount, "stars", now()))
    await m.reply_text(f"✅ {PLANS[plan]['emoji']} {PLANS[plan]['name']} tarifi {days} kunga yoqildi!", reply_markup=Kb([[Btn("🏠 Menyu", "m:home")]]))

async def redeem(m, uid, code):
    code = code.strip().upper()
    p = q1("SELECT * FROM promos WHERE code=?", (code,))
    if not p or p["used"] >= p["max_uses"]:
        return await m.reply_text("❌ Promokod yaroqsiz yoki tugagan.")
    if q1("SELECT 1 AS x FROM promo_used WHERE code=? AND uid=?", (code, uid)):
        return await m.reply_text("⚠️ Bu kodni allaqachon ishlatgansiz.")
    ex("INSERT INTO promo_used(code,uid) VALUES(?,?)", (code, uid))
    ex("UPDATE promos SET used=used+1 WHERE code=?", (code,))
    ex("UPDATE users SET bonus=bonus+? WHERE id=?", (p["bonus"], uid))
    await m.reply_text(f"🎉 +{p['bonus']} bonus xabar qo'shildi!", reply_markup=Kb([[Btn("🏠 Menyu", "m:home")]]))

# ================= ADMIN =================
def admin_kb():
    return Kb([[Btn("📊 Statistika", "adm:stats"), Btn("💳 To'lovlar", "adm:pending")],
               [Btn("📣 Hammaga", "adm:bc:all"), Btn("🆓 Free'ga", "adm:bc:free"), Btn("💎 Pullilarga", "adm:bc:paid")],
               [Btn("👤 Foydalanuvchi", "adm:user"), Btn("🎟 Promokod", "adm:promo")],
               [Btn("💾 Backup", "adm:backup"), Btn("◀️ Menyu", "m:home")]])

def stats_text():
    t0 = int(datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())

    def count(sql, args=()):
        row = q1(sql, args)
        return row["n"] if row else 0

    total_users = count("SELECT COUNT(*) n FROM users")
    new_today = count("SELECT COUNT(*) n FROM users WHERE created>=?", (t0,))
    active_today = count("SELECT COUNT(*) n FROM users WHERE last_seen>=?", (t0,))
    paid_users = count("SELECT COUNT(*) n FROM users WHERE plan != 'free'")
    banned_users = count("SELECT COUNT(*) n FROM users WHERE banned=1")
    total_requests = count("SELECT COALESCE(SUM(total),0) n FROM users")
    card_income = count("SELECT COALESCE(SUM(amount),0) n FROM payments WHERE status='ok'")
    stars_income = count("SELECT COALESCE(SUM(amount),0) n FROM payments WHERE status='stars'")

    return ("📊 <b>Statistika</b>\\n\\n"
            f"👥 Jami: <b>{total_users}</b>\\n"
            f"🆕 Bugun yangi: <b>{new_today}</b>\\n"
            f"🔥 Bugun faol: <b>{active_today}</b>\\n"
            f"💎 Pullik tarif: <b>{paid_users}</b>\\n"
            f"🚫 Ban: <b>{banned_users}</b>\\n"
            f"💬 Jami so'rovlar: <b>{total_requests}</b>\\n"
            f"💰 Daromad (karta): <b>{card_income:,}</b> so'm\\n"
            f"⭐ Stars: <b>{stars_income}</b>")

def user_card(uid):
    u = fresh(uid)
    if not u: return "❌ Foydalanuvchi topilmadi", None
    p = PLANS[u["plan"]]
    until = datetime.fromtimestamp(u["plan_until"], TZ).strftime("%d.%m.%Y") if u["plan"] != "free" else "-"
    t = (f"👤 <b>{esc(u['name'])}</b> @{esc(u['username'] or '-')}\n🆔 <code>{uid}</code>\n"
         f"{p['emoji']} {p['name']} (→ {until})\n⚡ {u['used']}/{p['limit']} · 🎁 {u['bonus']}\n"
         f"💬 Jami: {u['total']} · 👥 Referal: {u['refs']}\n🚫 Ban: {'ha' if u['banned'] else 'yo`q'}")
    kb = Kb([[Btn("✅ Unban" if u["banned"] else "🚫 Ban", f"au:ban:{uid}"), Btn("➕50 bonus", f"au:bonus:{uid}")],
             [Btn("💎 Pro 30k", f"au:pro:{uid}"), Btn("👑 Premium 30k", f"au:premium:{uid}")],
             [Btn("🆓 Free", f"au:free:{uid}"), Btn("◀️ Admin", "adm:home")]])
    return t, kb

async def do_broadcast(ctx, admin_id, audience, msg):
    sql = {"all": "SELECT id FROM users WHERE banned=0", "free": "SELECT id FROM users WHERE banned=0 AND plan='free'"}.get(
        audience, "SELECT id FROM users WHERE banned=0 AND plan!='free'")
    ok = fail = 0
    for r in q(sql):
        try:
            await ctx.bot.copy_message(r["id"], msg.chat_id, msg.message_id); ok += 1
        except Exception: fail += 1
        await asyncio.sleep(0.05)
    await ctx.bot.send_message(admin_id, f"📣 Tugadi: ✅ {ok} · ❌ {fail}")

def make_backup():
    dst = sqlite3.connect("backup.db"); db.backup(dst); dst.close()

async def send_backup(bot):
    await asyncio.to_thread(make_backup)
    for a in ADMINS:
        try:
            with open("backup.db", "rb") as f:
                await bot.send_document(a, f, filename=f"backup_{today()}.db", caption="💾 Baza zaxirasi. Tiklash: faylni shu caption bilan yuboring: /restore")
        except Exception as e: log.warning("Backup: %s", e)

async def admin_cb(update, ctx, d):
    cq = update.callback_query; uid = cq.from_user.id
    if uid not in ADMINS: return
    if d == "adm:home":
        return await show(update, "🛠 <b>Admin panel</b>", admin_kb())
    if d == "adm:stats":
        return await show(update, stats_text(), Kb([[Btn("◀️ Admin", "adm:home")]]))
    if d.startswith("adm:bc:"):
        ctx.user_data["await"] = "bc:" + d[7:]
        return await show(update, "📣 Yuboriladigan xabarni jo'nating (matn yoki rasm). Bekor: /menu", Kb([[Btn("◀️ Admin", "adm:home")]]))
    if d == "adm:user":
        ctx.user_data["await"] = "adm_user"
        return await show(update, "👤 Foydalanuvchi ID raqamini yuboring:", Kb([[Btn("◀️ Admin", "adm:home")]]))
    if d == "adm:promo":
        return await show(update, "🎟 Yaratish: <code>/promo KOD BONUS LIMIT</code>\nMasalan: <code>/promo YANGI50 50 100</code>", Kb([[Btn("◀️ Admin", "adm:home")]]))
    if d == "adm:backup":
        await send_backup(ctx.bot); return
    if d == "adm:pending":
        rows = q("SELECT * FROM payments WHERE status='pending' ORDER BY id DESC LIMIT 10")
        if not rows: return await show(update, "✅ Kutilayotgan to'lov yo'q.", Kb([[Btn("◀️ Admin", "adm:home")]]))
        for p in rows:
            await ctx.bot.send_photo(uid, p["file_id"], caption=f"💳 #{p['id']} · {p['uid']} · {p['plan']} · {p['amount']:,}",
                                     reply_markup=Kb([[Btn("✅", f"pay_ok:{p['id']}"), Btn("❌", f"pay_no:{p['id']}")]]))
        return
    if d.startswith("pay_"):
        act, pid = d.split(":"); p = q1("SELECT * FROM payments WHERE id=?", (int(pid),))
        if not p or p["status"] != "pending": return
        if act == "pay_ok":
            ex("UPDATE payments SET status='ok' WHERE id=?", (p["id"],)); grant_plan(p["uid"], p["plan"], p["days"])
            note, msg = "✅ Tasdiqlandi", f"✅ To'lov tasdiqlandi! {PLANS[p['plan']]['emoji']} {PLANS[p['plan']]['name']} {p['days']} kunga yoqildi."
        else:
            ex("UPDATE payments SET status='rejected' WHERE id=?", (p["id"],))
            note, msg = "❌ Rad etildi", "❌ To'lovingiz rad etildi. Muammo bo'lsa admin bilan bog'laning."
        try: await ctx.bot.send_message(p["uid"], msg)
        except Exception: pass
        try: await cq.edit_message_caption((cq.message.caption or "") + f"\n\n{note}")
        except Exception: pass
        return
    if d.startswith("au:"):
        _, act, tid = d.split(":"); tid = int(tid); u = fresh(tid)
        if not u: return
        if act == "ban": setu(tid, banned=1 - u["banned"])
        elif act == "bonus": ex("UPDATE users SET bonus=bonus+50 WHERE id=?", (tid,))
        elif act in ("pro", "premium"): grant_plan(tid, act, 30)
        elif act == "free": setu(tid, plan="free", plan_until=0)
        t, kb = user_card(tid)
        return await show(update, t, kb)

# ================= CALLBACKLAR =================
async def on_cb(update, ctx):
    cq = update.callback_query; d = cq.data or ""; uid = cq.from_user.id
    if d == "chk":
        if await missing_subs(ctx.bot, uid):
            return await cq.answer("❌ Hali hamma kanalga obuna bo'lmadingiz", show_alert=True)
        await cq.answer(); d = "m:home"
    else:
        await cq.answer()
    u = get_user(cq.from_user)
    if u["banned"]: return
    adm = uid in ADMINS
    def home(note=""):
        f = fresh(uid); return menu_text(f, note), main_kb(f, adm)

    if d.startswith(("adm:", "au:", "pay_")): return await admin_cb(update, ctx, d)

    if d == "m:home":
        ctx.user_data.pop("await", None); setu(uid, mode="chat")
        return await show(update, *home())
    if d == "m:new":
        clear_history(uid); ex("DELETE FROM docs WHERE uid=?", (uid,)); setu(uid, mode="chat")
        return await show(update, *home("🧹 Yangi suhbat boshlandi.\n\n"))
    if d == "m:roles":
        btns = [Btn(("✅ " if k == u["role"] else "") + v[0], f"role:{k}") for k, v in ROLES.items()]
        rows = [btns[i:i + 2] for i in range(0, len(btns), 2)] + [[Btn("◀️ Orqaga", "m:home")]]
        return await show(update, "🎭 <b>Rolni tanlang</b>\nBot shu rolda javob beradi:", Kb(rows))
    if d.startswith("role:"):
        k = d[5:]
        if k in ROLES: setu(uid, role=k)
        return await show(update, *home(f"✅ Rol: {ROLES.get(k, ROLES['default'])[0]}\n\n"))
    modes = {"m:img": ("image", "🎨 <b>Rasm yaratish</b> (3 kredit)\n\nQanday rasm kerak? Tavsifni yozing (istalgan tilda).\nMasalan: <i>tog' ustida quyosh botishi, realistik</i>"),
             "m:doc": ("doc", "📄 <b>Hujjat yozish</b> (3 kredit)\n\nMavzu/topshiriqni yozing: referat, maqola, biznes reja, xat...\nNatija <b>.docx</b> fayl bo'lib keladi."),
             "m:quiz": ("quiz", "🧩 <b>Viktorina</b> (2 kredit)\n\nMavzuni yozing — 5 ta test (Telegram quiz) tuzaman."),
             "m:hw": ("hw", "📚 <b>Uy vazifasi</b> (2 kredit)\n\nMasala/topshiriq <b>rasmini</b> yuboring — bosqichma-bosqich yechaman.")}
    if d in modes:
        setu(uid, mode=modes[d][0])
        return await show(update, modes[d][1], Kb([[Btn("◀️ Bekor qilish", "m:home")]]))
    if d == "m:tr":
        return await show(update, "🌐 <b>Tarjimon</b>\n\nQaysi tilga tarjima qilay? Tanlagach matn yuboring (ovoz ham bo'ladi).",
                          Kb([[Btn("🇺🇿 O'zbekcha", "tr:uz"), Btn("🇷🇺 Ruscha", "tr:ru"), Btn("🇬🇧 Inglizcha", "tr:en")], [Btn("◀️ Orqaga", "m:home")]]))
    if d.startswith("tr:"):
        setu(uid, mode=d)
        return await show(update, f"🌐 Tarjima rejimi: <b>{d[3:].upper()}</b>\nMatn yuboring. Chiqish uchun 🏠 bosing.", Kb([[Btn("🏠 Chiqish", "m:home")]]))
    if d == "m:search":
        setu(uid, search=1 - u["search"])
        return await show(update, *home("🔎 Web qidiruv " + ("yoqildi" if not u["search"] else "o'chirildi") + "\n\n"))
    if d == "m:voice":
        setu(uid, voice=1 - u["voice"])
        return await show(update, *home("🔊 Ovozli javob " + ("yoqildi" if not u["voice"] else "o'chirildi") + "\n\n"))
    if d == "mem:clear": setu(uid, memory=""); d = "m:mem"; u = fresh(uid)
    if d == "mem:toggle": setu(uid, memon=1 - u["memon"]); d = "m:mem"; u = fresh(uid)
    if d == "m:mem":
        return await show(update, f"🧠 <b>Xotira</b> — bot sizni shular bilan eslab qoladi:\n\n{esc(u['memory']) or '<i>hozircha bo`sh</i>'}\n\nQo'shish: <code>/eslab matn</code>",
                          Kb([[Btn("🗑 Tozalash", "mem:clear"), Btn("⏸ O'chirish" if u["memon"] else "▶️ Yoqish", "mem:toggle")], [Btn("◀️ Orqaga", "m:home")]]))
    if d == "m:prof":
        p = PLANS[u["plan"]]
        until = datetime.fromtimestamp(u["plan_until"], TZ).strftime("%d.%m.%Y") if u["plan"] != "free" else "—"
        return await show(update, f"👤 <b>Profil</b>\n\n🆔 <code>{uid}</code>\n{p['emoji']} Tarif: <b>{p['name']}</b> (→ {until})\n"
                                  f"⚡ Bugun: <b>{u['used']}/{p['limit']}</b>\n🎁 Bonus: <b>{u['bonus']}</b>\n💬 Jami so'rov: <b>{u['total']}</b>\n"
                                  f"👥 Taklif qilganlar: <b>{u['refs']}</b>\n📅 Qo'shilgan: {datetime.fromtimestamp(u['created'], TZ):%d.%m.%Y}", BACK)
    if d == "m:plans":
        f, pr, pm = PLANS["free"], PLANS["pro"], PLANS["premium"]
        t = (f"💎 <b>Tariflar</b> (30 kun)\n\n{f['emoji']} <b>Free</b> — {f['limit']} xabar/kun\n"
             f"{pr['emoji']} <b>Pro</b> — {pr['limit']} xabar/kun · {pr['price']:,} so'm · ⭐{pr['stars']}\n"
             f"{pm['emoji']} <b>Premium</b> — {pm['limit']} xabar/kun · {pm['price']:,} so'm · ⭐{pm['stars']}\n\n"
             "Rasm, hujjat, viktorina kabi funksiyalar ko'proq kredit sarflaydi.")
        rows = []
        if CARD: rows.append([Btn("💳 Pro (karta)", "buy:pro"), Btn("💳 Premium (karta)", "buy:premium")])
        rows += [[Btn("⭐ Pro (Stars)", "star:pro"), Btn("⭐ Premium (Stars)", "star:premium")], [Btn("◀️ Orqaga", "m:home")]]
        return await show(update, t, Kb(rows))
    if d.startswith("buy:"):
        plan = d[4:]; p = PLANS[plan]
        ctx.user_data["await"] = "receipt"; ctx.user_data["pay_plan"] = plan
        return await show(update, f"💳 <b>{p['emoji']} {p['name']} — {p['price']:,} so'm</b>\n\nKarta: <code>{esc(CARD)}</code>\nEgasi: {esc(CARD_OWNER)}\n\n"
                                  "To'lovni qilgach, <b>chek rasmini</b> shu yerga yuboring. Admin tasdiqlagach tarif yoqiladi.",
                          Kb([[Btn("◀️ Bekor", "m:home")]]))
    if d.startswith("star:"):
        plan = d[5:]; p = PLANS[plan]
        await ctx.bot.send_invoice(chat_id=uid, title=f"{p['name']} tarif — 30 kun", description=f"{p['limit']} xabar/kun",
                                   payload=f"{plan}:30", provider_token="", currency="XTR", prices=[LabeledPrice(p["name"], p["stars"])])
        return
    if d == "m:ref":
        link = f"https://t.me/{ctx.bot.username}?start=r{uid}"
        return await show(update, f"👥 <b>Do'st taklif qiling</b>\n\nHar bir do'st uchun sizga <b>+{REF_BONUS}</b> bonus, do'stingizga <b>+{REF_BONUS // 2}</b>.\n\n"
                                  f"🔗 Havolangiz:\n<code>{link}</code>\n\nTaklif qilganlar: <b>{u['refs']}</b>",
                          Kb([[Btn("📤 Ulashish", url=f"https://t.me/share/url?url={quote(link)}&text={quote('AI yordamchi bot 🤖')}")], [Btn("◀️ Orqaga", "m:home")]]))
    if d == "m:bonus":
        if u["last_bonus"] == today():
            note = "⏳ Bugungi bonusni olgansiz. Ertaga qaytib keling!\n\n"
        else:
            ex("UPDATE users SET bonus=bonus+?, last_bonus=? WHERE id=?", (DAILY_BONUS, today(), uid))
            note = f"🎁 +{DAILY_BONUS} bonus xabar qo'shildi!\n\n"
        return await show(update, *home(note))
    if d == "m:promo":
        ctx.user_data["await"] = "promo"
        return await show(update, "🎟 Promokodni yuboring:", Kb([[Btn("◀️ Bekor", "m:home")]]))
    if d == "m:set":
        cur = u["model"] if u["model"] in CHAT_MODELS else "avto"
        return await show(update, f"⚙️ <b>Sozlamalar</b>\n\n🤖 Model: <code>{esc(cur)}</code>",
                          Kb([[Btn("🤖 Modelni tanlash", "set:model")], [Btn("📎 Hujjatni o'chirish", "set:doc"), Btn("🗑 Tarixni tozalash", "m:new")], [Btn("◀️ Orqaga", "m:home")]]))
    if d == "set:model":
        rows = [[Btn(("✅ " if u["model"] == m else "") + m[:40], f"model:{i}")] for i, m in enumerate(CHAT_MODELS)]
        rows = [[Btn("🔄 Avto (tavsiya)", "model:auto")]] + rows + [[Btn("◀️ Orqaga", "m:set")]]
        return await show(update, "🤖 Modelni tanlang:", Kb(rows))
    if d.startswith("model:"):
        k = d[6:]
        setu(uid, model="" if k == "auto" else CHAT_MODELS[int(k)] if k.isdigit() and int(k) < len(CHAT_MODELS) else "")
        return await show(update, *home("✅ Model saqlandi.\n\n"))
    if d == "set:doc":
        ex("DELETE FROM docs WHERE uid=?", (uid,))
        return await show(update, *home("📎 Hujjat o'chirildi.\n\n"))
    if d == "tts":
        text = cq.message.text or cq.message.caption or ""
        try: await cq.message.reply_voice(await tts_bytes(text))
        except Exception as e:
            log.warning("TTS: %s", e); await cq.message.reply_text("⚠️ Ovoz xizmati hozir ishlamayapti.")
        return
    if d == "img:again":
        prompt = ctx.user_data.get("last_img")
        if not prompt: return await cq.message.reply_text("Avval 🎨 Rasm yaratish orqali tavsif yozing.")
        if not await afford(cq.message, u, 3): return
        if await make_image(cq.message, ctx, u, prompt): consume(u, 3)

# ================= BUYRUQLAR =================
async def cmd_start(update, ctx):
    tg, m = update.effective_user, update.effective_message
    existed = q1("SELECT id FROM users WHERE id=?", (tg.id,))
    u = get_user(tg)
    if u["banned"]: return await m.reply_text("🚫 Siz bloklangansiz.")
    if not existed and ctx.args and ctx.args[0].startswith("r") and ctx.args[0][1:].isdigit():
        rid = int(ctx.args[0][1:])
        if rid != tg.id and q1("SELECT id FROM users WHERE id=?", (rid,)):
            ex("UPDATE users SET ref_by=?, bonus=bonus+? WHERE id=?", (rid, REF_BONUS // 2, tg.id))
            ex("UPDATE users SET refs=refs+1, bonus=bonus+? WHERE id=?", (REF_BONUS, rid))
            try: await ctx.bot.send_message(rid, f"🎉 Do'stingiz qo'shildi! +{REF_BONUS} bonus.")
            except Exception: pass
    if await sub_wall(m, ctx, tg.id): return
    u = fresh(tg.id)
    await m.reply_text(menu_text(u, "👋 <b>Xush kelibsiz!</b>\n\n"), parse_mode="HTML", reply_markup=main_kb(u, tg.id in ADMINS))

async def cmd_menu(update, ctx):
    u = get_user(update.effective_user); ctx.user_data.pop("await", None); setu(u["id"], mode="chat")
    if await sub_wall(update.effective_message, ctx, u["id"]): return
    u = fresh(u["id"])
    await update.effective_message.reply_text(menu_text(u), parse_mode="HTML", reply_markup=main_kb(u, u["id"] in ADMINS))

async def cmd_new(update, ctx):
    uid = update.effective_user.id; get_user(update.effective_user)
    clear_history(uid); ex("DELETE FROM docs WHERE uid=?", (uid,))
    await update.effective_message.reply_text("🧹 Yangi suhbat boshlandi.")

async def cmd_img(update, ctx):
    u = await gate(update, ctx, 3)
    if not u: return
    prompt = " ".join(ctx.args)
    if not prompt:
        setu(u["id"], mode="image"); return await update.effective_message.reply_text("🎨 Rasm tavsifini yozing:")
    if await make_image(update.effective_message, ctx, u, prompt): consume(u, 3)

async def cmd_kod(update, ctx):
    get_user(update.effective_user)
    if not ctx.args:
        ctx.user_data["await"] = "promo"; return await update.effective_message.reply_text("🎟 Promokodni yuboring:")
    await redeem(update.effective_message, update.effective_user.id, ctx.args[0])

async def cmd_eslab(update, ctx):
    u = get_user(update.effective_user); t = " ".join(ctx.args).strip()
    if not t: return await update.effective_message.reply_text("Misol: /eslab Men Samarqandda yashayman")
    setu(u["id"], memory=((u["memory"] + "\n- " + t) if u["memory"] else "- " + t)[-700:])
    await update.effective_message.reply_text("🧠 Eslab qoldim.")

async def cmd_eslat(update, ctx):
    u = get_user(update.effective_user)
    if len(ctx.args) < 2 or not ctx.args[0].isdigit():
        return await update.effective_message.reply_text("⏰ Misol: <code>/eslat 30 dori ichish</code> (30 daqiqadan keyin)\n1 soat=60, 1 kun=1440", parse_mode="HTML")
    mins = int(ctx.args[0]); text = " ".join(ctx.args[1:])
    ex("INSERT INTO reminders(uid,ts,text) VALUES(?,?,?)", (u["id"], now() + mins * 60, text))
    await update.effective_message.reply_text(f"⏰ {mins} daqiqadan keyin eslataman.")

async def cmd_admin(update, ctx):
    if update.effective_user.id in ADMINS:
        await update.effective_message.reply_text("🛠 <b>Admin panel</b>", parse_mode="HTML", reply_markup=admin_kb())

async def cmd_user(update, ctx):
    if update.effective_user.id in ADMINS and ctx.args and ctx.args[0].isdigit():
        t, kb = user_card(int(ctx.args[0])); await update.effective_message.reply_text(t, parse_mode="HTML", reply_markup=kb)

async def cmd_give(update, ctx):
    if update.effective_user.id in ADMINS and len(ctx.args) == 2 and ctx.args[0].isdigit():
        ex("UPDATE users SET bonus=bonus+? WHERE id=?", (int(ctx.args[1]), int(ctx.args[0])))
        await update.effective_message.reply_text("✅ Berildi.")

async def cmd_promo(update, ctx):
    if update.effective_user.id in ADMINS and len(ctx.args) == 3 and ctx.args[1].isdigit() and ctx.args[2].isdigit():
        ex("INSERT OR REPLACE INTO promos(code,bonus,max_uses,used) VALUES(?,?,?,0)", (ctx.args[0].upper(), int(ctx.args[1]), int(ctx.args[2])))
        await update.effective_message.reply_text(f"✅ Promokod: {ctx.args[0].upper()} → +{ctx.args[1]} bonus, {ctx.args[2]} marta")

# ================= FON VAZIFALAR / XATOLAR =================
async def reminder_loop(app):
    while True:
        await asyncio.sleep(20)
        try:
            for r in q("SELECT * FROM reminders WHERE done=0 AND ts<=?", (now(),)):
                ex("UPDATE reminders SET done=1 WHERE id=?", (r["id"],))
                try: await app.bot.send_message(r["uid"], f"⏰ Eslatma: {r['text']}")
                except Exception: pass
        except Exception as e: log.error("Eslatma: %s", e)

async def backup_loop(app):
    while True:
        await asyncio.sleep(12 * 3600)
        try: await send_backup(app.bot)
        except Exception as e: log.error("Backup: %s", e)

last_err = [0.0]
async def on_error(update, ctx):
    log.error("Xato", exc_info=ctx.error)
    if time.time() - last_err[0] > 60 and ctx.error:
        last_err[0] = time.time()
        tb = "".join(traceback.format_exception(None, ctx.error, ctx.error.__traceback__))[-1500:]
        for a in ADMINS:
            try: await ctx.bot.send_message(a, "🐞 Xato:\n" + tb)
            except Exception: pass

async def post_init(app):
    await app.bot.set_my_commands([BotCommand("start", "Boshlash"), BotCommand("menu", "Asosiy menyu"),
        BotCommand("new", "Yangi suhbat"), BotCommand("img", "Rasm yaratish"), BotCommand("eslat", "Eslatma qo'yish"),
        BotCommand("eslab", "Xotiraga qo'shish"), BotCommand("kod", "Promokod")])
    app.bot_data["tasks"] = [asyncio.create_task(reminder_loop(app)), asyncio.create_task(backup_loop(app))]

def main():
    init_models()
    Thread(target=run_flask, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(True).post_init(post_init).build()
    for name, fn in [("start", cmd_start), ("menu", cmd_menu), ("new", cmd_new), ("img", cmd_img), ("kod", cmd_kod),
                     ("eslab", cmd_eslab), ("eslat", cmd_eslat), ("admin", cmd_admin), ("user", cmd_user),
                     ("give", cmd_give), ("promo", cmd_promo)]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(InlineQueryHandler(on_inline))
    app.add_handler(PreCheckoutQueryHandler(on_precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_paid))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
