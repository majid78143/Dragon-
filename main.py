import hmac
import io
import json
import os
import posixpath
import re
import secrets
import zipfile
from datetime import datetime, timezone
from functools import wraps
from pathlib import PurePosixPath

import requests
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

try:
    import firebase_admin
    from firebase_admin import credentials, firestore, storage
except ImportError:
    firebase_admin = None
    credentials = firestore = storage = None


app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dragon-vault-local-key")
app.config["MAX_CONTENT_LENGTH"] = 60 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    "html",
    "htm",
    "css",
    "js",
    "mjs",
    "json",
    "txt",
    "svg",
    "png",
    "jpg",
    "jpeg",
    "webp",
    "gif",
    "ico",
    "woff",
    "woff2",
    "ttf",
    "otf",
}
DEFAULT_CATEGORIES = ["Landing Pages", "Templates", "Components", "Websites", "Experiments", "Other"]
FIREBASE_DB = None
FIREBASE_BUCKET = None
FIREBASE_ERROR = None


def setup_firebase():
    global FIREBASE_DB, FIREBASE_BUCKET, FIREBASE_ERROR
    if FIREBASE_DB is not None:
        return
    if firebase_admin is None:
        FIREBASE_ERROR = "Firebase SDK is not installed."
        return
    raw_credentials = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not raw_credentials:
        FIREBASE_ERROR = "FIREBASE_SERVICE_ACCOUNT_JSON is not configured."
        return
    try:
        service_account = json.loads(raw_credentials)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(
                credentials.Certificate(service_account),
                {
                    "storageBucket": os.environ.get(
                        "FIREBASE_STORAGE_BUCKET",
                        "connecto-5814d.firebasestorage.app",
                    )
                },
            )
        FIREBASE_DB = firestore.client()
        FIREBASE_BUCKET = storage.bucket()
    except Exception:
        FIREBASE_ERROR = "Firebase could not be initialized. Check the service account and Firestore/Storage setup."


setup_firebase()


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_authenticated"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def clean_asset_path(filename):
    raw = (filename or "").replace("\\", "/").strip()
    raw = posixpath.normpath(raw).lstrip("/")
    if not raw or raw == "." or raw.startswith("../") or "/../" in raw:
        return None
    pieces = [secure_filename(piece) for piece in PurePosixPath(raw).parts]
    pieces = [piece for piece in pieces if piece]
    if not pieces:
        return None
    return "/".join(pieces)


def allowed_file(filename):
    path = clean_asset_path(filename)
    return bool(path and "." in path and path.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS)


def safe_slug(value):
    value = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return value[:70] or f"asset-{secrets.token_hex(4)}"


def unique_slug(title, current_id=None):
    base = safe_slug(title)
    if FIREBASE_DB is None:
        return base
    candidate = base
    counter = 2
    while True:
        matches = list(FIREBASE_DB.collection("assets").where("slug", "==", candidate).limit(1).stream())
        if not matches or (current_id and matches[0].id == current_id):
            return candidate
        candidate = f"{base}-{counter}"
        counter += 1


def timestamp_value(value):
    if hasattr(value, "timestamp"):
        return datetime.fromtimestamp(value.timestamp(), tz=timezone.utc).strftime("%b %d, %Y")
    return str(value or "Just now")


def asset_view(doc_id, data):
    result = dict(data)
    result["id"] = doc_id
    result["created_label"] = timestamp_value(result.get("createdAt"))
    result["updated_label"] = timestamp_value(result.get("updatedAt"))
    result["file_count"] = len(result.get("files", []))
    return result


def list_assets(include_private=False):
    if FIREBASE_DB is None:
        return []
    try:
        query = FIREBASE_DB.collection("assets")
        if not include_private:
            query = query.where("status", "==", "published")
        docs = query.stream()
        assets = [asset_view(doc.id, doc.to_dict()) for doc in docs]
        return sorted(assets, key=lambda item: str(item.get("updatedAt", "")), reverse=True)
    except Exception:
        return []


def get_asset_by_id(asset_id):
    if FIREBASE_DB is None:
        return None
    doc = FIREBASE_DB.collection("assets").document(asset_id).get()
    return asset_view(doc.id, doc.to_dict()) if doc.exists else None


def get_asset_by_slug(slug, include_private=False):
    if FIREBASE_DB is None:
        return None
    docs = list(FIREBASE_DB.collection("assets").where("slug", "==", slug).limit(1).stream())
    if not docs:
        return None
    result = asset_view(docs[0].id, docs[0].to_dict())
    if not include_private and result.get("status") != "published":
        return None
    return result


