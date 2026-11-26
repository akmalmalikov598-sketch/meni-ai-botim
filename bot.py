import os
from flask import Flask, request, Response, jsonify
from groq import Groq

app = Flask(__name__)

# Tartib bo'yicha sinaladi. Mavjud bo'lmaganlari o'tkazib yuboriladi.
PREFERRED = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.1-8b-instant",
    "qwen/qwen3-32b",
]

BASE = """Sen "Hoppy" ismli ingliz tili o'qituvchisisan. Maqsad: foydalanuvchini 0 dan IELTS 9.0 darajasigacha o'rgatish.
Uslub: qattiq, jahli chiqqan, baqiradigan o'qituvchi. Lekin so'kinma va haqorat qilma (onasi, irqi, dini, shaxsiy hayoti haqida gapirma).
Qoidalar:
- Har javobni [mood:X] tegi bilan boshla. X: happy, neutral, angry, proud, shout.
- Xato bo'lsa [mood:shout] yoz, javobni BOSH HARFLAR bilan boshla ("YANA XATO!", "QAYTA YOZ!") va xatoni qattiq tuzat. Tushuntirishni o'zbekcha ber.
- Befarq yoki bo'sh gap bo'lsa [mood:angry] yoz.
- To'g'ri javob bo'lsa qisqa maqta va [mood:proud] yoki [mood:happy] tanla.
- Tushuntirishlar o'zbekcha, gap va misollar inglizcha bo'lsin.
- Baholash bo'lsa oxirida [score:N] qo'sh, N 0 dan 100 gacha.
- Har doim oxirida aniq vazifa yoki savol ber.
"""

MODES = {
    "lesson": "Rejim: DARS. Darajani aniqlab, bosqichma-bosqich dars ber: alifbo, talaffuz, so'z turkumlari, zamonlar, gap tuzish, so'z boyligi, keyin IELTS. Har darsda qisqa nazariya va 3 ta mashq ber.",
    "homework": "Rejim: UYGA VAZIFA. 5 ta vazifa ber (grammatika, so'z boyligi, tarjima). Javoblarni qattiq tekshir, har birini izohla va oxirida umumiy [score:N] qo'sh.",
    "speaking": "Rejim: GAPIRISH. Faqat inglizcha suhbatlash. Javobing 2-3 qisqa gap bo'lsin. Foydalanuvchi gapidagi har bir xatoni o'zbekcha izoh bilan ko'rsat. Har javobda savol ber.",
    "ielts": "Rejim: IELTS. Writing Task 2, Speaking Part 1-3 yoki Reading mashqlarini o'tkaz. Javobni IELTS band (0-9) bo'yicha baho, yetishmagan jihatlarni ayt va oxirida [score:N] qo'sh (N = band * 11, masalan 6.5 -> 72).",
}


def get_client():
    key = os.environ.get("GROQ_API_KEY")
    return Groq(api_key=key) if key else None


def available_models(client):
    """Groq'dagi haqiqatan mavjud modellar, PREFERRED tartibida."""
    try:
        live = {m.id for m in client.models.list().data}
    except Exception:
        return PREFERRED[:]  # ro'yxatni ololmasa, hammasini sinab ko'ramiz
    found = [m for m in PREFERRED if m in live]
    return found or sorted(live)


@app.route("/")
def index():
    return HTML


@app.route("/api/models")
def models():
    client = get_client()
    if client is None:
        return jsonify(models=[], error="GROQ_API_KEY sozlanmagan")
    return jsonify(models=available_models(client))


