"""
Kate & Tony — Wedding community website.

Two public sections (Photos, Wishes) and a private admin panel. Runs behind
nginx at https://tools.tankway.co.nz/wedding/.

Contributors add photos & wishes that stay private to them until the wedding
day (WEDDING_DATE, Fiji time), when the home page reveals everyone's together as
a Pinterest-style scrolling wall. The admin panel previews that wall live.

Design note: served under the /wedding/ subpath. PrefixMiddleware sets
SCRIPT_NAME so url_for() generates correct /wedding/... links.
"""

import os
import uuid
import sqlite3
import functools
from datetime import datetime, date, timezone

import pytz
from flask import (
    Flask, g, render_template, request, jsonify, Response, url_for,
)
from dotenv import load_dotenv

load_dotenv()

# --- Configuration -----------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "wedding.db")
DEMO_TAG = "::demo::"  # internal marker stripped from any demo content before display

URL_PREFIX = os.environ.get("URL_PREFIX", "").rstrip("/")
WEDDING_DATE = os.environ.get("WEDDING_DATE", "2026-08-20")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")

FIJI_TZ = pytz.timezone("Pacific/Fiji")
CONTRIB_COOKIE = "wed_contrib"  # per-browser id so contributors see only their own pre-reveal

import cloudinary
import cloudinary.uploader
import cloudinary.api

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
# The app is served two ways at once:
#   * tools.tankway.co.nz/wedding/  -> under the /wedding prefix (no X-Forwarded-
#     Prefix header, so it falls back to URL_PREFIX=/wedding)
#   * kateandtony.co.nz/            -> at the root (that vhost sends
#     `X-Forwarded-Prefix /`, which means "no prefix")
# The per-request header lets one process generate correct url_for() links for both.
class PrefixMiddleware:
    def __init__(self, wsgi_app, default_prefix=""):
        self.wsgi_app = wsgi_app
        self.default_prefix = default_prefix

    def __call__(self, environ, start_response):
        prefix = environ.get("HTTP_X_FORWARDED_PREFIX", self.default_prefix).rstrip("/")
        if prefix:
            environ["SCRIPT_NAME"] = prefix
            path = environ.get("PATH_INFO", "")
            if path.startswith(prefix):
                environ["PATH_INFO"] = path[len(prefix):] or "/"
        return self.wsgi_app(environ, start_response)