def storage_read(path):
    if FIREBASE_BUCKET is None:
        return None
    blob = FIREBASE_BUCKET.blob(path)
    if not blob.exists():
        return None
    return blob.download_as_bytes()


def storage_write(path, payload, content_type=None):
    if FIREBASE_BUCKET is None:
        return False
    blob = FIREBASE_BUCKET.blob(path)
    blob.upload_from_string(payload, content_type=content_type or "application/octet-stream")
    return True


def storage_delete(path):
    if FIREBASE_BUCKET is not None:
        blob = FIREBASE_BUCKET.blob(path)
        if blob.exists():
            blob.delete()


def content_type_for(filename):
    suffix = filename.rsplit(".", 1)[-1].lower()
    return {
        "html": "text/html; charset=utf-8",
        "htm": "text/html; charset=utf-8",
        "css": "text/css; charset=utf-8",
        "js": "text/javascript; charset=utf-8",
        "mjs": "text/javascript; charset=utf-8",
        "json": "application/json",
        "svg": "image/svg+xml",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
        "ico": "image/x-icon",
        "woff": "font/woff",
        "woff2": "font/woff2",
        "ttf": "font/ttf",
        "otf": "font/otf",
    }.get(suffix, "text/plain; charset=utf-8")


def uploaded_entries(files):
    entries = []
    for file in files:
        if not file or not file.filename:
            continue
        original = clean_asset_path(file.filename)
        if not original:
            continue
        if original.lower().endswith(".zip"):
            try:
                archive = zipfile.ZipFile(file.stream)
                for member in archive.infolist():
                    path = clean_asset_path(member.filename)
                    if not path or member.is_dir() or not allowed_file(path):
                        continue
                    entries.append((path, archive.read(member), content_type_for(path)))
            except zipfile.BadZipFile:
                continue
        elif allowed_file(original):
            entries.append((original, file.read(), content_type_for(original)))
    return entries


def make_preview_html(asset):
    main_file = asset.get("mainFile") or "index.html"
    body = storage_read(asset["filesByName"].get(main_file, "")) or b""
    html = body.decode("utf-8", errors="replace")
    base_url = url_for("asset_file", slug=asset["slug"], filename="")
    base_tag = f'<base href="{base_url}">'
    if re.search(r"<head(?:\s[^>]*)?>", html, flags=re.IGNORECASE):
        html = re.sub(r"(<head(?:\s[^>]*)?>)", r"\1" + base_tag, html, count=1, flags=re.IGNORECASE)
    else:
        html = base_tag + html
    return html


def ensure_firebase():
    if FIREBASE_DB is None or FIREBASE_BUCKET is None:
        flash("Firebase is not ready. Check FIREBASE_SERVICE_ACCOUNT_JSON, Firestore and Storage.", "error")
        return False
    return True


@app.context_processor
def global_template_data():
    profile = {}
    if FIREBASE_DB is not None:
        try:
            snapshot = FIREBASE_DB.collection("settings").document("profile").get()
            if snapshot.exists:
                profile = snapshot.to_dict()
        except Exception:
            profile = {}
    return {
        "profile": profile,
        "firebase_ready": FIREBASE_DB is not None and FIREBASE_BUCKET is not None,
        "firebase_error": FIREBASE_ERROR,
    }


@app.get("/")
def home():
    return render_template("home.html", assets=list_assets()[:6])


@app.get("/admin/login")
def admin_login():
    if session.get("admin_authenticated"):
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.post("/admin/login")
def admin_login_submit():
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    expected_email = os.environ.get("ADMIN_EMAIL", "")
    expected_password = os.environ.get("ADMIN_PASSWORD", "")
    if (
        expected_email
        and expected_password
        and hmac.compare_digest(email, expected_email)
        and hmac.compare_digest(password, expected_password)
    ):
        session.clear()
        session["admin_authenticated"] = True
        session["admin_email"] = email
        session.permanent = True
        return redirect(request.args.get("next") or url_for("dashboard"))
    flash("Email ya password sahi nahi hai.", "error")
    return render_template("login.html", email=email), 401


