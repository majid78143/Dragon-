# Dragon Vault — Firebase Realtime Database

## Included

- `main.py` — Flask application and RTDB REST data access
- `templates/` — the existing Dragon Vault pages and layout
- `static/` — CSS, JavaScript, Firebase web configuration, and SVG assets
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

Set these values in the hosting provider's environment settings:

```text
ADMIN_EMAIL
ADMIN_PASSWORD
FIREBASE_DATABASE_URL
FLASK_SECRET_KEY
```

This version uses Firebase Realtime Database only. It needs no server-side
credential file and no local upload directory.

Create/enable a Firebase Realtime Database and set its rules for the access model
you want to use. The server talks to the database through its REST API using the
configured `FIREBASE_DATABASE_URL`.

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

## Main routes

```text
/                       Public home
/admin/login            Admin login
/admin/dashboard        Admin vault
/admin/assets/new       Create an asset
/admin/profile          Edit profile
/profile                Public profile
/assets/<slug>          Public asset page
/embed/<slug>           Embeddable asset
```

## RTDB-only asset model

Assets are stored at `assets/<asset-id>` in Firebase Realtime Database. Each
asset keeps its source files as text:

```json
{
  "mainFile": "index.html",
  "files": [
    {
      "name": "index.html",
      "content": "<!doctype html>...",
      "contentType": "text/html; charset=utf-8",
      "size": 1234
    }
  ]
}
```

When a text file is selected, the browser uses `FileReader` to load its actual
UTF-8 text into the code editor. HTML, CSS, JavaScript, JSON, SVG, and TXT are
supported. Images, fonts, and other binary files are rejected with an
unsupported-file message and are never uploaded or converted.

ZIP packages can still be selected for compatibility. They are read in memory
only; only UTF-8 text files with supported extensions are kept, and binary
members are skipped. No uploaded file is saved on the server or local disk.

The list, edit, delete, public preview, embed preview, and HTML asset preview
all read the stored RTDB `files[].content`. HTML previews use the stored
`mainFile` content directly and resolve other supported text files through
`/asset-file/<slug>/<filename>`.

## Security notes

- Never commit `.env`.
- Use restrictive Firebase Realtime Database rules for your deployment.
- Use a long random `FLASK_SECRET_KEY`.
- Restrict your hosting provider's file and environment-variable access.