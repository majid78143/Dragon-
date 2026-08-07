# Dragon Vault — Self-hosting

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

Set these values in your hosting provider's secret/environment settings:

```text
ADMIN_EMAIL
ADMIN_PASSWORD
FIREBASE_SERVICE_ACCOUNT_JSON
IMGBB_API_KEY
FLASK_SECRET_KEY
```

`FIREBASE_SERVICE_ACCOUNT_JSON` must contain the complete Firebase service-account JSON as one value. Do not put it in `static/`, `templates/`, or a public repository.

The Firebase web configuration is already in `static/firebase.js`, as requested. Enable these Firebase services:

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

## Firebase Storage and upload notes

- HTML, CSS, JavaScript, images, fonts, and ZIP packages are supported.
- The maximum upload size is 60 MB.
- Uploaded files are stored in Firebase Storage, not in the `static/` folder.
- Public assets are available only after publishing.
- Draft/unpublished assets are visible to the authenticated admin only.

## Security notes

- Never commit `.env` or the Firebase service-account JSON.
- Keep Firestore and Storage rules restricted to the app's intended access model.
- Use a long random `FLASK_SECRET_KEY`.
- Restrict your hosting provider's file and environment-variable access.