# PDF Tools compression service

The Campus Hub Android app cannot do real PDF compression on its own. `pdf-lib` can rewrite a PDF's
structure, but it cannot re-encode embedded images, and images are where nearly all of a photo-heavy PDF's
size comes from. This small Flask service does what iLovePDF's server does: it downsamples and re-encodes
the images, then returns the smaller PDF.

It is deliberately one endpoint. The other PDF Tools (merge, split, organize, watermark, page numbers,
PDF to Word, image conversion) still run offline on the phone.

## What it uses

| Engine | Used for | Requirement |
| --- | --- | --- |
| PyMuPDF | `Document.rewrite_images()` (downsample + JPEG re-encode), `subset_fonts()`, `garbage=4` clean-up, page counts and output verification | `pip install -r requirements.txt` |
| Ghostscript | `/prepress`, `/ebook`, `/screen` presets, used instead of PyMuPDF when installed | Optional: `gswin64c`/`gs` on `PATH`, or `PDFTOOLS_GS_BINARY` |

The service runs both eligible engines, verifies every candidate (PDF signature, page count), and returns
the smallest valid file. If the original is already the smallest, it returns the original bytes unchanged
and sets `X-Reduced: false`. **Compression never makes the file bigger.**

Presets:

| Preset | Ghostscript | PyMuPDF (approx.) |
| --- | --- | --- |
| `low` | `/prepress` (300 dpi) | images above 300 dpi -> 220 dpi, JPEG q85 |
| `medium` | `/ebook` (150 dpi) | images above 200 dpi -> 150 dpi, JPEG q72 |
| `high` | `/screen` (72 dpi) | images above 150 dpi -> 96 dpi, JPEG q55 |

Text stays selectable; page order, sizes and rotations are preserved.

## Run it

From this folder (`backend/pdftools`):

```powershell
python -m pip install -r requirements.txt
python app.py
```

The API is then on `http://localhost:5000`. Check it:

```powershell
Invoke-RestMethod http://localhost:5000/api/health
```

### Make it reachable from a phone (no account, no signup)

A phone cannot reach your PC's `localhost`. The easiest fix is a free Cloudflare quick tunnel, which gives a
public HTTPS address in a few seconds:

```powershell
powershell -ExecutionPolicy Bypass -File .\run-with-tunnel.ps1
```

It starts the service, opens the tunnel and prints something like
`https://continuously-coast-finds-wifi.trycloudflare.com`. Paste that into the app:
**PDF Tools -> Compress PDF -> Compression server -> Change -> Save**.

That address changes every time the script restarts, which is why the app stores the address instead of
hardcoding it — no APK rebuild is ever needed. HTTPS also means no `network_security_config.xml` change.

A production-style server (waitress is in `requirements.txt`):

```powershell
python -c "from waitress import serve; from app import app; serve(app, host='0.0.0.0', port=5000)"
```

For a permanent URL, deploy this folder to Render/Railway/Fly and paste that HTTPS address into the app the
same way.

Run the tests:

```powershell
python -m pytest -q
```

### Environment variables

| Name | Default | Meaning |
| --- | --- | --- |
| `PORT` | `5000` | Port for `python app.py` |
| `PDFTOOLS_MAX_UPLOAD_BYTES` | `31457280` (30 MB) | Upload cap, matching the app's picker limit |
| `PDFTOOLS_MAX_PAGES` | `3000` | Reject larger documents before spending time on them |
| `PDFTOOLS_TIMEOUT_SECONDS` | `180` | Ghostscript subprocess timeout |
| `PDFTOOLS_GS_BINARY` | auto-detect | Path to `gswin64c.exe` / `gs` |
| `PDFTOOLS_ALLOWED_ORIGINS` | local dev origins | Comma-separated browser origins allowed by CORS (native clients do not need this) |

## API

### `GET /api/health`

```json
{
  "status": "ok",
  "service": "campushub-pdftools",
  "version": "1.0.0",
  "engine": "pymupdf",
  "engines": {"ghostscript": false, "pymupdf": true},
  "maxUploadBytes": 31457280,
  "maxPages": 3000,
  "presets": ["low", "medium", "high"]
}
```

### `POST /api/pdf/compress`

`multipart/form-data`:

- `file` - the PDF (required)
- `preset` - `low`, `medium` (default) or `high`

Success: the compressed PDF with `Content-Type: application/pdf` and these headers:

| Header | Example |
| --- | --- |
| `X-Original-Bytes` | `2456789` |
| `X-Output-Bytes` | `734512` |
| `X-Saved-Bytes` | `1722277` |
| `X-Reduction-Percent` | `70.11` |
| `X-Pages` | `12` |
| `X-Engine` | `pymupdf`, `ghostscript` or `original` |
| `X-Reduced` | `true` / `false` |

Errors are JSON:

```json
{"error": {"code": "invalid_pdf", "message": "This file is not a valid PDF, or it is damaged."}}
```

| Status | Codes |
| --- | --- |
| 400 | `missing_file`, `empty_file`, `invalid_preset` |
| 413 | `file_too_large`, `too_many_pages` |
| 415 | `not_a_pdf` |
| 422 | `invalid_pdf`, `encrypted_pdf`, `empty_pdf`, `processing_failed` |
| 500 | `server_error` |

## Safety

- Every upload is written to a fresh `tempfile.mkdtemp(prefix='pdftools-')` and the whole directory is
  deleted in `finally`, so a request never leaves a document behind.
- File type is checked from the bytes (`%PDF-`), not the client's file name.
- Output names are generated from a sanitised stem; the client cannot choose a path.
- Ghostscript runs with `-dSAFER`.
- Download responses are `Cache-Control: no-store`.
- Nothing is logged except unexpected server exceptions (no document contents).

This is not a claim of complete security. Put it behind HTTPS and a reverse proxy with its own request
limits before exposing it publicly.

## Connecting the Android app

The client is `src/modules/pdftools/lib/backend.ts`; the address is in
`src/modules/pdftools/config.ts` and, more importantly, editable in the app.

| Situation | Address | How |
| --- | --- | --- |
| Any phone, anywhere (recommended) | a `https://*.trycloudflare.com` or deployed HTTPS address | run `run-with-tunnel.ps1` on the PC, then paste the printed address in **Compress PDF -> Compression server -> Change** |
| Debug build on the Android emulator | `http://10.0.2.2:5000` | the emulator's alias for the PC; this is the built-in debug default |
| Release APK on a USB-connected phone | `http://localhost:5000` | run `adb reverse tcp:5000 tcp:5000`, then set that address in the app |

The address is saved under the `pdftools.serverUrl` AsyncStorage key and can be reset to the built-in default
from the same screen. `Test` on that screen calls `/api/health` and reports the engine and limits.

The cleartext allowlist in `android/app/src/main/res/xml/network_security_config.xml` contains `localhost`
and `10.0.2.2` only. A LAN IP will be blocked, so use HTTPS (the tunnel) or `adb reverse`. HTTPS needs no
allowlist entry at all.

The server must be running before the Compress PDF tool is used. If it is unreachable, the app shows the
address it tried and a short hint, never a fake "compressed" result.

## Limits

- Compression is only as good as the source. A PDF whose images are already small and low quality will barely
  change; the app reports that honestly and keeps the original.
- Password-protected PDFs are refused (the user must remove the password first).
- The service is synchronous per request. Ghostscript and PyMuPDF both use CPU; for many users, run several
  workers behind a queue.
