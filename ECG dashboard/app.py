"""ECG cloud backend: login/registration, guardian links, MQTT ingest,
daily history, abnormal-rhythm alerts and SMS."""
import json, random, re, secrets, sqlite3, threading, time
from datetime import datetime, timedelta
from functools import wraps

import paho.mqtt.client as mqtt
import requests
from flask import Flask, g, jsonify, redirect, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

import config

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  role TEXT NOT NULL CHECK(role IN ('patient','guardian')),
  name TEXT NOT NULL, mobile TEXT NOT NULL, password_hash TEXT NOT NULL,
  age INTEGER, email TEXT, patient_code TEXT UNIQUE,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(role, mobile));
CREATE TABLE IF NOT EXISTS links(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guardian_id INTEGER NOT NULL, patient_code TEXT NOT NULL, relation TEXT NOT NULL,
  UNIQUE(guardian_id, patient_code));
CREATE TABLE IF NOT EXISTS readings(
  id INTEGER PRIMARY KEY AUTOINCREMENT, patient_code TEXT NOT NULL,
  ts INTEGER NOT NULL, bpm INTEGER, rhythm TEXT, battery INTEGER);
CREATE INDEX IF NOT EXISTS idx_readings ON readings(patient_code, ts);
CREATE TABLE IF NOT EXISTS alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, patient_code TEXT NOT NULL,
  ts INTEGER NOT NULL, kind TEXT, bpm INTEGER, message TEXT, sms_status TEXT);
