# Deploying the compression server (free, ~3 minutes)

## Current deployment

| Item | Value |
| --- | --- |
| Address | `https://campushub-pdftools.onrender.com` |
| Host | Render, free plan, Singapore region, Docker |
| Engine | **ghostscript** (PyMuPDF also available as the second engine / verifier) |
| Verified | `GET /api/health` -> 200; a 13.11 MB / 3-page image PDF -> 3.18 MB (75.73% smaller, 3 pages, same page size) |
| Auto-deploy | on, from `main` of <https://github.com/patan-jamsheer/campushub-pdftools> |

That address is the built-in release default in `src/modules/pdftools/config.ts`, and it can be overridden in
the app. Free instances sleep after ~15 minutes idle; the next request takes 30-60 s to wake.

The Android app needs a public **HTTPS** address. This folder is a complete, self-contained Docker service, so
the host builds it for you — no Python setup on the server, no build commands to type.

Everything here is already in the repository, so deploying is: open one link, click Apply.

## Render (free tier, no credit card)

**One click:** <https://render.com/deploy?repo=https://github.com/patan-jamsheer/campushub-pdftools>

1. Sign in at <https://render.com> with GitHub when asked (free, no card needed for the free instance type).
2. The page already has this repo selected — click **Apply**. It reads `render.yaml` and starts the build.
3. Wait for the first build (~3–5 minutes). The log ends with
   `waitress-serve --listen=0.0.0.0:<port> ...` and the service goes **Live**.
4. Copy the address at the top — it looks like `https://campushub-pdftools.onrender.com`.
5. In the app: **PDF Tools → Compress PDF → Compression server → Change**, paste that address, **Save**, then
   press **Test**. It should answer `Connected. Engine: ghostscript`.

If the one-click page asks you to install the GitHub app (some accounts do for Blueprints), use
**New + → Web Service → Public Git repository** instead and paste
`https://github.com/patan-jamsheer/campushub-pdftools`; Render builds the same `Dockerfile`.

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
