import hmac
import json
import os
import posixpath
import re
import secrets
import time
import zipfile
from datetime import datetime, timezone
from functools import wraps
from pathlib import PurePosixPath

import requests
from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.utils import secure_filename


app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dragon-vault-local-key")
app.config["MAX_CONTENT_LENGTH"] = 60 * 1024 * 1024

TEXT_EXTENSIONS = {"html", "htm", "css", "js", "mjs", "json", "svg", "txt"}
DEFAULT_CATEGORIES = ["Landing Pages", "Templates", "Components", "Websites", "Experiments", "Other"]
FIREBASE_DATABASE_URL = os.environ.get(
    "FIREBASE_DATABASE_URL",
    "https://connecto-5814d-default-rtdb.firebaseio.com",
).rstrip("/")
FIREBASE_ERROR = None


def rtdb_request(method, path="", payload=None):
    """Use the Firebase Realtime Database REST API."""
    url = f"{FIREBASE_DATABASE_URL}/{path.strip('/')}.json" if path else f"{FIREBASE_DATABASE_URL}/.json"
    kwargs = {"timeout": 20}
    if payload is not None:
        kwargs["json"] = payload
    response = requests.request(method, url, **kwargs)
    if not response.ok:
        raise RuntimeError(f"Realtime Database request failed ({response.status_code})")
    if not response.content:
        return None
    return response.json()


def rtdb_get(path=""):
    return rtdb_request("GET", path)


def rtdb_put(path, payload):
    return rtdb_request("PUT", path, payload)


def rtdb_patch(path, payload):
    return rtdb_request("PATCH", path, payload)


def rtdb_delete(path):
    return rtdb_request("DELETE", path)


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
    return "/".join(pieces) if pieces else None


def allowed_file(filename):
    path = clean_asset_path(filename)
    return bool(path and "." in path and path.rsplit(".", 1)[1].lower() in TEXT_EXTENSIONS)


def safe_slug(value):
    value = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return value[:70] or f"asset-{secrets.token_hex(4)}"