"""


# ---------------------------------------------------------------- database
def connect_db():
    db = sqlite3.connect(config.DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def get_db():
    if "db" not in g:
        g.db = connect_db()
    return g.db


@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    db = connect_db()
    db.executescript(SCHEMA)
    db.commit()
    db.close()


# ----------------------------------------------------------------- helpers
def clean_mobile(v):
    d = re.sub(r"\D", "", v or "")[-10:]
    return d if re.fullmatch(r"[6-9]\d{9}", d) else None


def err(msg, code=400):
    return jsonify(error=msg), code


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **k):
        if "uid" not in session:
            return err("Please log in.", 401)
        return fn(*a, **k)
    return wrapper


def can_view(db, code):
    if session.get("role") == "patient":
        q = "SELECT 1 FROM users WHERE id=? AND patient_code=?"
    else:
        q = "SELECT 1 FROM links WHERE guardian_id=? AND patient_code=?"
    return db.execute(q, (session.get("uid"), code)).fetchone() is not None


# ------------------------------------------------------------------- pages
@app.get("/")
def home():
    if "uid" in session:
        return redirect("/dashboard")
    return render_template("auth.html")


@app.get("/dashboard")
def dashboard():
    if "uid" not in session:
        return redirect("/")
    cfg = dict(wsUrl=config.MQTT_WS_URL, root=config.TOPIC_ROOT,
               role=session["role"], name=session["name"])
    return render_template("dashboard.html", cfg=cfg, name=session["name"], role=session["role"])


# --------------------------------------------------------------- auth API
@app.post("/api/register/patient")
def register_patient():
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    mobile = clean_mobile(d.get("mobile"))
    pw = d.get("password") or ""
    try:
        age = int(d.get("age"))
    except (TypeError, ValueError):
        age = 0
    if len(name) < 2 or not mobile or len(pw) < 6 or not 1 <= age <= 120:
        return err("Please fill all fields correctly (10-digit mobile, password of 6+ characters).")
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE role='patient' AND mobile=?", (mobile,)).fetchone():
        return err("This mobile number is already registered as a patient.", 409)
    for _ in range(50):
        code = f"ECG{random.randint(1000, 9999)}"
        if not db.execute("SELECT 1 FROM users WHERE patient_code=?", (code,)).fetchone():
            break
    cur = db.execute(
        "INSERT INTO users(role,name,mobile,password_hash,age,email,patient_code) "
        "VALUES('patient',?,?,?,?,?,?)",
        (name, mobile, generate_password_hash(pw), age, (d.get("email") or "").strip(), code))
    db.commit()
    session.clear()
    session.update(uid=cur.lastrowid, role="patient", name=name)
    return jsonify(ok=True, patient_code=code)


@app.post("/api/register/guardian")
def register_guardian():
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    mobile = clean_mobile(d.get("mobile"))
    pw = d.get("password") or ""
    code = (d.get("patient_code") or "").strip().upper()
    relation = (d.get("relation") or "").strip()
    if len(name) < 2 or not mobile or len(pw) < 6 or not relation:
        return err("Please fill all fields correctly (10-digit mobile, password of 6+ characters).")
    db = get_db()
    if not db.execute("SELECT 1 FROM users WHERE role='patient' AND patient_code=?", (code,)).fetchone():
        return err("No patient found with that Patient ID. Check the ID shown after the patient registered.", 404)
    if db.execute("SELECT 1 FROM users WHERE role='guardian' AND mobile=?", (mobile,)).fetchone():
        return err("This mobile number is already registered as a guardian. Please log in.", 409)
    cur = db.execute("INSERT INTO users(role,name,mobile,password_hash) VALUES('guardian',?,?,?)",
                     (name, mobile, generate_password_hash(pw)))
    db.execute("INSERT INTO links(guardian_id,patient_code,relation) VALUES(?,?,?)",
               (cur.lastrowid, code, relation))
    db.commit()
    session.clear()
    session.update(uid=cur.lastrowid, role="guardian", name=name)
    return jsonify(ok=True)


@app.post("/api/login")
def login():
    d = request.get_json(silent=True) or {}
    role = d.get("role") if d.get("role") in ("patient", "guardian") else "patient"
    mobile = clean_mobile(d.get("mobile"))
    u = get_db().execute("SELECT * FROM users WHERE role=? AND mobile=?", (role, mobile)).fetchone() if mobile else None
    if not u or not check_password_hash(u["password_hash"], d.get("password") or ""):
        return err("Wrong mobile number or password.", 401)
    session.clear()
    session.update(uid=u["id"], role=u["role"], name=u["name"])
    return jsonify(ok=True)


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


# --------------------------------------------------------------- data API
@app.get("/api/patients")
@login_required
def patients():
    db = get_db()
    if session["role"] == "patient":
        rows = db.execute("SELECT patient_code code, name, age, 'Self' relation FROM users WHERE id=?",
                          (session["uid"],)).fetchall()
    else:
        rows = db.execute(
            "SELECT u.patient_code code, u.name, u.age, l.relation FROM links l "
            "JOIN users u ON u.patient_code=l.patient_code WHERE l.guardian_id=?",
            (session["uid"],)).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/summary")
@login_required
def summary():
    code = request.args.get("patient", "")
    db = get_db()
    if not can_view(db, code):
        return err("Not allowed.", 403)
    days = 7
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    t0 = int(start.timestamp())
    avg = {r["d"]: r["a"] for r in db.execute(
        "SELECT date(ts,'unixepoch','localtime') d, ROUND(AVG(bpm)) a FROM readings "
        "WHERE patient_code=? AND ts>=? AND bpm>0 GROUP BY d", (code, t0))}
    abn = {r["d"]: r["c"] for r in db.execute(
        "SELECT date(ts,'unixepoch','localtime') d, COUNT(*) c FROM alerts "
        "WHERE patient_code=? AND ts>=? GROUP BY d", (code, t0))}
    out = []
    for i in range(days):
        day = (start + timedelta(days=i))
        k = day.strftime("%Y-%m-%d")
        out.append(dict(date=k, label=day.strftime("%a %d"), avg_bpm=avg.get(k, 0), abnormal=abn.get(k, 0)))
    return jsonify(out)


@app.get("/api/alerts")
@login_required
def alerts():
    code = request.args.get("patient", "")
    db = get_db()
    if not can_view(db, code):
        return err("Not allowed.", 403)
    rows = db.execute("SELECT ts,kind,bpm,message,sms_status FROM alerts "
                      "WHERE patient_code=? ORDER BY ts DESC LIMIT 20", (code,)).fetchall()
    return jsonify([dict(r) for r in rows])


# -------------------------------------------------------------------- SMS
def send_sms(number, text):
    p = config.SMS_PROVIDER
    try:
        if p == "fast2sms":
            r = requests.post("https://www.fast2sms.com/dev/bulkV2",
                              headers={"authorization": config.FAST2SMS_KEY},
                              data={"route": "q", "message": text, "numbers": number, "flash": "0"},
                              timeout=15)
            ok = r.ok and r.json().get("return") is True
            return "sent" if ok else f"failed: {r.text[:80]}"
        if p == "twilio":
            r = requests.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{config.TWILIO_SID}/Messages.json",
                auth=(config.TWILIO_SID, config.TWILIO_TOKEN),
                data={"From": config.TWILIO_FROM, "To": "+91" + number, "Body": text}, timeout=15)
            return "sent" if r.ok else f"failed: {r.text[:80]}"
    except Exception as e:
        return f"failed: {e}"
    print(f"[SMS simulated] to {number}: {text}")
    return "simulated"


def sms_job(alert_id, numbers, text):
    status = "no guardian linked" if not numbers else ", ".join(send_sms(n, text) for n in numbers)
    db = connect_db()
    db.execute("UPDATE alerts SET sms_status=? WHERE id=?", (status[:200], alert_id))
    db.commit()
    db.close()


# ------------------------------------------------------------------- MQTT
_tl = threading.local()
last_store, last_alert = {}, {}


def mdb():
    if not hasattr(_tl, "db"):
        _tl.db = connect_db()
    return _tl.db


def raise_alert(client, db, code, kind, bpm):
    name = db.execute("SELECT name FROM users WHERE patient_code=?", (code,)).fetchone()["name"]
    now = int(time.time())
    text = f"ALERT: {name} ({code}) - {kind} detected, heart rate {bpm} BPM. Please check on them."
    cur = db.execute("INSERT INTO alerts(patient_code,ts,kind,bpm,message,sms_status) VALUES(?,?,?,?,?,'pending')",
                     (code, now, kind, bpm, text))
    db.commit()
    numbers = [r["mobile"] for r in db.execute(
        "SELECT u.mobile FROM links l JOIN users u ON u.id=l.guardian_id WHERE l.patient_code=?", (code,))]
    client.publish(f"{config.TOPIC_ROOT}/{code}/alert",
                   json.dumps(dict(kind=kind, bpm=bpm, message=text, ts=now)))
    threading.Thread(target=sms_job, args=(cur.lastrowid, numbers, text), daemon=True).start()


def on_message(client, userdata, msg):
    try:
        code = msg.topic.split("/")[1]
        d = json.loads(msg.payload)
    except Exception:
        return
    if not re.fullmatch(r"ECG\d{4}", code):
        return
    db = mdb()
    if not db.execute("SELECT 1 FROM users WHERE patient_code=?", (code,)).fetchone():
        return                                   # unregistered patient: ignore
    now = int(time.time())
    bpm = d.get("bpm") if isinstance(d.get("bpm"), (int, float)) else 0
    rhythm = str(d.get("rhythm", "Normal"))
    if now - last_store.get(code, 0) >= config.STORE_EVERY_S:
        db.execute("INSERT INTO readings(patient_code,ts,bpm,rhythm,battery) VALUES(?,?,?,?,?)",
                   (code, now, int(bpm), rhythm, d.get("battery")))
        db.commit()
        last_store[code] = now
    kind = None
    if rhythm != "Normal":
        kind = rhythm
    elif bpm > config.BPM_HIGH:
        kind = "Tachycardia"
    elif 0 < bpm < config.BPM_LOW:
        kind = "Bradycardia"
    if kind and now - last_alert.get((code, kind), 0) >= config.ALERT_COOLDOWN_S:
        last_alert[(code, kind)] = now
        raise_alert(client, db, code, kind, int(bpm))


def start_mqtt():
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"ecg-backend-{secrets.token_hex(3)}")

    def on_connect(cl, ud, flags, rc, props=None):
        print("MQTT connected:", rc)
        cl.subscribe(f"{config.TOPIC_ROOT}/+/live")

    c.on_connect, c.on_message = on_connect, on_message
    c.connect_async(config.MQTT_HOST, config.MQTT_PORT, 60)
    c.loop_start()
    return c


init_db()

if __name__ == "__main__":
    start_mqtt()
    print("Open http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)   # keep debug off: one MQTT client only
