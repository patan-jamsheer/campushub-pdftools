# Deploying the compression server (free, ~3 minutes)

The Android app needs a public **HTTPS** address. This folder is a complete, self-contained Docker service, so
the host builds it for you — no Python setup on the server, no build commands to type.

Everything here is already in the repository, so deploying is: open Render, paste the repo URL, click Create.

## Render (free tier, no credit card)

1. Sign in at <https://render.com> with GitHub (free, no card needed for the free instance type).
2. **New +** → **Web Service**.
3. Choose **Public Git repository** and paste:
   `https://github.com/patan-jamsheer/campushub-pdftools`
4. Render reads `Dockerfile` automatically. Leave everything else at the defaults and click **Create Web Service**.
5. Wait for the first build (~3–5 minutes). The log ends with
   `waitress-serve --listen=0.0.0.0:8080 ...` and the service goes **Live**.
6. Copy the address at the top — it looks like `https://campushub-pdftools.onrender.com`.
7. In the app: **PDF Tools → Compress PDF → Compression server → Change**, paste that address, **Save**, then
   press **Test**. It should answer `Connected. Engine: ghostscript`.

No APK rebuild is needed: the address is stored in the app.

### Expected behaviour on the free plan

- The service **sleeps after ~15 minutes** without traffic, and the next request takes 30–60 s while it wakes.
  The app's request timeout is 180 s, so the first compression after a sleep still succeeds — it is just slow.
  Pressing **Test** first also wakes it.
- 512 MB RAM and a shared CPU. A 5–10 MB PDF compresses in a few seconds; a 30 MB 500-page scan may need the
  full timeout.
- Free instances are fine for personal use. For always-on, upgrade the instance or use another host.

### If the build fails

Look at the log. The only realistic cause is Docker Hub rate limits on a brand-new network; pressing
**Manual Deploy → Clear build cache & deploy** fixes it.

## Alternatives

| Host | How | Notes |
| --- | --- | --- |
| **Render Blueprint** | New + → Blueprint → pick the same repo | Uses `render.yaml`; identical result |
| **Railway** | New Project → Deploy from GitHub repo | `Procfile` is already there; set `PORT` if asked |
| **Fly.io** | `fly launch` in this folder, `fly deploy` | Needs a card on file; always-on without sleep |
| **Your PC + tunnel** | `run-with-tunnel.ps1` | Free, but only while the PC is on and the URL changes |

## What the container does

- Installs **Ghostscript**, so the deployed server uses `/prepress`, `/ebook` and `/screen` — the same
  downsample-and-recompress presets iLovePDF uses — with PyMuPDF as the second engine and the verifier.
- Serves with **waitress** (4 threads), never the Flask development server.
- Runs as a non-root user, exposes `PORT` (8080), and has a `/api/health` health check.
- Keeps every uploaded file in a fresh temp directory that is deleted when the request ends.

## Limits (set in `render.yaml`)

| Setting | Value |
| --- | --- |
| Upload size | 30 MB (`PDFTOOLS_MAX_UPLOAD_BYTES`) |
| Pages | 3000 (`PDFTOOLS_MAX_PAGES`) |
| Timeout | 180 s (`PDFTOOLS_TIMEOUT_SECONDS`) |

Raising the upload limit means changing the app's `MAX_PDF_BYTES` too and rebuilding the APK.
