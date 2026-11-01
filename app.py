import os
import hmac
import sqlite3
from pathlib import Path
from flask import Flask, request, session, redirect, url_for, render_template_string, flash, abort, Response
from twilio.rest import Client
from voice_chat import init_schema, install_voice, uses_openai

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-only-change-before-deploy")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.getenv("RENDER") is not None)
DB = Path(os.getenv("MALAK_DB_PATH", "/tmp/malak_tasks.db"))
VOICE = os.getenv("MALAK_VOICE", "Polly.Hala-Neural")
LANG = os.getenv("MALAK_LANGUAGE", "ar-AE")
CALL_TEXT = "هلا، أنا ملاك. أنا خلصت."
PAGE = """<!doctype html><html lang="ar" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#191e34"><title>ملاك - المهام والمكالمات</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f5f6fa;color:#181d2c;font-family:system-ui,-apple-system,Arial}
header{background:#191e34;color:white;padding:25px 18px}main{max-width:700px;margin:24px auto;padding:0 15px}
.card{background:white;border-radius:17px;padding:22px;margin:16px 0;box-shadow:0 4px 18px #10102012}
input,button{font:inherit;padding:13px;border-radius:10px;max-width:100%}
input{border:1px solid #a4a8b9;width:100%;margin:8px 0}
button{border:0;background:#3d5af1;color:white;cursor:pointer}
button.secondary{background:#535b70}button.warn{background:#195e4e}
.flex{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
small{color:#666}.flash{background:#fff1bd;padding:12px;border-radius:9px}
</style></head><body>
<header><h1>🎙️ ملاك</h1><p>مدير المهام والتنبيه باتصال هاتفي</p></header>
<main>
{% for msg in get_flashed_messages() %}<p class="flash">{{msg}}</p>{% endfor %}
{% if not logged_in %}
<section class="card"><h2>تسجيل الدخول</h2><form method="post" action="/login">
<label>كلمة المرور<input type="password" name="password" required autocomplete="current-password"></label>
<button>دخول</button></form></section>
{% else %}
<section class="card"><div class="flex"><h2>إضافة مهمة</h2><form method="post" action="/logout"><input type="hidden" name="csrf" value="{{csrf}}"><button class="secondary">خروج</button></form></div>
<form method="post" action="/tasks"><input type="hidden" name="csrf" value="{{csrf}}">
<input name="title" maxlength="180" placeholder="اكتب المهمة هنا" required><button>إضافة</button></form></section>
<section class="card"><h2>المهام</h2>
{% for t in tasks %}<div class="flex" style="border-bottom:1px solid #eee;padding:13px 0">
<div>{% if t['done'] %}✅{% else %}⏳{% endif %} {{t['title']}} <small>#{{t['id']}}</small></div>
{% if not t['done'] %}<form method="post" action="/tasks/{{t['id']}}/complete">
<input type="hidden" name="csrf" value="{{csrf}}">
<label><input type="checkbox" name="call" value="1" style="width:auto"> اتصل عند الإنجاز</label>
<button class="warn">إنهاء</button></form>{% endif %}</div>
{% else %}<p>ما عندك مهام بعد.</p>{% endfor %}</section>
<section class="card"><h2>محادثة ملاك والتأكيد</h2>
<p>تسمع ملاك ردك بالعربية وتجاوبك. اضغط 1 أثناء المكالمة لحفظ التأكيد، أو 9 للإنهاء دون تأكيد.</p>
{% if local_mode %}<p>الردود العربية الجاهزة مفعلة دون الحاجة لرصيد OpenAI. قل «خلصت» أو «ما خلصت» أو «وش المهمة؟». هذه محادثة محدودة بردود جاهزة.</p>
<p>يحوّل Twilio كلامك إلى نص لمعالجته داخل ملاك؛ لا يُرسل النص إلى OpenAI في هذا الوضع.</p>
{% else %}<p>يتم تحويل كلامك إلى نص وإرساله إلى OpenAI للرد، دون تسجيل صوتي في التطبيق.</p>
<p>{% if ai_ready %}الربط الذكي مضبوط؛ الردود تتطلب رصيد API متاحًا.{% else %}الرد الذكي ينتظر إعداد مفتاح OpenAI. تأكيد الأرقام متاح.{% endif %}</p>{% endif %}
<p>قد تسمع مقدمة Twilio التجريبية أولًا. اضغط أي رقم إذا طلبت ذلك، ثم انتظر رسالة ملاك.</p>
<p>المكالمة الفعلية تتطلب إعداد Twilio وقد تترتب عليها رسوم.</p>
<form method="post" action="/test-call"><input type="hidden" name="csrf" value="{{csrf}}">
<label><input type="checkbox" name="confirm" value="yes" required style="width:auto"> أوافق على طلب مكالمة تجريبية لرقمي</label>
<button>📞 اتصل علي الآن (Test)</button></form></section>
<section class="card"><h2>سجل المحادثات والتأكيدات</h2>
{% if temporary_storage %}<p class="flash">السجل والمهام محفوظة مؤقتًا على هذه الاستضافة، وقد تُفقد عند إعادة تشغيلها أو نشر تحديث. يلزم تخزين دائم للاحتفاظ بها.</p>{% endif %}
{% for c in calls %}<div style="border-bottom:1px solid #eee;padding:12px 0">
<strong>{{c['title']}}</strong>
<p>{% if c['confirmed_at'] %}✅ تم تأكيدك وحفظه — {{c['confirmed_at']}} UTC{% elif c['state']=='closed' %}انتهت دون تأكيد{% else %}لم يُحفظ تأكيد بعد{% endif %}</p>
<small>بدء المكالمة: {{c['created_at']}} UTC</small>
</div>{% else %}<p>لم تُجرَ محادثات بعد.</p>{% endfor %}
</section>
{% endif %}
</main></body></html>"""

