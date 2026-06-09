"""
Tony & Kate — Wedding community website.

Two public sections (Photos, Wishes) and a private admin panel. Runs behind
nginx at https://tools.tankway.co.nz/wedding/.

Once the wedding day (WEDDING_DATE) arrives, a daily scheduler job generates a
PDF keepsake e-book of every approved photo and well wish and emails it to the
couple (COUPLE_EMAIL). The admin panel can also preview/download the e-book or
send it on demand at any time.

Design notes:
  * Served under the /wedding/ subpath. PrefixMiddleware sets SCRIPT_NAME so
    url_for() generates correct /wedding/... links.
  * Under gunicorn -w 2 the scheduler is guarded by an exclusive file lock so
    only one worker runs it (the couple never gets a duplicate e-book email).
"""

import os
import io
import sqlite3
import smtplib
import calendar
import tempfile
import functools
import urllib.request
from datetime import datetime, date, timezone
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr

import pytz
from PIL import Image
from fpdf import FPDF
from flask import (
    Flask, g, render_template, request, jsonify, Response, send_file, url_for,
    after_this_request,
)
from dotenv import load_dotenv

load_dotenv()

# --- Configuration -----------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "wedding.db")
EBOOK_SENT_FLAG = os.path.join(BASE_DIR, ".ebook_sent")
FONT_DIR = "/usr/share/fonts/truetype/dejavu"
DEMO_TAG = "::demo::"  # stripped from any demo content before it reaches the PDF

URL_PREFIX = os.environ.get("URL_PREFIX", "").rstrip("/")
WEDDING_DATE = os.environ.get("WEDDING_DATE", "2026-08-20")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
COUPLE_EMAIL = os.environ.get("COUPLE_EMAIL", "")

# Values still left at their .env placeholders don't count as "configured".
_PLACEHOLDERS = {"your@email.com", "yourpassword", "tonyandkate@email.com"}


def _real(v):
    return bool(v) and v not in _PLACEHOLDERS


SMTP_READY = all(_real(v) for v in (SMTP_HOST, SMTP_USER, SMTP_PASS, COUPLE_EMAIL))

NZ_TZ = pytz.timezone("Pacific/Auckland")

import cloudinary
import cloudinary.uploader

CLOUDINARY_READY = all(
    v and not v.startswith("your_")
    for v in (CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET)
)
if CLOUDINARY_READY:
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
        secure=True,
    )


# --- WSGI prefix middleware --------------------------------------------------
class PrefixMiddleware:
    def __init__(self, wsgi_app, prefix=""):
        self.wsgi_app = wsgi_app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        if self.prefix:
            environ["SCRIPT_NAME"] = self.prefix
            path = environ.get("PATH_INFO", "")
            if path.startswith(self.prefix):
                environ["PATH_INFO"] = path[len(self.prefix):] or "/"
        return self.wsgi_app(environ, start_response)


app = Flask(__name__)
if URL_PREFIX:
    app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix=URL_PREFIX)