app = Flask(__name__)
app.wsgi_app = PrefixMiddleware(app.wsgi_app, default_prefix=URL_PREFIX)


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
    # `approved` now means "included in the wedding-day reveal & keepsake".
    # Contributions are visible by default (1); admin can hide (0) or delete.
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS photos (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            uploader_name        TEXT NOT NULL,
            cloudinary_url       TEXT NOT NULL,
            cloudinary_public_id TEXT,
            caption              TEXT,
            submitted_at         TEXT NOT NULL,
            approved             INTEGER NOT NULL DEFAULT 1,
            contributor_id       TEXT
        );

        CREATE TABLE IF NOT EXISTS wishes (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT NOT NULL,
            message        TEXT NOT NULL,
            submitted_at   TEXT NOT NULL,
            approved       INTEGER NOT NULL DEFAULT 1,
            contributor_id TEXT
        );

        -- The vault concept was removed; drop its table if upgrading.
        DROP TABLE IF EXISTS vault_messages;
        """
    )
    # Migrate older databases that predate the contributor column.
    for table in ("photos", "wishes"):
        cols = [r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()]
        if "contributor_id" not in cols:
            db.execute(f"ALTER TABLE {table} ADD COLUMN contributor_id TEXT")
    db.commit()
    db.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean(text):
    """Strip the internal demo marker from any user-facing text."""
    return (text or "").replace(" " + DEMO_TAG, "").replace(DEMO_TAG, "").strip()


def is_revealed():
    """True once the wedding day (Fiji time) has arrived — the big reveal."""
    try:
        wedding = date.fromisoformat(WEDDING_DATE)
    except ValueError:
        return False
    return datetime.now(FIJI_TZ).date() >= wedding


def balanced_interleave(photos, wishes):
    """Mix two lists in proportion so the scarcer type spreads evenly. Returns
    a list of ("photo"|"wish", row) tuples. Shared by the web reveal."""
    items = []
    i = j = 0
    npn, nwn = len(photos), len(wishes)
    while i < npn or j < nwn:
        if j >= nwn or (i < npn and i * nwn <= j * npn):
            items.append(("photo", photos[i])); i += 1
        else:
            items.append(("wish", wishes[j])); j += 1
    return items


@app.before_request
def ensure_contributor():
    """Give every browser a stable anonymous id so it can see its own
    contributions (and only its own) before the reveal — no login needed."""
    cid = request.cookies.get(CONTRIB_COOKIE)
    if not cid:
        cid = uuid.uuid4().hex
        g.new_contrib = True
    g.contrib_id = cid


@app.after_request
def save_contributor(response):
    if getattr(g, "new_contrib", False):
        response.set_cookie(
            CONTRIB_COOKIE, g.contrib_id,
            max_age=60 * 60 * 24 * 400, samesite="Lax",
            path=(URL_PREFIX + "/" if URL_PREFIX else "/"),
        )
    return response


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
    return {"wedding_date": WEDDING_DATE, "revealed": is_revealed()}


@app.context_processor
def asset_helpers():
    # Append the file's mtime as ?v= so browsers always fetch fresh CSS/JS
    # after a deploy (no more stale-cache "the site isn't refreshing").
    def static_v(filename):
        try:
            v = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
        except OSError:
            v = 0
        return url_for("static", filename=filename) + f"?v={v}"

    return {"static_v": static_v}


def tile_of(kind, row):
    """Flatten a DB row into a cleaned dict for the reveal masonry template."""
    if kind == "photo":
        return {"kind": "photo", "url": row["cloudinary_url"],
                "caption": clean(row["caption"]), "who": clean(row["uploader_name"])}
    return {"kind": "wish", "message": clean(row["message"]), "who": clean(row["name"])}


# --- Public pages ------------------------------------------------------------
@app.route("/")
def index():
    tiles = None
    if is_revealed():
        db = get_db()
        ps = db.execute(
            "SELECT * FROM photos WHERE approved = 1 ORDER BY submitted_at ASC"
        ).fetchall()
        ws = db.execute(
            "SELECT * FROM wishes WHERE approved = 1 ORDER BY submitted_at ASC"
        ).fetchall()
        tiles = [tile_of(kind, row) for kind, row in balanced_interleave(ps, ws)]
    return render_template("index.html", counts=counts(), tiles=tiles)


@app.route("/photos", methods=["GET"])
def photos():
    db = get_db()
    if is_revealed():
        rows = db.execute(
            "SELECT * FROM photos WHERE approved = 1 ORDER BY submitted_at DESC"
        ).fetchall()
    else:
        # Before the reveal, contributors see only the photos they uploaded.
        rows = db.execute(
            "SELECT * FROM photos WHERE contributor_id = ? ORDER BY submitted_at DESC",
            (g.contrib_id,),
        ).fetchall()
    return render_template(
        "photos.html", photos=rows, cloudinary_ready=CLOUDINARY_READY,
    )


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
        "caption, submitted_at, approved, contributor_id) VALUES (?, ?, ?, ?, ?, 1, ?)",
        (name, result.get("secure_url"), result.get("public_id"), caption, now_iso(),
         g.contrib_id),
    )
    db.commit()
    if is_revealed():
        msg = "Thank you! Your photo's been added to the album."
    else:
        msg = ("Thank you! Your photo is saved. For now only you can see it — "
               "everyone's photos are revealed together on the wedding day. 🌺")
    return jsonify(ok=True, message=msg)


@app.route("/wishes", methods=["GET"])
def wishes():
    db = get_db()
    if is_revealed():
        rows = db.execute(
            "SELECT * FROM wishes WHERE approved = 1 ORDER BY submitted_at DESC"
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM wishes WHERE contributor_id = ? ORDER BY submitted_at DESC",
            (g.contrib_id,),
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
        "INSERT INTO wishes (name, message, submitted_at, approved, contributor_id) "
        "VALUES (?, ?, ?, 1, ?)",
        (name, message, now_iso(), g.contrib_id),
    )
    db.commit()
    if is_revealed():
        msg = "Your wish has been added!"
    else:
        msg = "Your wish is saved — it'll be revealed with everyone's on the wedding day. 🌺"
    return jsonify(
        ok=True,
        message=msg,
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
                {"WWW-Authenticate": 'Basic realm="Kate & Tony Admin"'},
            )
        return view(*args, **kwargs)

    return wrapped


@app.route("/admin")
@require_admin
def admin():
    db = get_db()
    ps = db.execute(
        "SELECT * FROM photos WHERE approved = 1 ORDER BY submitted_at ASC"
    ).fetchall()
    ws = db.execute(
        "SELECT * FROM wishes WHERE approved = 1 ORDER BY submitted_at ASC"
    ).fetchall()
    tiles = [tile_of(kind, row) for kind, row in balanced_interleave(ps, ws)]
    return render_template("admin.html", tiles=tiles,
                           photo_count=len(ps), wish_count=len(ws))


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


def requested_ids():
    """Pull a list of integer ids from a bulk-action JSON body ({"ids": [...]}).
    Silently drops anything non-integer so one bad value can't fail the batch."""
    data = request.get_json(silent=True) or {}
    out = []
    for v in data.get("ids", []):
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


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