@app.post("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.get("/admin/dashboard")
@admin_required
def dashboard():
    assets = list_assets(include_private=True)
    stats = {
        "total": len(assets),
        "published": sum(item.get("status") == "published" for item in assets),
        "drafts": sum(item.get("status") == "draft" for item in assets),
        "files": sum(item.get("file_count", 0) for item in assets),
    }
    query = request.args.get("q", "").strip().lower()
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "").strip()
    if query:
        assets = [
            item
            for item in assets
            if query in item.get("title", "").lower()
            or query in item.get("slug", "").lower()
            or query in item.get("description", "").lower()
        ]
    if category:
        assets = [item for item in assets if item.get("category") == category]
    if status:
        assets = [item for item in assets if item.get("status") == status]
    categories = sorted(set(DEFAULT_CATEGORIES + [item.get("category", "Other") for item in list_assets(True)]))
    return render_template("dashboard.html", assets=assets, stats=stats, categories=categories)


@app.route("/admin/assets/new", methods=["GET", "POST"])
@admin_required
def new_asset():
    if request.method == "GET":
        return render_template("upload.html", categories=DEFAULT_CATEGORIES)
    if not ensure_firebase():
        return redirect(url_for("new_asset"))
    title = request.form.get("title", "").strip() or "Untitled asset"
    category = request.form.get("category", "Other").strip() or "Other"
    description = request.form.get("description", "").strip()
    html_content = request.form.get("html_content", "")
    status = "published" if request.form.get("publish") == "on" else "draft"
    entries = uploaded_entries(request.files.getlist("files"))
    if html_content.strip():
        entries = [("index.html", html_content.encode("utf-8"), "text/html; charset=utf-8")] + [
            entry for entry in entries if entry[0] != "index.html"
        ]
    if not entries:
        flash("Ek HTML file, code ya asset package add karein.", "error")
        return render_template("upload.html", categories=DEFAULT_CATEGORIES), 400
    asset_id = secrets.token_urlsafe(9).replace("-", "").replace("_", "")
    slug = unique_slug(title)
    files = []
    files_by_name = {}
    for name, payload, mime in entries:
        path = f"assets/{asset_id}/{name}"
        storage_write(path, payload, mime)
        files.append({"name": name, "storagePath": path, "contentType": mime, "size": len(payload)})
        files_by_name[name] = path
    main_file = next((item["name"] for item in files if item["name"].lower().endswith((".html", ".htm"))), files[0]["name"])
    FIREBASE_DB.collection("assets").document(asset_id).set(
        {
            "title": title,
            "slug": slug,
            "category": category,
            "description": description,
            "status": status,
            "mainFile": main_file,
            "files": files,
            "createdAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "views": 0,
            "embedCopies": 0,
        }
    )
    flash("Asset save ho gaya.", "success")
    return redirect(url_for("asset_detail", slug=slug))