def unique_slug(title, current_id=None):
    base = safe_slug(title)
    assets = list_assets(include_private=True)
    used = {item.get("slug") for item in assets if item.get("id") != current_id}
    candidate = base
    counter = 2
    while candidate in used:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def timestamp_value(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%b %d, %Y")
    return str(value or "Just now")


def asset_view(asset_id, data):
    result = dict(data or {})
    result["id"] = asset_id
    result["created_label"] = timestamp_value(result.get("createdAt"))
    result["updated_label"] = timestamp_value(result.get("updatedAt"))
    result["file_count"] = len(result.get("files") or [])
    return result


def list_assets(include_private=False):
    try:
        raw_assets = rtdb_get("assets") or {}
        if not isinstance(raw_assets, dict):
            return []
        assets = [
            asset_view(asset_id, data)
            for asset_id, data in raw_assets.items()
            if isinstance(data, dict)
            and (include_private or data.get("status") == "published")
        ]
        return sorted(assets, key=lambda item: item.get("updatedAt", 0), reverse=True)
    except Exception:
        return []


def get_asset_by_id(asset_id):
    try:
        data = rtdb_get(f"assets/{asset_id}")
        return asset_view(asset_id, data) if isinstance(data, dict) else None
    except Exception:
        return None


def get_asset_by_slug(slug, include_private=False):
    for asset in list_assets(include_private=True):
        if asset.get("slug") == slug and (include_private or asset.get("status") == "published"):
            return asset
    return None


def content_type_for(filename):
    suffix = filename.rsplit(".", 1)[-1].lower()
    return {
        "html": "text/html; charset=utf-8",
        "htm": "text/html; charset=utf-8",
        "css": "text/css; charset=utf-8",
        "js": "text/javascript; charset=utf-8",
        "mjs": "text/javascript; charset=utf-8",
        "json": "application/json; charset=utf-8",
        "svg": "image/svg+xml; charset=utf-8",
        "txt": "text/plain; charset=utf-8",
    }.get(suffix, "text/plain; charset=utf-8")


def text_entry(name, content):
    cleaned_name = clean_asset_path(name)
    if not cleaned_name or not allowed_file(cleaned_name) or not isinstance(content, str):
        return None
    return {
        "name": cleaned_name,
        "content": content,
        "contentType": content_type_for(cleaned_name),
        "size": len(content.encode("utf-8")),
    }


def uploaded_entries(files):
    entries = []
    rejected = []
    for file in files:
        if not file or not file.filename:
            continue
        original = clean_asset_path(file.filename)
        if not original:
            continue
        if original.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(file.stream) as archive:
                    for member in archive.infolist():
                        path = clean_asset_path(member.filename)
                        if not path or member.is_dir():
                            continue
                        if not allowed_file(path):
                            rejected.append(path)
                            continue
                        raw = archive.read(member)
                        if b"\x00" in raw:
                            rejected.append(path)
                            continue
                        entry = text_entry(path, raw.decode("utf-8", errors="replace"))
                        if entry:
                            entries.append(entry)
            except zipfile.BadZipFile:
                rejected.append(original)
        elif not allowed_file(original):
            rejected.append(original)
        else:
            raw = file.read()
            if b"\x00" in raw:
                rejected.append(original)
                continue
            entry = text_entry(original, raw.decode("utf-8", errors="replace"))
            if entry:
                entries.append(entry)
    return entries, rejected


def browser_entries():
    raw_manifest = request.form.get("text_files_json", "")
    if not raw_manifest:
        return [], []
    try:
        manifest = json.loads(raw_manifest)
    except (TypeError, ValueError):
        return [], ["selected files"]
    entries = []
    rejected = []
    for item in manifest if isinstance(manifest, list) else []:
        if not isinstance(item, dict):
            continue
        entry = text_entry(item.get("name", ""), item.get("content"))
        if entry:
            entries.append(entry)
        elif item.get("name"):
            rejected.append(str(item["name"]))
    return entries, rejected


def merge_files(existing, incoming):
    by_name = {item.get("name"): dict(item) for item in existing or [] if item.get("name")}
    for entry in incoming:
        by_name[entry["name"]] = entry
    return list(by_name.values())


def make_preview_html(asset):
    files = {item.get("name"): item for item in asset.get("files", [])}
    main_file = asset.get("mainFile") or "index.html"
    html = str((files.get(main_file) or {}).get("content") or "")
    base_url = url_for("asset_file", slug=asset["slug"], filename="")
    base_tag = f'<base href="{base_url}">'
    if re.search(r"<head(?:\s[^>]*)?>", html, flags=re.IGNORECASE):
        html = re.sub(
            r"(<head(?:\s[^>]*)?>)",
            r"\1" + base_tag,
            html,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        html = base_tag + html
    return html


def ensure_firebase():
    if not FIREBASE_DATABASE_URL:
        flash("Firebase Realtime Database URL configured nahi hai.", "error")
        return False
    return True


def readable_firebase_error(error):
    message = str(error).lower()
    if "permission" in message or "403" in message or "forbidden" in message:
        return "Firebase Realtime Database permission denied. RTDB rules aur database URL check karein."
    if "database" in message or "404" in message:
        return "Firebase Realtime Database save fail hua. RTDB enable karke database URL check karein."
    return "Asset save nahi ho paya. Firebase Realtime Database connection check karein."


@app.context_processor
def global_template_data():
    profile = {}
    try:
        stored_profile = rtdb_get("settings/profile")
        if isinstance(stored_profile, dict):
            profile = stored_profile
    except Exception:
        pass
    return {
        "profile": profile,
        "firebase_ready": bool(FIREBASE_DATABASE_URL),
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
    entries, rejected = browser_entries()
    uploaded, rejected_from_upload = uploaded_entries(request.files.getlist("files"))
    entries = merge_files(entries, uploaded)
    rejected.extend(rejected_from_upload)
    if html_content.strip():
        html_entry = text_entry("index.html", html_content)
        entries = [html_entry] + [entry for entry in entries if entry["name"] != "index.html"] if html_entry else entries
    if rejected:
        flash("Unsupported/non-text files skipped: " + ", ".join(rejected[:5]), "error")
    if not entries:
        flash("Ek HTML, CSS, JS, JSON, SVG ya TXT file add karein.", "error")
        return render_template("upload.html", categories=DEFAULT_CATEGORIES), 400
    asset_id = secrets.token_urlsafe(9).replace("-", "").replace("_", "")
    main_file = next(
        (item["name"] for item in entries if item["name"].lower().endswith((".html", ".htm"))),
        entries[0]["name"],
    )
    now = int(time.time() * 1000)
    payload = {
        "title": title,
        "slug": unique_slug(title),
        "category": category,
        "description": description,
        "status": status,
        "mainFile": main_file,
        "files": entries,
        "createdAt": now,
        "updatedAt": now,
        "views": 0,
        "embedCopies": 0,
    }
    try:
        rtdb_put(f"assets/{asset_id}", payload)
    except Exception as error:
        app.logger.exception("Asset creation failed")
        flash(readable_firebase_error(error), "error")
        return render_template("upload.html", categories=DEFAULT_CATEGORIES), 502
    flash("Asset save ho gaya.", "success")
    return redirect(url_for("asset_detail", slug=payload["slug"]))


@app.get("/admin/as")
@admin_required
def admin_as_alias():
    return redirect(url_for("new_asset"))


@app.route("/admin/assets/<asset_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_asset(asset_id):
    asset = get_asset_by_id(asset_id)
    if not asset:
        abort(404)
    if request.method == "GET":
        main_file = next(
            (item for item in asset.get("files", []) if item.get("name") == asset.get("mainFile")),
            {},
        )
        asset["html_content"] = main_file.get("content", "")
        return render_template("upload.html", asset=asset, categories=DEFAULT_CATEGORIES)
    if not ensure_firebase():
        return redirect(url_for("edit_asset", asset_id=asset_id))
    title = request.form.get("title", "").strip() or asset["title"]
    category = request.form.get("category", "Other").strip() or "Other"
    description = request.form.get("description", "").strip()
    html_content = request.form.get("html_content", "")
    status = "published" if request.form.get("publish") == "on" else "draft"
    entries, rejected = browser_entries()
    uploaded, rejected_from_upload = uploaded_entries(request.files.getlist("files"))
    entries = merge_files(entries, uploaded)
    rejected.extend(rejected_from_upload)
    files = merge_files(asset.get("files", []), entries)
    if html_content.strip() and asset.get("mainFile"):
        html_entry = text_entry(asset["mainFile"], html_content)
        if html_entry:
            files = merge_files(files, [html_entry])
    if rejected:
        flash("Unsupported/non-text files skipped: " + ", ".join(rejected[:5]), "error")
    if not files:
        flash("Asset mein kam se kam ek text file honi chahiye.", "error")
        return render_template("upload.html", asset=asset, categories=DEFAULT_CATEGORIES), 400
    update = {
        "title": title,
        "slug": unique_slug(title, current_id=asset_id),
        "category": category,
        "description": description,
        "status": status,
        "files": files,
        "mainFile": next(
            (item["name"] for item in files if item["name"].lower().endswith((".html", ".htm"))),
            files[0]["name"],
        ),
        "updatedAt": int(time.time() * 1000),
    }
    try:
        rtdb_patch(f"assets/{asset_id}", update)
    except Exception as error:
        flash(readable_firebase_error(error), "error")
        return render_template("upload.html", asset=asset, categories=DEFAULT_CATEGORIES), 502
    flash("Asset update ho gaya.", "success")
    return redirect(url_for("asset_detail", slug=update["slug"]))


@app.post("/admin/assets/<asset_id>/toggle")
@admin_required
def toggle_asset(asset_id):
    asset = get_asset_by_id(asset_id)
    if not asset or not ensure_firebase():
        abort(404)
    new_status = "draft" if asset.get("status") == "published" else "published"
    rtdb_patch(f"assets/{asset_id}", {"status": new_status, "updatedAt": int(time.time() * 1000)})
    flash("Asset " + ("publish ho gaya." if new_status == "published" else "unpublish ho gaya."), "success")
    return redirect(request.referrer or url_for("dashboard"))


@app.post("/admin/assets/<asset_id>/delete")
@admin_required
def delete_asset(asset_id):
    if not get_asset_by_id(asset_id) or not ensure_firebase():
        abort(404)
    try:
        rtdb_delete(f"assets/{asset_id}")
    except Exception as error:
        flash(readable_firebase_error(error), "error")
        return redirect(url_for("dashboard"))
    flash("Asset delete ho gaya.", "success")
    return redirect(url_for("dashboard"))


@app.get("/assets/<slug>")
def asset_detail(slug):
    asset = get_asset_by_slug(slug, include_private=bool(session.get("admin_authenticated")))
    if not asset:
        return render_template("error.html", code="Unavailable", message="Ye asset published nahi hai ya available nahi hai."), 404
    try:
        rtdb_patch(f"assets/{asset['id']}", {"views": int(asset.get("views", 0)) + 1})
    except Exception:
        pass
    return render_template("asset_detail.html", asset=asset, preview_html=make_preview_html(asset))


@app.get("/embed/<slug>")
def embed_asset(slug):
    asset = get_asset_by_slug(slug)
    if not asset:
        return render_template("error.html", code="Unavailable", message="Ye embed unavailable hai."), 404
    return make_preview_html(asset)


@app.get("/asset-file/<slug>/<path:filename>")
def asset_file(slug, filename):
    asset = get_asset_by_slug(slug, include_private=bool(session.get("admin_authenticated")))
    if not asset:
        abort(404)
    requested = clean_asset_path(filename)
    item = next((item for item in asset.get("files", []) if item.get("name") == requested), None)
    if not item or not isinstance(item.get("content"), str):
        abort(404)
    return Response(item["content"], mimetype=item.get("contentType", "text/plain"))


@app.route("/admin/profile", methods=["GET", "POST"])
@admin_required
def profile():
    try:
        profile_data = rtdb_get("settings/profile") or {}
    except Exception:
        profile_data = {}
    if request.method == "POST":
        if not ensure_firebase():
            return redirect(url_for("profile"))
        image = request.files.get("profile_image")
        if image and image.filename:
            flash("Binary image upload unsupported hai. Sirf text/code files save hoti hain.", "error")
        data = {
            "name": request.form.get("name", "Majid").strip() or "Majid",
            "bio": request.form.get("bio", "").strip(),
            "htmlBio": request.form.get("htmlBio", "").strip(),
            "website": request.form.get("website", "").strip(),
            "public": request.form.get("public") == "on",
            "updatedAt": int(time.time() * 1000),
        }
        try:
            rtdb_patch("settings/profile", data)
        except Exception as error:
            flash(readable_firebase_error(error), "error")
            return redirect(url_for("profile"))
        flash("Profile save ho gayi.", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", profile_data=profile_data)


@app.get("/profile")
def public_profile():
    try:
        public_data = rtdb_get("settings/profile") or {}
    except Exception:
        public_data = {}
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