@app.route("/admin/api/photos/<int:pid>/hide", methods=["POST"])
@require_admin
def admin_photo_hide(pid):
    db = get_db()
    db.execute("UPDATE photos SET approved = 0 WHERE id = ?", (pid,))
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


# --- Bulk photo actions ------------------------------------------------------
# Each takes a JSON body {"ids": [...]} and applies one action to the whole set,
# so the admin can clear out a batch in a single click.
@app.route("/admin/api/photos/bulk-hide", methods=["POST"])
@require_admin
def admin_photos_bulk_hide(approved=0):
    ids = requested_ids()
    if not ids:
        return jsonify(ok=True, count=0)
    db = get_db()
    placeholders = ",".join("?" * len(ids))
    db.execute(f"UPDATE photos SET approved = ? WHERE id IN ({placeholders})",
               [approved, *ids])
    db.commit()
    return jsonify(ok=True, count=len(ids))


@app.route("/admin/api/photos/bulk-show", methods=["POST"])
@require_admin
def admin_photos_bulk_show():
    return admin_photos_bulk_hide(approved=1)


@app.route("/admin/api/photos/bulk-delete", methods=["POST"])
@require_admin
def admin_photos_bulk_delete():
    ids = requested_ids()
    if not ids:
        return jsonify(ok=True, count=0)
    db = get_db()
    placeholders = ",".join("?" * len(ids))
    rows = db.execute(
        f"SELECT cloudinary_public_id FROM photos WHERE id IN ({placeholders})", ids
    ).fetchall()
    if CLOUDINARY_READY:
        for row in rows:
            pubid = row["cloudinary_public_id"]
            if pubid and pubid != DEMO_TAG:
                try:
                    cloudinary.uploader.destroy(pubid)
                except Exception:
                    pass  # don't let one Cloudinary hiccup abort the DB cleanup
    db.execute(f"DELETE FROM photos WHERE id IN ({placeholders})", ids)
    db.commit()
    return jsonify(ok=True, count=len(ids))


@app.route("/admin/api/wishes")
@require_admin
def admin_wishes():
    db = get_db()
    rows = db.execute("SELECT * FROM wishes ORDER BY submitted_at DESC").fetchall()
    return jsonify(rows_to_dicts(rows))


@app.route("/admin/api/wishes/<int:wid>/hide", methods=["POST"])
@require_admin
def admin_wish_hide(wid):
    db = get_db()
    db.execute("UPDATE wishes SET approved = 0 WHERE id = ?", (wid,))
    db.commit()
    return jsonify(ok=True)


@app.route("/admin/api/wishes/<int:wid>/show", methods=["POST"])
@require_admin
def admin_wish_show(wid):
    db = get_db()
    db.execute("UPDATE wishes SET approved = 1 WHERE id = ?", (wid,))
    db.commit()
    return jsonify(ok=True)


@app.route("/admin/api/wishes/<int:wid>/delete", methods=["POST"])
@require_admin
def admin_wish_delete(wid):
    db = get_db()
    db.execute("DELETE FROM wishes WHERE id = ?", (wid,))
    db.commit()
    return jsonify(ok=True)


@app.route("/admin/api/wishes/bulk-delete", methods=["POST"])
@require_admin
def admin_wishes_bulk_delete():
    """Delete a whole set of wishes in one click. Body: {"ids": [...]}."""
    ids = requested_ids()
    if not ids:
        return jsonify(ok=True, count=0)
    db = get_db()
    placeholders = ",".join("?" * len(ids))
    db.execute(f"DELETE FROM wishes WHERE id IN ({placeholders})", ids)
    db.commit()
    return jsonify(ok=True, count=len(ids))


@app.route("/admin/api/cloudinary")
@require_admin
def admin_cloudinary_usage():
    """Live Cloudinary free-tier usage for the admin readout."""
    if not CLOUDINARY_READY:
        return jsonify(ready=False)
    try:
        u = cloudinary.api.usage()
    except Exception as exc:
        return jsonify(ready=True, error=str(exc)[:140])
    credits = u.get("credits") or {}
    storage = u.get("storage") or {}
    bandwidth = u.get("bandwidth") or {}
    objects = u.get("objects") or {}
    return jsonify(
        ready=True,
        plan=u.get("plan"),
        used_percent=credits.get("used_percent"),
        credits_used=credits.get("usage"),
        credits_limit=credits.get("limit"),
        storage_bytes=storage.get("usage"),
        bandwidth_bytes=bandwidth.get("usage"),
        objects=objects.get("usage"),
    )


# --- Bootstrap ---------------------------------------------------------------
init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005, debug=False)
