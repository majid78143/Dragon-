# Dragon Vault — Self-hosting

Dragon Vault can run without Firebase or any paid storage. By default it uses
local storage under `data/` for uploaded files and asset metadata. Firebase is
optional: if `FIREBASE_SERVICE_ACCOUNT_JSON` is configured, the original
Firestore + Firebase Storage mode is used automatically.

## Included

- `main.py` — Flask application
- `templates/` — all HTML pages
- `static/` — CSS, JavaScript, Firebase web config, and SVG assets
- `requirements.txt` — Python dependencies
- `.env.example` — required environment variable names

## 1. Install

Use Python 3.11 or newer:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Configure environment variables

Copy the example file:

```bash
cp .env.example .env
```

Set these values in your environment settings:

```text
ADMIN_EMAIL
ADMIN_PASSWORD
IMGBB_API_KEY
FLASK_SECRET_KEY
```

For free local mode, only `ADMIN_EMAIL` and `ADMIN_PASSWORD` are needed.
`FLASK_SECRET_KEY` is optional; the app also uses `SESSION_SECRET` when
available. `FIREBASE_SERVICE_ACCOUNT_JSON` is optional.
Never put a Firebase service-account JSON in `static/`, `templates/`, or a
public repository.

If Firebase is configured, enable these Firebase services:

- Firestore Database
- Firebase Storage

The current login uses the fixed `ADMIN_EMAIL` and `ADMIN_PASSWORD` values. Firebase service-account access is used by Flask for Firestore and Storage.

## 3. Run locally

```bash
export $(grep -v '^#' .env | xargs)
python3 main.py
```

Open `http://localhost:5000`.

## 4. Run in production

Set the hosting provider's port variable and use Gunicorn:

```bash
gunicorn --bind 0.0.0.0:${PORT:-5000} main:app
```

For a reverse proxy, forward the public domain to the Gunicorn port.

## Main routes

```text
/                       Public home
/admin/login            Admin login
/admin/dashboard        Admin vault
/admin/assets/new       Upload an asset
/admin/profile          Edit profile
/profile                Public profile
/assets/<slug>          Public asset page
/embed/<slug>           Embeddable asset
```

## Storage and upload notes

- HTML, CSS, JavaScript, images, fonts, and ZIP packages are supported.
- The maximum upload size is 60 MB.
- In free local mode, uploaded files are stored in `data/storage/` and metadata
  is stored in `data/metadata.json`, not in the `static/` folder.
- Set `DRAGON_DATA_DIR` if you want to keep the data in another directory.
- Public assets are available only after publishing.
- Draft/unpublished assets are visible to the authenticated admin only.
- Keep a backup of `data/` when using temporary hosting; local disks can be
  reset when a workspace or deployment is rebuilt.

## Security notes

- Never commit `.env` or the Firebase service-account JSON.
- Keep Firestore and Storage rules restricted to the app's intended access model.
- Use a long random `FLASK_SECRET_KEY`.
- Restrict your hosting provider's file and environment-variable access.