# --- Database ----------------------------------------------------------------
def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = g._db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_db(exc):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS photos (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            uploader_name        TEXT NOT NULL,
            cloudinary_url       TEXT NOT NULL,
            cloudinary_public_id TEXT,
            caption              TEXT,
            submitted_at         TEXT NOT NULL,
            approved             INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS wishes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            message      TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            approved     INTEGER NOT NULL DEFAULT 0
        );

        -- The vault concept was removed; drop its table if upgrading.
        DROP TABLE IF EXISTS vault_messages;
        """
    )
    db.commit()
    db.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean(text):
    """Strip the internal demo marker from any user-facing text."""
    return (text or "").replace(" " + DEMO_TAG, "").replace(DEMO_TAG, "").strip()


# --- Template helpers --------------------------------------------------------
@app.template_filter("timeago")
def timeago(value):
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = int((datetime.now(timezone.utc) - dt).total_seconds())
    if secs < 60:
        return "just now"
    mins = secs // 60
    if mins < 60:
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days < 7:
        return f"{days} day{'s' if days != 1 else ''} ago"
    weeks = days // 7
    if weeks < 5:
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    months = days // 30
    if months < 12:
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = days // 365
    return f"{years} year{'s' if years != 1 else ''} ago"


def counts():
    db = get_db()
    p = db.execute("SELECT COUNT(*) FROM photos WHERE approved = 1").fetchone()[0]
    w = db.execute("SELECT COUNT(*) FROM wishes WHERE approved = 1").fetchone()[0]
    return {"photos": p, "wishes": w}


@app.context_processor
def inject_globals():
    return {"wedding_date": WEDDING_DATE}


# --- Public pages ------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", counts=counts())


@app.route("/photos", methods=["GET"])
def photos():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM photos WHERE approved = 1 ORDER BY submitted_at DESC"
    ).fetchall()
    return render_template("photos.html", photos=rows, cloudinary_ready=CLOUDINARY_READY)


@app.route("/photos", methods=["POST"])
def upload_photo():
    name = (request.form.get("name") or "").strip()
    caption = (request.form.get("caption") or "").strip()
    file = request.files.get("photo")

    if not name or not file or not file.filename:
        return jsonify(ok=False, message="Please add your name and choose a photo."), 400
    if not CLOUDINARY_READY:
        return jsonify(
            ok=False,
            message="Photo uploads aren't configured yet. Please try again later.",
        ), 503

    try:
        result = cloudinary.uploader.upload(file, folder="wedding", resource_type="image")
    except Exception:
        return jsonify(ok=False, message="Sorry, that upload failed. Please try again."), 500

    db = get_db()
    db.execute(
        "INSERT INTO photos (uploader_name, cloudinary_url, cloudinary_public_id, "
        "caption, submitted_at, approved) VALUES (?, ?, ?, ?, ?, 0)",
        (name, result.get("secure_url"), result.get("public_id"), caption, now_iso()),
    )
    db.commit()
    return jsonify(ok=True, message="Thank you! Your photo is awaiting approval and will appear soon.")


@app.route("/wishes", methods=["GET"])
def wishes():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM wishes WHERE approved = 1 ORDER BY submitted_at DESC"
    ).fetchall()
    return render_template("wishes.html", wishes=rows)


@app.route("/wishes", methods=["POST"])
def add_wish():
    name = (request.form.get("name") or "").strip()
    message = (request.form.get("message") or "").strip()
    if not name or not message:
        return jsonify(ok=False, message="Please add your name and a message."), 400

    db = get_db()
    cur = db.execute(
        "INSERT INTO wishes (name, message, submitted_at, approved) VALUES (?, ?, ?, 1)",
        (name, message, now_iso()),
    )
    db.commit()
    return jsonify(
        ok=True,
        message="Your wish has been added!",
        wish={"id": cur.lastrowid, "name": name, "message": message, "timeago": "just now"},
    )


# --- Admin panel -------------------------------------------------------------
def check_auth(auth):
    return bool(auth) and auth.username == ADMIN_USER and auth.password == ADMIN_PASSWORD


def require_admin(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not check_auth(request.authorization):
            return Response(
                "Authentication required.",
                401,
                {"WWW-Authenticate": 'Basic realm="Tony & Kate Admin"'},
            )
        return view(*args, **kwargs)

    return wrapped


@app.route("/admin")
@require_admin
def admin():
    return render_template("admin.html")


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


@app.route("/admin/api/photos")
@require_admin
def admin_photos():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM photos ORDER BY approved ASC, submitted_at DESC"
    ).fetchall()
    return jsonify(rows_to_dicts(rows))


@app.route("/admin/api/photos/<int:pid>/approve", methods=["POST"])
@require_admin
def admin_photo_approve(pid):
    db = get_db()
    db.execute("UPDATE photos SET approved = 1 WHERE id = ?", (pid,))
    db.commit()
    return jsonify(ok=True)


@app.route("/admin/api/photos/<int:pid>/delete", methods=["POST"])
@require_admin
def admin_photo_delete(pid):
    db = get_db()
    row = db.execute("SELECT cloudinary_public_id FROM photos WHERE id = ?", (pid,)).fetchone()
    if row and row["cloudinary_public_id"] and row["cloudinary_public_id"] != DEMO_TAG and CLOUDINARY_READY:
        try:
            cloudinary.uploader.destroy(row["cloudinary_public_id"])
        except Exception:
            pass
    db.execute("DELETE FROM photos WHERE id = ?", (pid,))
    db.commit()
    return jsonify(ok=True)


@app.route("/admin/api/wishes")
@require_admin
def admin_wishes():
    db = get_db()
    rows = db.execute("SELECT * FROM wishes ORDER BY submitted_at DESC").fetchall()
    return jsonify(rows_to_dicts(rows))


@app.route("/admin/api/wishes/<int:wid>/delete", methods=["POST"])
@require_admin
def admin_wish_delete(wid):
    db = get_db()
    db.execute("DELETE FROM wishes WHERE id = ?", (wid,))
    db.commit()
    return jsonify(ok=True)


@app.route("/admin/api/ebook")
@require_admin
def admin_ebook_status():
    db = get_db()
    p = db.execute("SELECT COUNT(*) FROM photos WHERE approved = 1").fetchone()[0]
    w = db.execute("SELECT COUNT(*) FROM wishes WHERE approved = 1").fetchone()[0]
    return jsonify(
        photos=p,
        wishes=w,
        wedding_date=WEDDING_DATE,
        auto_sent=os.path.exists(EBOOK_SENT_FLAG),
        smtp_ready=SMTP_READY,
        couple_email=COUPLE_EMAIL,
        deliver_on=(delivery_date().isoformat() if delivery_date() else None),
    )


@app.route("/admin/ebook")
@require_admin
def admin_ebook():
    """Generate the keepsake on demand and stream it back as a PDF download."""
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    generate_ebook(path)

    @after_this_request
    def cleanup(response):
        try:
            os.remove(path)
        except OSError:
            pass
        return response

    return send_file(
        path, mimetype="application/pdf", as_attachment=True,
        download_name="Tony-and-Kate-Keepsake.pdf",
    )


@app.route("/admin/ebook/send", methods=["POST"])
@require_admin
def admin_ebook_send():
    if not SMTP_READY:
        return jsonify(ok=False, message="Email isn't configured yet — set SMTP_* and COUPLE_EMAIL in .env."), 400
    if send_ebook_email():
        return jsonify(ok=True, message=f"Sent! The keepsake e-book is on its way to {COUPLE_EMAIL}.")
    return jsonify(ok=False, message="Sending failed — check the SMTP settings and server logs."), 500


# --- Keepsake e-book (PDF, landscape masonry) --------------------------------
TEAL = (47, 126, 122)
INK = (74, 64, 52)
SOFT = (138, 125, 104)
GOLD = (201, 168, 106)
CREAM = (255, 250, 243)
AQUA_SOFT = (216, 239, 236)
SAND = (239, 227, 210)
SAND_DEEP = (231, 220, 203)
WISH_BGS = (CREAM, AQUA_SOFT, SAND)

# Masonry geometry (millimetres, A4 landscape = 297 x 210).
MARGIN = 12
GUTTER = 6
NCOLS = 4
PAD = 5            # inner padding of wish tiles
FS_MSG, LH_MSG = 10, 5.0
FS_NAME, LH_NAME = 9, 5.0
FS_CAP, LH_CAP = 9, 4.6
FS_WHO, LH_WHO = 8, 4.4


def _fetch_bytes(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 wedding-ebook"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _process_image(data, max_side=1400):
    """Downscale/normalise to JPEG so the PDF stays small. Returns (bytes, w, h)."""
    im = Image.open(io.BytesIO(data))
    if im.mode not in ("RGB", "L"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        im = im.convert("RGBA")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    return buf.getvalue(), im.width, im.height


def _setup_fonts(pdf):
    """Register DejaVu Serif for full-unicode text; fall back to core Times."""
    serif = os.path.join(FONT_DIR, "DejaVuSerif.ttf")
    serif_b = os.path.join(FONT_DIR, "DejaVuSerif-Bold.ttf")
    if os.path.exists(serif) and os.path.exists(serif_b):
        pdf.add_font("serif", "", serif)
        pdf.add_font("serif", "B", serif_b)
        return "serif", True
    return "Times", False


def _wrap(pdf, text, max_w):
    """Word-wrap text to max_w using the currently-selected font."""
    lines = []
    for para in (text or "").split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = ""
        for w in words:
            # Break a single word that's wider than the column.
            while pdf.get_string_width(w) > max_w and len(w) > 1:
                cut = len(w)
                while cut > 1 and pdf.get_string_width(w[:cut]) > max_w:
                    cut -= 1
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(w[:cut])
                w = w[cut:]
            trial = (cur + " " + w).strip()
            if not cur or pdf.get_string_width(trial) <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
    return lines


def generate_ebook(out_path):
    """Build a landscape keepsake: a cover, then a Pinterest-style masonry of
    photo and well-wish tiles interleaved across the pages."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    wish_rows = db.execute(
        "SELECT * FROM wishes WHERE approved = 1 ORDER BY submitted_at ASC"
    ).fetchall()
    photo_rows = db.execute(
        "SELECT * FROM photos WHERE approved = 1 ORDER BY submitted_at ASC"
    ).fetchall()
    db.close()

    pdf = FPDF(orientation="L", format="A4")
    pdf.set_auto_page_break(False)
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    fam, uni = _setup_fonts(pdf)
    PW, PH = pdf.w, pdf.h
    col_w = (PW - 2 * MARGIN - (NCOLS - 1) * GUTTER) / NCOLS
    page_bottom = PH - MARGIN

    def t(s):
        s = s or ""
        return s if uni else s.encode("latin-1", "replace").decode("latin-1")

    # ---- Cover ----
    pdf.add_page()
    pdf.set_y(46)
    pdf.set_font(fam, "", 16)
    pdf.set_text_color(*SOFT)
    pdf.cell(0, 9, t("together with their families"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font(fam, "B", 48)
    pdf.set_text_color(*INK)
    pdf.cell(0, 20, t("Tony & Kate"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_draw_color(*GOLD)
    pdf.set_line_width(0.8)
    pdf.line(PW / 2 - 32, pdf.get_y(), PW / 2 + 32, pdf.get_y())
    pdf.ln(9)
    pdf.set_font(fam, "", 19)
    pdf.set_text_color(*TEAL)
    pdf.cell(0, 11, t("20 August 2026  ·  Fiji"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(16)
    pdf.set_font(fam, "", 13)
    pdf.set_text_color(*SOFT)
    pdf.multi_cell(
        0, 7,
        t("A keepsake of the photos and well wishes shared by everyone who "
          "celebrated your love."),
        align="C", new_x="LMARGIN", new_y="NEXT",
    )

    # ---- Pre-fetch & normalise photos (need real dimensions for packing) ----
    photos = []
    for p in photo_rows:
        try:
            jpeg, iw, ih = _process_image(_fetch_bytes(p["cloudinary_url"]))
        except Exception:
            continue  # skip unreachable / broken images
        photos.append({"data": jpeg, "iw": iw, "ih": ih,
                       "caption": clean(p["caption"]), "who": clean(p["uploader_name"])})

    # ---- Balanced interleave of photos & wishes -------------------------------
    # There will usually be many more of one than the other. Rather than dumping
    # all of the majority then the minority (which reads as lopsided), we walk
    # both lists in proportion so the scarcer type is spread evenly across the
    # whole book — e.g. 200 photos + 10 wishes ⇒ a wish roughly every 20 tiles.
    # The masonry packer below then scatters those tiles across columns, so each
    # page stays a balanced mix of pictures and messages.
    items = []
    i = j = 0
    npn, nwn = len(photos), len(wish_rows)
    while i < npn or j < nwn:
        # Place whichever list is proportionally "behind" so far.
        if j >= nwn or (i < npn and i * nwn <= j * npn):
            items.append(("photo", photos[i])); i += 1
        else:
            items.append(("wish", wish_rows[j])); j += 1

    if not items:
        pdf.output(out_path)
        return out_path

    # ---- Masonry placement ----
    state = {"cols": None, "first": True}

    def start_page():
        pdf.add_page()
        top = MARGIN
        if state["first"]:
            pdf.set_font(fam, "B", 20)
            pdf.set_text_color(*INK)
            pdf.set_xy(MARGIN, MARGIN - 1)
            pdf.cell(PW - 2 * MARGIN, 11, t("Photos & Well Wishes"),
                     align="C", new_x="LMARGIN", new_y="NEXT")
            y = pdf.get_y()
            pdf.set_draw_color(*GOLD)
            pdf.set_line_width(0.6)
            pdf.line(PW / 2 - 22, y, PW / 2 + 22, y)
            top = MARGIN + 16
            state["first"] = False
        state["cols"] = [top] * NCOLS

    def place(height, render):
        cands = [c for c in range(NCOLS) if state["cols"][c] + height <= page_bottom]
        if not cands:
            start_page()
            cands = list(range(NCOLS))
        c = min(cands, key=lambda c: state["cols"][c])
        x = MARGIN + c * (col_w + GUTTER)
        y = state["cols"][c]
        render(x, y)
        state["cols"][c] += height + GUTTER

    def draw_card(x, y, w, h, bg):
        pdf.set_fill_color(*bg)
        pdf.set_draw_color(*SAND_DEEP)
        pdf.set_line_width(0.3)
        try:
            pdf.rect(x, y, w, h, style="DF", round_corners=True, corner_radius=2.5)
        except Exception:
            pdf.rect(x, y, w, h, style="DF")

    start_page()
    wish_i = 0
    for kind, obj in items:
        if kind == "wish":
            inner = col_w - 2 * PAD
            pdf.set_font(fam, "", FS_MSG)
            msg_lines = _wrap(pdf, t("“" + clean(obj["message"]) + "”"), inner)
            pdf.set_font(fam, "B", FS_NAME)
            name_lines = _wrap(pdf, t("— " + clean(obj["name"])), inner)

            # Clamp pathologically long wishes so a tile never exceeds a page.
            max_msg = int((page_bottom - MARGIN - 2 * PAD - 4 - len(name_lines) * LH_NAME) / LH_MSG)
            if max_msg < 1:
                max_msg = 1
            if len(msg_lines) > max_msg:
                msg_lines = msg_lines[:max_msg]
                msg_lines[-1] = (msg_lines[-1].rstrip("”").rstrip() + " …”")

            h = PAD + len(msg_lines) * LH_MSG + 3 + len(name_lines) * LH_NAME + PAD
            bg = WISH_BGS[wish_i % len(WISH_BGS)]
            wish_i += 1

            def render(x, y, ml=msg_lines, nl=name_lines, h=h, bg=bg):
                draw_card(x, y, col_w, h, bg)
                ty = y + PAD
                pdf.set_font(fam, "", FS_MSG)
                pdf.set_text_color(*INK)
                for ln in ml:
                    pdf.set_xy(x + PAD, ty)
                    pdf.cell(col_w - 2 * PAD, LH_MSG, ln)
                    ty += LH_MSG
                ty += 3
                pdf.set_font(fam, "B", FS_NAME)
                pdf.set_text_color(*TEAL)
                for ln in nl:
                    pdf.set_xy(x + PAD, ty)
                    pdf.cell(col_w - 2 * PAD, LH_NAME, ln)
                    ty += LH_NAME

            place(h, render)
        else:
            iw, ih = obj["iw"], obj["ih"]
            img_w = col_w
            img_h = img_w * ih / iw
            cap = obj["caption"]
            who = ("— " + obj["who"]) if obj["who"] else ""
            cap_inner = col_w - 2
            pdf.set_font(fam, "", FS_CAP)
            cap_lines = _wrap(pdf, t(cap), cap_inner) if cap else []
            pdf.set_font(fam, "B", FS_WHO)
            who_lines = _wrap(pdf, t(who), cap_inner) if who else []
            cap_h = (3 + len(cap_lines) * LH_CAP + len(who_lines) * LH_WHO + 1) if (cap_lines or who_lines) else 2

            max_img_h = page_bottom - MARGIN - cap_h
            if img_h > max_img_h:
                img_h = max_img_h
                img_w = img_h * iw / ih
            h = img_h + cap_h

            def render(x, y, data=obj["data"], iw_=img_w, ih_=img_h, cl=cap_lines, wl=who_lines):
                ix = x + (col_w - iw_) / 2
                pdf.image(io.BytesIO(data), x=ix, y=y, w=iw_, h=ih_)
                ty = y + ih_ + 3
                if cl:
                    pdf.set_font(fam, "", FS_CAP)
                    pdf.set_text_color(*INK)
                    for ln in cl:
                        pdf.set_xy(x, ty)
                        pdf.cell(col_w, LH_CAP, ln, align="C")
                        ty += LH_CAP
                if wl:
                    pdf.set_font(fam, "B", FS_WHO)
                    pdf.set_text_color(*SOFT)
                    for ln in wl:
                        pdf.set_xy(x, ty)
                        pdf.cell(col_w, LH_WHO, ln, align="C")
                        ty += LH_WHO

            place(h, render)

    pdf.output(out_path)
    return out_path


def send_ebook_email():
    """Generate the keepsake and email it to COUPLE_EMAIL. Returns True on success."""
    if not SMTP_READY:
        app.logger.warning("E-book delivery skipped: SMTP/COUPLE_EMAIL not configured.")
        return False

    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        generate_ebook(path)

        html = """\
        <div style="max-width:600px;margin:0 auto;padding:32px 22px;background:#f7efe3;
                    font-family:Helvetica,Arial,sans-serif;color:#5a5040;">
          <h1 style="font-family:Georgia,serif;color:#2f7e7a;font-weight:400;font-size:30px;
                     text-align:center;margin:0 0 6px;">Tony &amp; Kate</h1>
          <p style="text-align:center;color:#9b8e7a;letter-spacing:.12em;text-transform:uppercase;
                    font-size:12px;margin:0 0 26px;">your wedding keepsake</p>
          <p style="font-size:15px;line-height:1.7;">Congratulations! Attached is your keepsake
             e-book — every photo and well wish that friends and family shared with you,
             gathered into one PDF to keep forever.</p>
          <p style="font-size:15px;line-height:1.7;">With love, from everyone who celebrated with you. 💛</p>
        </div>"""

        msg = MIMEMultipart()
        msg["Subject"] = "Your wedding keepsake e-book \U0001f49b"
        msg["From"] = formataddr(("Tony & Kate", SMTP_USER))
        msg["To"] = COUPLE_EMAIL
        msg.attach(MIMEText(html, "html", "utf-8"))

        with open(path, "rb") as f:
            part = MIMEApplication(f.read(), _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename="Tony-and-Kate-Keepsake.pdf")
        msg.attach(part)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=40) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [COUPLE_EMAIL], msg.as_string())
        app.logger.info("Keepsake e-book emailed to %s.", COUPLE_EMAIL)
        return True
    except Exception as exc:
        app.logger.error("E-book email failed: %s", exc)
        return False
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def add_one_month(d):
    """Return the date one calendar month after d (clamping the day if needed)."""
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


def delivery_date():
    """When the keepsake is sent: one month after the wedding day."""
    try:
        return add_one_month(date.fromisoformat(WEDDING_DATE))
    except ValueError:
        return None


def check_and_send_ebook():
    """Daily job: one month after the wedding day, send the keepsake once.

    Waiting a month lets late photos and wishes trickle in, so the couple get a
    fuller keepsake rather than one captured the moment the ceremony ends.
    """
    if os.path.exists(EBOOK_SENT_FLAG):
        return
    deliver_on = delivery_date()
    if deliver_on is None:
        return
    if datetime.now(NZ_TZ).date() < deliver_on:
        return
    if send_ebook_email():
        with open(EBOOK_SENT_FLAG, "w") as f:
            f.write(now_iso())
        app.logger.info("Keepsake e-book auto-delivered (one month after the wedding).")


_scheduler_lock = None


def start_scheduler():
    """Start the daily 09:00 NZ keepsake check in exactly one process."""
    global _scheduler_lock
    try:
        import fcntl

        _scheduler_lock = open(os.path.join(BASE_DIR, ".scheduler.lock"), "w")
        try:
            fcntl.flock(_scheduler_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            _scheduler_lock.close()
            _scheduler_lock = None
            return
    except ImportError:
        pass

    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone=NZ_TZ)
    scheduler.add_job(check_and_send_ebook, "cron", hour=9, minute=0, id="ebook_daily")
    scheduler.start()
    app.logger.info("Keepsake scheduler started (daily 09:00 Pacific/Auckland).")


# --- Bootstrap ---------------------------------------------------------------
init_db()
start_scheduler()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005, debug=False)