def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0)")
    init_schema(con)
    return con

def authenticated():
    return session.get("logged_in", False)

def guard():
    if not authenticated():
        abort(401)
    sent = request.form.get("csrf", "")
    if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
        abort(403)

def phone_call(task_id=None):
    required = ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "MALAK_TO_NUMBER"]
    if any(not os.getenv(k) for k in required):
        return "لم تُضبط إعدادات Twilio بعد."
    base_url = os.getenv("RENDER_EXTERNAL_URL", "https://malak-calls.onrender.com").rstrip("/")
    try:
        call = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"]).calls.create(
            from_=os.environ["TWILIO_FROM_NUMBER"],
            to=os.environ["MALAK_TO_NUMBER"],
            url=f"{base_url}/voice"
        )
        con = db()
        try:
            task = con.execute("SELECT title FROM tasks WHERE id=?", (task_id,)).fetchone() if task_id else None
            title = task["title"] if task else "تجربة المحادثة والتأكيد"
            con.execute("INSERT INTO voice_calls(sid,task_id,title) VALUES(?,?,?)", (call.sid, task_id, title))
            con.commit()
        finally:
            con.close()
        return f"تم إرسال طلب المكالمة إلى Twilio. رقم الطلب: {call.sid}. هذا لا يؤكد أن المكالمة وصلت أو تم الرد عليها."
    except Exception:
        app.logger.exception("Twilio call failed")
        return "تعذر إرسال طلب المكالمة. تحقق من حساب Twilio وأرقام الاتصال وصلاحيات الاتصال بالسعودية."

@app.get("/")
def index():
    import secrets
    if authenticated() and "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    con = db()
    try:
        tasks = con.execute("SELECT id,title,done FROM tasks ORDER BY id DESC LIMIT 100").fetchall() if authenticated() else []
        calls = con.execute("SELECT title,created_at,confirmed_at,state,history FROM voice_calls ORDER BY created_at DESC, rowid DESC LIMIT 10").fetchall() if authenticated() else []
    finally:
        con.close()
    return render_template_string(PAGE, logged_in=authenticated(), tasks=tasks, calls=calls, ai_ready=uses_openai() and bool(os.getenv("OPENAI_API_KEY")), local_mode=not uses_openai(), temporary_storage=str(DB).startswith("/tmp/"), csrf=session.get("csrf", ""))

@app.post("/login")
def login():
    import secrets
    pwd = os.getenv("MALAK_PASSWORD", "")
    if not pwd:
        flash("اضبط MALAK_PASSWORD في إعدادات الاستضافة أولاً.")
    elif hmac.compare_digest(request.form.get("password", ""), pwd):
        session.clear()
        session["logged_in"] = True
        session["csrf"] = secrets.token_urlsafe(24)
    else:
        flash("كلمة المرور غير صحيحة.")
    return redirect(url_for("index"))

@app.post("/logout")
def logout():
    guard()
    session.clear()
    return redirect(url_for("index"))

@app.post("/tasks")
def create_task():
    guard()
    title = request.form.get("title", "").strip()
    if not title or len(title) > 180:
        abort(400)
    con = db()
    try:
        con.execute("INSERT INTO tasks(title) VALUES (?)", (title,))
        con.commit()
    finally:
        con.close()
    return redirect(url_for("index"))

@app.post("/tasks/<int:task_id>/complete")
def complete_task(task_id):
    guard()
    con = db()
    try:
        row = con.execute("SELECT done FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row and not row["done"]:
            con.execute("UPDATE tasks SET done=1 WHERE id=?", (task_id,))
            con.commit()
            if request.form.get("call") == "1":
                flash(phone_call(task_id))
    finally:
        con.close()
    return redirect(url_for("index"))

@app.post("/test-call")
def test_call():
    guard()
    if request.form.get("confirm") != "yes":
        abort(400)
    flash(phone_call())
    return redirect(url_for("index"))

install_voice(app, db, VOICE, LANG)

@app.get("/health")
def health():
    return {"ok": True}

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080)