@app.route("/api/chat", methods=["POST"])
def chat():
    client = get_client()
    if client is None:
        return Response("[mood:angry] GROQ_API_KEY sozlanmagan! Render Environment ga qo'shing.",
                        mimetype="text/plain; charset=utf-8")

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()[:4000]
    if not message:
        return Response("[mood:angry] BO'SH XABAR! Yozing!", mimetype="text/plain; charset=utf-8")

    mode = data.get("mode") if data.get("mode") in MODES else "lesson"

    # Foydalanuvchi tanlagan model birinchi sinaladi, qolganlari zaxira.
    live = available_models(client)
    req = data.get("model")
    order = ([req] if req in live else []) + [m for m in live if m != req]

    messages = [{"role": "system", "content": BASE + "\n" + MODES[mode]}]
    for m in (data.get("history") or [])[-30:]:
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and m["content"]:
            messages.append({"role": m["role"], "content": m["content"][:4000]})
    messages.append({"role": "user", "content": message})

    def generate():
        last_err = None
        for name in order:
            try:
                stream = client.chat.completions.create(
                    model=name, messages=messages, max_tokens=1500, stream=True
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
                return
            except Exception as e:
                last_err = e  # keyingi modelga o'tamiz
        yield f"\n[mood:angry] Hech bir model ishlamadi: {last_err}"

    return Response(generate(), mimetype="text/plain; charset=utf-8",
                    headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


HTML = r"""<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hoppy - Ingliz tili</title>
<style>
  * { box-sizing: border-box; }
  body { margin:0; height:100vh; font-family:system-ui, sans-serif; background:#0f1115; color:#e8e8e8; overflow:hidden; }
  #stage { display:flex; height:100%; width:100%; }
  #stage.shake { animation: quake .45s; }
  @keyframes quake {
    0%,100%{transform:translate(0,0)} 10%{transform:translate(-10px,6px)} 20%{transform:translate(10px,-6px)}
    30%{transform:translate(-12px,4px)} 40%{transform:translate(12px,-4px)} 50%{transform:translate(-8px,6px)}
    60%{transform:translate(8px,-4px)} 70%{transform:translate(-5px,3px)} 80%{transform:translate(5px,-2px)} 90%{transform:translate(-2px,1px)}
  }
  #flash { position:fixed; inset:0; background:radial-gradient(circle,rgba(255,30,30,.55),rgba(160,0,0,.15)); pointer-events:none; opacity:0; z-index:50; }
  #flash.go { animation: flash .7s ease-out; }
  @keyframes flash { 0%{opacity:1} 100%{opacity:0} }

  #side { width:340px; background:#171a21; border-right:1px solid #262b36; display:flex; flex-direction:column; align-items:center; padding:16px; gap:12px; overflow-y:auto; }
  #side.hidden { display:none; }
  #mascot { width:260px; height:260px; cursor:pointer; }
  #face { transform-origin:60px 60px; }
  #face.happy, #face.proud { animation: bounce 1s ease-in-out infinite; }
  @keyframes bounce { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-10px)} }
  #face.angry { animation: rage .18s infinite; }
  #face.shout { animation: rage .1s infinite; }
  @keyframes rage { 0%,100%{transform:rotate(0)} 25%{transform:rotate(-4deg)} 75%{transform:rotate(4deg)} }
  #pill { transition: fill .2s, stroke .2s; }
  #face.angry #pill, #face.shout #pill { fill:#ffe1e1; stroke:#ff1a1a; }
  #face.talking #pill { animation: pulse .25s infinite alternate; }
  @keyframes pulse { from{transform:scale(1)} to{transform:scale(1.04)} }
  .eye { transform-box:fill-box; transform-origin:center; animation: blink 3.5s infinite; }
  @keyframes blink { 0%,94%,100%{transform:scaleY(1)} 97%{transform:scaleY(.1)} }
  #face.angry .eye, #face.shout .eye { animation:none; transform:scaleY(.5); }
  #face.shout .eye { fill:#ff0000; }
  #brows { opacity:0; transition:opacity .15s; }
  #face.angry #brows, #face.shout #brows { opacity:1; }
  #steam { opacity:0; }
  #face.angry #steam, #face.shout #steam { opacity:1; animation: steam .6s infinite; }
  @keyframes steam { 0%{transform:translateY(0);opacity:1} 100%{transform:translateY(-14px);opacity:0} }

  #mood-label { font-size:16px; font-weight:600; color:#8a93a6; text-align:center; min-height:24px; }
  #mood-label.red { color:#ff5a5a; }
  #progressBox { width:100%; }
  #progLabel { font-size:14px; margin-bottom:6px; }
  #bar { height:14px; background:#262b36; border-radius:8px; overflow:hidden; }
  #fill { height:100%; width:0%; background:linear-gradient(90deg,#c93a2e,#ff8a7a); transition: width .6s; }
  #tools { width:100%; display:flex; flex-direction:column; gap:8px; }
  .btn { padding:10px; border:1px solid #303746; border-radius:10px; background:#1e232d; color:#e8e8e8; cursor:pointer; font-size:14px; }
  .btn:hover { background:#262b36; }

  #main { flex:1; display:flex; flex-direction:column; min-width:0; }
  header { padding:12px 16px; background:#171a21; border-bottom:1px solid #262b36; display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
  header h1 { margin:0; font-size:22px; color:#ff5a4e; margin-right:auto; }
  #toggle { background:none; border:0; color:#e8e8e8; font-size:20px; cursor:pointer; }
  .tab { padding:8px 14px; border-radius:8px; border:1px solid #303746; background:#1e232d; color:#e8e8e8; cursor:pointer; font-size:14px; }
  .tab.active { background:#c93a2e; border-color:#c93a2e; }
  select, #clear { padding:7px 10px; border-radius:8px; border:1px solid #303746; background:#0f1115; color:#e8e8e8; cursor:pointer; }
  #chat { flex:1; overflow-y:auto; padding:20px; display:flex; flex-direction:column; gap:12px; }
  .msg { max-width:80%; padding:10px 14px; border-radius:12px; white-space:pre-wrap; line-height:1.55; word-wrap:break-word; }
  .user { align-self:flex-end; background:#2b6cb0; }
  .bot { align-self:flex-start; background:#1e232d; }
  .bot.angry { border:1px solid #ff3b3b; }
  .glitch.on { animation: glitch .35s steps(3) 1; }
  @keyframes glitch {
    0%{transform:translate(0); text-shadow:none}
    25%{transform:translate(-4px,1px); text-shadow:3px 0 #ff0000, -3px 0 #00ffff}
    50%{transform:translate(4px,-1px); text-shadow:-3px 0 #ff0000, 3px 0 #00ffff}
    75%{transform:translate(-2px,0); text-shadow:2px 0 #ff0000}
    100%{transform:translate(0); text-shadow:none}
  }
  form { display:flex; gap:8px; padding:14px; background:#171a21; border-top:1px solid #262b36; }
  textarea { flex:1; padding:12px; border-radius:10px; border:1px solid #303746; background:#0f1115; color:#e8e8e8; font-size:15px; resize:none; font-family:inherit; }
  #mic { padding:0 14px; border:1px solid #303746; border-radius:10px; background:#1e232d; color:#e8e8e8; font-size:18px; cursor:pointer; }
  #mic.rec { background:#b03030; animation: pulse .4s infinite alternate; }
  #send { padding:0 20px; border:0; border-radius:10px; background:#c93a2e; color:#fff; font-size:15px; cursor:pointer; }
  #send:disabled { opacity:.5; cursor:default; }

  #scare { position:fixed; inset:0; background:#000; display:none; align-items:center; justify-content:center; z-index:100; cursor:pointer; }
  #scare.show { display:flex; animation: scareIn .25s steps(2) 2; }
  #scare svg { width:min(80vw,60vh); height:min(80vw,60vh); }
  #scare .eyeRed { animation: redPulse .2s infinite alternate; }
  @keyframes scareIn { 0%{opacity:0; transform:scale(1.4)} 100%{opacity:1; transform:scale(1)} }
  @keyframes redPulse { from{fill:#ff0000} to{fill:#440000} }

  @media (max-width:800px) {
    #side { position:absolute; z-index:5; height:100%; }
    #side.hidden { display:none; }
    #mascot { width:200px; height:200px; }
  }
</style>
</head>
<body>
<div id="flash"></div>
<div id="scare">
  <svg viewBox="0 0 120 120">
    <rect width="120" height="120" fill="#000"/>
    <path d="M20 30 Q60 0 100 30 L100 90 Q60 120 20 90 Z" fill="#e8e8e8"/>
    <ellipse class="eyeRed" cx="42" cy="58" rx="9" ry="6" fill="#ff0000"/>
    <ellipse class="eyeRed" cx="78" cy="58" rx="9" ry="6" fill="#ff0000"/>
    <path d="M40 86 Q60 100 80 86 Q60 92 40 86" fill="#8b0000"/>
  </svg>
</div>

<div id="stage">
  <div id="side">
    <svg id="mascot" viewBox="0 0 120 120">
      <g id="face">
        <g id="steam">
          <path d="M24 18 q-4 -6 0 -12" stroke="#ff5a5a" stroke-width="3" fill="none" stroke-linecap="round"/>
          <path d="M96 18 q4 -6 0 -12" stroke="#ff5a5a" stroke-width="3" fill="none" stroke-linecap="round"/>
        </g>
        <rect id="pill" x="12" y="26" width="96" height="68" rx="34" fill="#fff" stroke="#ff5a4e" stroke-width="6"/>
        <ellipse class="eye" cx="42" cy="54" rx="7" ry="9" fill="#111"/>
        <ellipse class="eye" cx="78" cy="54" rx="7" ry="9" fill="#111"/>
        <g id="brows" stroke="#111" stroke-width="5" stroke-linecap="round">
          <line x1="30" y1="38" x2="50" y2="48"/>
          <line x1="90" y1="38" x2="70" y2="48"/>
        </g>
        <path id="mouth" d="M42 66 Q60 82 78 66" fill="none" stroke="#111" stroke-width="5" stroke-linecap="round"/>
      </g>
    </svg>
    <div id="mood-label">Tayyor, qachon tayyor bo'lsang</div>
    <div id="progressBox">
      <div id="progLabel">Daraja: <b id="pct">0</b>%</div>
      <div id="bar"><div id="fill"></div></div>
    </div>
    <div id="tools">
      <button class="btn" id="speakBtn">🔊 Ovoz: yoqilgan</button>
      <button class="btn" id="resetProg">Darajani nolga qaytarish</button>
    </div>
  </div>

  <div id="main">
    <header>
      <button id="toggle" title="Menyu">☰</button>
      <h1>Hoppy</h1>
      <button class="tab" data-mode="lesson">📘 Dars</button>
      <button class="tab" data-mode="homework">📝 Uyga vazifa</button>
      <button class="tab" data-mode="speaking">🗣 Gapirish</button>
      <button class="tab" data-mode="ielts">🎯 IELTS</button>
      <select id="model"></select>
      <button id="clear">Tozalash</button>
    </header>
    <div id="chat"></div>
    <form id="f">
      <button id="mic" type="button" title="Gapirish">🎤</button>
      <textarea id="inp" rows="1" placeholder="Yozing yoki 🎤 bosib gapiring... (Enter - yuborish)"></textarea>
      <button id="send" type="submit">Yuborish</button>
    </form>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);

const MOUTH = {
  happy: "M42 66 Q60 84 78 66", proud: "M42 66 Q60 88 78 66",
  neutral: "M46 70 L74 70", angry: "M42 80 Q60 62 78 80",
  shout: "M40 68 Q60 96 80 68 Q60 74 40 68",
  talk1: "M44 64 Q60 96 76 64", talk2: "M46 68 Q60 74 74 68"
};
const LABEL = {
  happy: "Zo'r! 😊", proud: "Ajoyib! 🌟", neutral: "Tayyor, qachon tayyor bo'lsang",
  angry: "JAHLIM CHIQDI! 😡", shout: "YANA XATO!!! 🤬", talking: "Gapiryapman... 💬"
};
const INTRO = {
  lesson: "SALOM! Men Hoppy. Darajangizni bilmasam dars bera olmayman. Ingliz tilini qayerdan boshlaysiz? Xato qilsangiz, JAHLIM CHIQADI!",
  homework: "UYGA VAZIFA! 'Vazifa ber' deb yozing. 5 ta mashq beraman, bajarmasangiz kechirmayman!",
  speaking: "GAPIRISH! Mikrofonni bosing va inglizcha gapiring. Xato qilsangiz, darhol tuzataman!",
  ielts: "IELTS! 'Writing Task 2 ber' yoki 'Speaking part 1 boshlaymiz' deb yozing. Band balingizni qattiq baholayman."
};

let mode = localStorage.getItem('hoppy_mode') || 'lesson';
let chats = JSON.parse(localStorage.getItem('hoppy_chats') || '{}');
let progress = +localStorage.getItem('hoppy_progress') || 0;
let busy = false, speakOn = true, curMood = 'neutral', talkTimer = null;
let actx = null, scareCooldown = 0, idleTimer = null;

function save() {
  localStorage.setItem('hoppy_mode', mode);
  localStorage.setItem('hoppy_chats', JSON.stringify(chats));
  localStorage.setItem('hoppy_progress', progress);
}

// ---------- Ovoz effektlari (fayl kerak emas) ----------
function beep(freq = 60, dur = 0.8, type = 'sawtooth', vol = 0.25) {
  try {
    actx = actx || new (window.AudioContext || window.webkitAudioContext)();
    const o = actx.createOscillator();
    const g = actx.createGain();
    o.type = type;
    o.frequency.value = freq;
    g.gain.setValueAtTime(vol, actx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.001, actx.currentTime + dur);
    o.connect(g).connect(actx.destination);
    o.start();
    o.stop(actx.currentTime + dur);
  } catch (e) {}
}
function alarm() {
  beep(55, 0.9, 'sawtooth', 0.3);
  setTimeout(() => beep(42, 0.7, 'square', 0.2), 350);
}

// ---------- Jumpscare va silkinish ----------
function jumpscare() {
  const now = Date.now();
  if (now < scareCooldown) return;
  scareCooldown = now + 15000;
  const s = $('scare');
  s.classList.remove('show'); void s.offsetWidth; s.classList.add('show');
  alarm();
  setTimeout(() => s.classList.remove('show'), 1200);
}
$('scare').onclick = () => $('scare').classList.remove('show');

function angryFx(strong) {
  const st = $('stage'), fl = $('flash');
  st.classList.remove('shake'); void st.offsetWidth; st.classList.add('shake');
  if (strong) { fl.classList.remove('go'); void fl.offsetWidth; fl.classList.add('go'); }
}

function glitchLast() {
  const bubbles = document.querySelectorAll('#chat .bot');
  const last = bubbles[bubbles.length - 1];
  if (!last) return;
  last.classList.remove('glitch', 'on');
  void last.offsetWidth;
  last.classList.add('glitch', 'on');
}

// ---------- Yuz holati ----------
function setMood(m) {
  curMood = m;
  $('face').setAttribute('class', m);
  $('mood-label').className = (m === 'angry' || m === 'shout') ? 'red' : '';
  if (!talkTimer) $('mouth').setAttribute('d', MOUTH[m] || MOUTH.neutral);
  $('mood-label').textContent = LABEL[m] || LABEL.neutral;

  if (m === 'shout') {
    alarm();
    angryFx(true);
    glitchLast();
    if (Math.random() < 0.6) jumpscare();
  } else if (m === 'angry') {
    beep(70, 0.4, 'square', 0.15);
    angryFx(false);
    glitchLast();
  }
}

function startTalk() {
  $('face').setAttribute('class', 'talking');
  $('mood-label').textContent = LABEL.talking;
  $('mood-label').className = '';
  let t = 0;
  clearInterval(talkTimer);
  talkTimer = setInterval(() => $('mouth').setAttribute('d', (t++ % 2) ? MOUTH.talk1 : MOUTH.talk2), 140);
}
function stopTalk() {
  clearInterval(talkTimer);
  talkTimer = null;
  setMood(curMood);
}

// ---------- Teglar va daraja ----------
function parseTags(full) {
  const mood = (full.match(/\[mood:(\w+)\]/) || [])[1] || null;
  const scoreM = full.match(/\[score:(\d+)\]/);
  const score = scoreM ? Math.min(100, +scoreM[1]) : null;
  const clean = full.replace(/\[mood:\w+\]/g, '').replace(/\[score:\d+\]/g, '').trim();
  return {mood, score, clean};
}

function updateProgress() {
  $('pct').textContent = progress;
  $('fill').style.width = progress + '%';
}

function speak(text) {
  if (!speakOn || !('speechSynthesis' in window)) return;
  const plain = text.replace(/[*#`_]/g, '');
  const u = new SpeechSynthesisUtterance(plain);
  u.lang = 'en-US';
  u.rate = 1.05;
  u.pitch = (curMood === 'shout' || curMood === 'angry') ? 1.3 : 1.0;
  u.onstart = startTalk;
  u.onend = stopTalk;
  u.onerror = stopTalk;
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
}

// ---------- Modellar (serverdan) ----------
async function loadModels() {
  const sel = $('model');
  try {
    const r = await fetch('/api/models');
    const j = await r.json();
    sel.innerHTML = '';
    (j.models || []).forEach(m => {
      const o = document.createElement('option');
      o.value = m;
      o.textContent = m;
      sel.appendChild(o);
    });
    if (!sel.options.length) {
      const o = document.createElement('option');
      o.textContent = j.error || 'Model topilmadi';
      sel.appendChild(o);
    }
  } catch (e) {
    sel.innerHTML = '<option>Modellar yuklanmadi</option>';
  }
}

// ---------- Chat ----------
function addBubble(role, text, angry) {
  const d = document.createElement('div');
  d.className = 'msg ' + (role === 'user' ? 'user' : 'bot') + (angry ? ' angry' : '');
  d.textContent = text;
  $('chat').appendChild(d);
  return d;
}

function renderAll() {
  document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  $('speakBtn').textContent = speakOn ? '🔊 Ovoz: yoqilgan' : "🔇 Ovoz: o'chirilgan";
  const box = $('chat');
  box.innerHTML = '';
  const list = chats[mode] || [];
  if (list.length === 0) addBubble('bot', INTRO[mode]);
  list.forEach(m => addBubble(m.role === 'user' ? 'user' : 'bot', m.content));
  box.scrollTop = box.scrollHeight;
  updateProgress();
}

async function send() {
  const input = $('inp');
  const text = input.value.trim();
  if (!text || busy) return;
  resetIdle();
  if (!chats[mode]) chats[mode] = [];
  const list = chats[mode];
  const history = list.slice(-30);
  list.push({role: 'user', content: text});
  list.push({role: 'assistant', content: ''});
  input.value = '';
  busy = true;
  $('send').disabled = true;
  renderAll();
  const el = $('chat').lastElementChild;
  setMood('neutral');

  let full = '';
  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text, history, mode, model: $('model').value})
    });
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      full += dec.decode(value, {stream: true});
      el.textContent = parseTags(full).clean;
      $('chat').scrollTop = $('chat').scrollHeight;
    }
  } catch (err) {
    full = "[mood:angry] Server bilan aloqa yo'q!";
  }

  const {mood, score, clean} = parseTags(full);
  list[list.length - 1].content = clean;
  el.textContent = clean;
  if (mood === 'angry' || mood === 'shout') el.classList.add('angry');
  if (score !== null && score > progress) progress = score;
  save();
  updateProgress();

  setMood(mood || 'neutral');
  if (mode === 'speaking' || speakOn) speak(clean);

  busy = false;
  $('send').disabled = false;
  input.focus();
}

// ---------- Mikrofon ----------
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null, recording = false;
if (SR) {
  rec = new SR();
  rec.lang = 'en-US';
  rec.interimResults = false;
  rec.onresult = e => {
    $('inp').value = e.results[0][0].transcript;
    if (mode === 'speaking') send();
  };
  rec.onend = () => { recording = false; $('mic').classList.remove('rec'); };
}
$('mic').onclick = () => {
  if (!rec) { alert("Bu brauzerda mikrofon ishlamaydi. Chrome ishlating."); return; }
  if (recording) { rec.stop(); return; }
  recording = true;
  $('mic').classList.add('rec');
  rec.start();
};

// ---------- Idle: uzoq jim qolsa, Hoppy g'azablanadi ----------
function resetIdle() {
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => {
    if (busy) return;
    setMood('angry');
    addBubble('bot', 'HOY! Uxlab qoldingizmi? Yozing!', true);
    $('chat').scrollTop = $('chat').scrollHeight;
  }, 120000);
}
['keydown', 'click', 'touchstart'].forEach(ev => document.addEventListener(ev, resetIdle));

// ---------- Boshqaruv ----------
$('f').addEventListener('submit', e => { e.preventDefault(); send(); });
$('inp').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
document.querySelectorAll('.tab').forEach(b => b.onclick = () => {
  mode = b.dataset.mode;
  save();
  renderAll();
});
$('clear').onclick = () => {
  if (!confirm("Bu bo'limdagi suhbat o'chirilsinmi?")) return;
  chats[mode] = [];
  save();
  renderAll();
};
$('speakBtn').onclick = () => {
  speakOn = !speakOn;
  if (!speakOn) speechSynthesis.cancel();
  renderAll();
};
$('resetProg').onclick = () => {
  if (confirm('Daraja nolga qaytsinmi?')) { progress = 0; save(); updateProgress(); }
};
$('mascot').onclick = () => {
  setMood('shout');
  setTimeout(() => setMood('neutral'), 1500);
};
$('toggle').onclick = () => $('side').classList.toggle('hidden');

setMood('neutral');
renderAll();
loadModels();
resetIdle();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
