
import os, json, sqlite3, io, hashlib, time, uuid
from datetime import datetime
from PIL import Image, ImageFilter, ImageStat, ImageDraw, ImageFont
from flask import Flask, render_template, request, jsonify, url_for, abort
import qrcode
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

APP_NAME = "AGA Grading"
DB_PATH = os.getenv("DB_PATH","aga.db")
CERT_SALT = os.getenv("CERT_SALT","agasecret")

app = Flask(__name__, static_folder="static", template_folder="templates")

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, cert TEXT UNIQUE, cert_hash TEXT, name TEXT, email TEXT, title TEXT, service TEXT, grade TEXT, subgrades TEXT, created_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS registry (id INTEGER PRIMARY KEY AUTOINCREMENT, cert TEXT, display_name TEXT, note TEXT, created_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS pops (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, grade TEXT, qty INTEGER DEFAULT 0)")
    conn.commit()
init_db()

def secure_hash(cert:str):
    m = hashlib.sha256()
    m.update((CERT_SALT + cert).encode())
    return m.hexdigest()[:10]

def ai_grade_image(img: Image.Image):
    img = img.convert("RGB")
    small = img.resize((512,512))
    edges = small.filter(ImageFilter.FIND_EDGES).convert("L")
    sharp = ImageStat.Stat(edges).var[0] ** 0.5
    gray = small.convert("L")
    bright = ImageStat.Stat(gray).mean[0]
    corner_noise = ImageStat.Stat(gray.crop((0,0,64,64))).var[0] ** 0.5
    s = max(0,min(10, sharp/8))
    b = max(0,min(10, (bright-30)/15))
    c = max(0,min(10, 10 - corner_noise/6))
    sub = {"centering": round(b,1), "corners": round(c,1), "edges": round(s,1), "surface": round((s+b)/2,1)}
    overall = round((sub["centering"]+sub["corners"]+sub["edges"]+sub["surface"])/4,1)
    if overall >= 9.5: letter = "Gem 10"
    elif overall >= 8.5: letter = "Mint 9"
    elif overall >= 7.5: letter = "NM 8"
    else: letter = "VG 7"
    return letter, sub

def save_qr_png(text:str, path:str):
    qrcode.make(text).save(path)

def save_label_png(name, title, cert, qr_path, out_path):
    W,H = (900,300)
    im = Image.new("RGB",(W,H),(15,18,30))
    d = ImageDraw.Draw(im)
    try:
        font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    except:
        font_big = font_small = None
    d.rectangle([0,0,W,60], fill=(190,30,30))
    d.text((18,12),"AGA Grading", fill=(255,255,255), font=font_big)
    d.text((20,90), f"Submitter: {name}", fill=(235,235,240), font=font_small)
    d.text((20,140), f"Title: {title}", fill=(235,235,240), font=font_small)
    d.text((20,190), f"Cert: {cert}", fill=(235,235,240), font=font_small)
    if os.path.exists(qr_path):
        q = Image.open(qr_path).resize((200,200))
        im.paste(q, (W-220,80))
    im.save(out_path)

def save_cert_pdf(order, qr_path, out_path):
    c = canvas.Canvas(out_path, pagesize=letter)
    w,h = letter
    c.setFillColorRGB(0.12,0.14,0.22); c.rect(0,0,w,h,fill=1, stroke=0)
    c.setFillColorRGB(1,1,1)
    c.setFont("Helvetica-Bold", 28); c.drawString(72, h-90, "Authentic Grading Authority")
    c.setFont("Helvetica-Bold", 20); c.drawString(72, h-130, "Certificate of Grading")
    c.setFont("Helvetica", 12)
    c.drawString(72, h-170, f"Certification #: {order['cert']}")
    c.drawString(72, h-190, f"Title: {order['title']}")
    c.drawString(72, h-210, f"Grade: {order['grade']}")
    try:
        sub = json.loads(order["subgrades"]) if isinstance(order["subgrades"], str) else order["subgrades"]
    except:
        sub = {}
    c.drawString(72, h-230, "Subgrades: Ctr {0}  Corn {1}  Edg {2}  Surf {3}".format(
        sub.get("centering",""),sub.get("corners",""),sub.get("edges",""),sub.get("surface","")
    ))
    if os.path.exists(qr_path):
        c.drawImage(qr_path, w-200, h-260, 128,128, preserveAspectRatio=True, mask='auto')
    c.setFont("Helvetica-Oblique", 10); c.setFillColorRGB(0.85,0.85,0.85)
    c.drawString(72, 60, "Verify at AGA — scan QR for live cert page.")
    c.showPage(); c.save()

def pop_increment(title, grade):
    conn = get_db(); cur=conn.cursor()
    cur.execute("SELECT id, qty FROM pops WHERE title=? AND grade=?", (title, grade))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE pops SET qty=? WHERE id=?", (row["qty"]+1, row["id"]))
    else:
        cur.execute("INSERT INTO pops(title,grade,qty) VALUES(?,?,?)", (title, grade, 1))
    conn.commit()

@app.route("/")
def index():
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT COUNT(*), SUM(CASE WHEN grade='Gem 10' THEN 1 ELSE 0 END) FROM orders")
    total, gem10 = cur.fetchone()
    cur.execute("SELECT cert, title, grade, created_at FROM orders ORDER BY id DESC LIMIT 6")
    recent = cur.fetchall()
    return render_template("index.html", total=total or 0, gem10=gem10 or 0, recent=recent, app_name=APP_NAME)

@app.route("/pricing")
def pricing():
    return render_template("pricing.html", app_name=APP_NAME)

@app.route("/submit")
def submit():
    return render_template("submit.html", app_name=APP_NAME)

@app.route("/lookup")
def lookup_page():
    return render_template("lookup.html", app_name=APP_NAME)

@app.route("/registry")
def registry_page():
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT r.display_name, r.note, r.cert, o.title, o.grade, o.created_at FROM registry r LEFT JOIN orders o ON o.cert=r.cert ORDER BY r.id DESC LIMIT 25")
    rows=cur.fetchall()
    return render_template("registry.html", rows=rows, app_name=APP_NAME)

@app.route("/pop-report")
def pop_report():
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT title, grade, qty FROM pops ORDER BY title, grade")
    rows=cur.fetchall()
    return render_template("pop.html", rows=rows, app_name=APP_NAME)

@app.route("/c/<cert>/<h>")
def cert_view(cert,h):
    if h != secure_hash(cert): abort(404)
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT * FROM orders WHERE cert=?", (cert,))
    order=cur.fetchone()
    if not order: abort(404)
    qr_url = url_for("static", filename=f"qrcodes/{cert}.png")
    return render_template("cert.html", order=order, qr_url=qr_url, app_name=APP_NAME)

@app.route("/api/grade", methods=["POST"])
def api_grade():
    if "image" not in request.files:
        return jsonify(ok=False, error="No image"), 400
    f = request.files["image"]
    img = Image.open(f.stream)
    letter, sub = ai_grade_image(img)
    return jsonify(ok=True, grade=letter, subgrades=sub)

@app.route("/api/order", methods=["POST"])
def api_order():
    data = request.get_json(force=True)
    name = data.get("name",""); email = data.get("email","")
    service = data.get("service","standard")
    title = data.get("title","Sports Card")
    grade = data.get("grade","Pending")
    subgrades = data.get("subgrades",{})
    cert = str(int(time.time())) + "-" + uuid.uuid4().hex[:6].upper()
    cert_hash = secure_hash(cert)
    created_at = datetime.utcnow().isoformat()
    conn=get_db(); cur=conn.cursor()
    cur.execute("INSERT INTO orders(cert, cert_hash, name, email, title, service, grade, subgrades, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (cert, cert_hash, name, email, title, service, grade, json.dumps(subgrades), created_at))
    conn.commit()
    cert_url = url_for("cert_view", cert=cert, h=cert_hash, _external=True)
    qr_path = os.path.join(app.static_folder, "qrcodes", f"{cert}.png")
    label_path = os.path.join(app.static_folder, "labels", f"{cert}.png")
    pdf_path = os.path.join(app.static_folder, "certs", f"{cert}.pdf")
    qrcode.make(cert_url).save(qr_path)
    save_label_png(name, title, cert, qr_path, label_path)
    save_cert_pdf({"cert":cert,"title":title,"grade":grade,"subgrades":json.dumps(subgrades)}, qr_path, pdf_path)
    pop_increment(title, grade)
    return jsonify(ok=True,
                   cert=cert,
                   cert_url=cert_url,
                   qr_url=url_for('static', filename=f'qrcodes/{cert}.png', _external=True),
                   label_url=url_for('static', filename=f'labels/{cert}.png', _external=True),
                   pdf_url=url_for('static', filename=f'certs/{cert}.pdf', _external=True))

@app.route("/api/lookup")
def api_lookup():
    cert = request.args.get("cert","").strip()
    if not cert: return jsonify(ok=False, error="Missing cert"), 400
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT cert, title, grade, subgrades, created_at FROM orders WHERE cert=?", (cert,))
    row=cur.fetchone()
    if not row: return jsonify(ok=False, error="Not found"), 404
    try:
        sub = json.loads(row["subgrades"]) if row["subgrades"] else {}
    except: sub={}
    cur.execute("SELECT grade, qty FROM pops WHERE title=?", (row["title"],))
    pop = {r["grade"]: r["qty"] for r in cur.fetchall()}
    return jsonify(ok=True, cert=row["cert"], title=row["title"], grade=row["grade"], subgrades=sub, pop=pop)

@app.route("/api/registry", methods=["POST"])
def api_registry():
    data=request.get_json(force=True)
    cert=data.get("cert","").strip()
    display=data.get("display_name","").strip()
    note=data.get("note","").strip()
    if not cert or not display:
        return jsonify(ok=False, error="Missing fields"), 400
    conn=get_db(); cur=conn.cursor()
    cur.execute("INSERT INTO registry(cert, display_name, note, created_at) VALUES(?,?,?,?)",
                (cert, display, note, datetime.utcnow().isoformat()))
    conn.commit()
    return jsonify(ok=True)

@app.route("/api/stats")
def api_stats():
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT COUNT(*), SUM(CASE WHEN grade='Gem 10' THEN 1 ELSE 0 END) FROM orders")
    total, gem10 = cur.fetchone()
    return jsonify(ok=True, total=total or 0, gem10=gem10 or 0)

@app.route("/health")
def health():
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