@app.route("/admin/assets/<asset_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_asset(asset_id):
    asset = get_asset_by_id(asset_id)
    if not asset:
        abort(404)
    asset["filesByName"] = {item["name"]: item["storagePath"] for item in asset.get("files", [])}
    if request.method == "GET":
        current_html = storage_read(asset["filesByName"].get(asset.get("mainFile", ""), ""))
        asset["html_content"] = (current_html or b"").decode("utf-8", errors="replace")
        return render_template("upload.html", asset=asset, categories=DEFAULT_CATEGORIES)
    if not ensure_firebase():
        return redirect(url_for("edit_asset", asset_id=asset_id))
    title = request.form.get("title", "").strip() or asset["title"]
    category = request.form.get("category", "Other").strip() or "Other"
    description = request.form.get("description", "").strip()
    html_content = request.form.get("html_content", "")
    status = "published" if request.form.get("publish") == "on" else "draft"
    update = {
        "title": title,
        "slug": unique_slug(title, current_id=asset_id),
        "category": category,
        "description": description,
        "status": status,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }
    if html_content.strip() and asset.get("mainFile"):
        storage_write(asset["filesByName"][asset["mainFile"]], html_content.encode("utf-8"), "text/html; charset=utf-8")
    FIREBASE_DB.collection("assets").document(asset_id).update(update)
    flash("Asset update ho gaya.", "success")
    return redirect(url_for("asset_detail", slug=update["slug"]))


@app.post("/admin/assets/<asset_id>/toggle")
@admin_required
def toggle_asset(asset_id):
    asset = get_asset_by_id(asset_id)
    if not asset or not ensure_firebase():
        abort(404)
    new_status = "draft" if asset.get("status") == "published" else "published"
    FIREBASE_DB.collection("assets").document(asset_id).update(
        {"status": new_status, "updatedAt": firestore.SERVER_TIMESTAMP}
    )
    flash("Asset " + ("publish ho gaya." if new_status == "published" else "unpublish ho gaya."), "success")
    return redirect(request.referrer or url_for("dashboard"))


@app.post("/admin/assets/<asset_id>/delete")
@admin_required
def delete_asset(asset_id):
    asset = get_asset_by_id(asset_id)
    if not asset or not ensure_firebase():
        abort(404)
    for item in asset.get("files", []):
        storage_delete(item.get("storagePath", ""))
    FIREBASE_DB.collection("assets").document(asset_id).delete()
    flash("Asset delete ho gaya.", "success")
    return redirect(url_for("dashboard"))


@app.get("/assets/<slug>")
def asset_detail(slug):
    asset = get_asset_by_slug(slug, include_private=bool(session.get("admin_authenticated")))
    if not asset:
        return render_template("error.html", code="Unavailable", message="Ye asset published nahi hai ya available nahi hai."), 404
    if FIREBASE_DB is not None:
        try:
            FIREBASE_DB.collection("assets").document(asset["id"]).update({"views": firestore.Increment(1)})
        except Exception:
            pass
    asset["filesByName"] = {item["name"]: item["storagePath"] for item in asset.get("files", [])}
    return render_template("asset_detail.html", asset=asset, preview_html=make_preview_html(asset))


@app.get("/embed/<slug>")
def embed_asset(slug):
    asset = get_asset_by_slug(slug)
    if not asset:
        return render_template("error.html", code="Unavailable", message="Ye embed unavailable hai."), 404
    asset["filesByName"] = {item["name"]: item["storagePath"] for item in asset.get("files", [])}
    return make_preview_html(asset)


@app.get("/asset-file/<slug>/<path:filename>")
def asset_file(slug, filename):
    asset = get_asset_by_slug(slug, include_private=bool(session.get("admin_authenticated")))
    if not asset:
        abort(404)
    requested = clean_asset_path(filename)
    item = next((item for item in asset.get("files", []) if item.get("name") == requested), None)
    if not item:
        abort(404)
    payload = storage_read(item.get("storagePath", ""))
    if payload is None:
        abort(404)
    return send_file(io.BytesIO(payload), mimetype=item.get("contentType"), download_name=requested)


@app.route("/admin/profile", methods=["GET", "POST"])
@admin_required
def profile():
    if FIREBASE_DB is None:
        profile_data = {}
    else:
        profile_snapshot = FIREBASE_DB.collection("settings").document("profile").get()
        profile_data = profile_snapshot.to_dict() if profile_snapshot.exists else {}
    if request.method == "POST":
        if not ensure_firebase():
            return redirect(url_for("profile"))
        data = {
            "name": request.form.get("name", "Majid").strip() or "Majid",
            "bio": request.form.get("bio", "").strip(),
            "htmlBio": request.form.get("htmlBio", "").strip(),
            "website": request.form.get("website", "").strip(),
            "public": request.form.get("public") == "on",
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
        image = request.files.get("profile_image")
        if image and image.filename:
            api_key = os.environ.get("IMGBB_API_KEY", "")
            if api_key:
                response = requests.post(
                    "https://api.imgbb.com/1/upload",
                    params={"key": api_key},
                    files={"image": (secure_filename(image.filename), image.read(), image.mimetype)},
                    timeout=25,
                )
                if response.ok and response.json().get("success"):
                    data["imageUrl"] = response.json()["data"]["url"]
                else:
                    flash("Profile image upload nahi ho paya.", "error")
        FIREBASE_DB.collection("settings").document("profile").set(data, merge=True)
        flash("Profile save ho gayi.", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", profile_data=profile_data)


@app.get("/profile")
def public_profile():
    profile_snapshot = (
        FIREBASE_DB.collection("settings").document("profile").get()
        if FIREBASE_DB is not None
        else None
    )
    public_data = profile_snapshot.to_dict() if profile_snapshot and profile_snapshot.exists else {}
    if not public_data.get("public"):
        return render_template("error.html", code="Private", message="Profile public nahi hai."), 404
    return render_template("profile.html", profile_data=public_data, public_view=True)


@app.errorhandler(413)
def too_large(_error):
    return render_template("error.html", code="File too large", message="Upload size 60 MB se zyada nahi ho sakta."), 413


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code="Not found", message="Ye page ya asset available nahi hai."), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)