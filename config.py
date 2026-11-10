"""Settings for the PDF Tools compression service.

Everything can be changed with environment variables, so the same code runs on a laptop and on a host.
"""
from __future__ import annotations

import os
import shutil

SERVICE_NAME = 'campushub-pdftools'
SERVICE_VERSION = '1.0.0'


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# A Campus Hub PDF is picked on a phone, so 30 MB matches the app's own picker limit.
MAX_UPLOAD_BYTES = _int('PDFTOOLS_MAX_UPLOAD_BYTES', 30 * 1024 * 1024)
# A hard cap on pages keeps one request from tying up the worker indefinitely.
MAX_PAGES = _int('PDFTOOLS_MAX_PAGES', 3000)
# Ghostscript runs as a child process, so it needs its own timeout. PyMuPDF cannot be interrupted as easily,
# which is why the page cap matters.
PROCESS_TIMEOUT_SECONDS = _int('PDFTOOLS_TIMEOUT_SECONDS', 180)
PORT = _int('PORT', 5000)

# Ghostscript is optional. When it is installed (or PDFTOOLS_GS_BINARY points at it) it is preferred, because
# its /screen, /ebook and /prepress presets are the same downsample-and-recompress pipeline iLovePDF uses.
GS_BINARY = (
    os.environ.get('PDFTOOLS_GS_BINARY')
    or shutil.which('gswin64c')
    or shutil.which('gswin32c')
    or shutil.which('gs')
    or ''
)

# The Android app is a native client and does not send an Origin header. These origins are only for a browser
# client during development, such as a local React page.
ALLOWED_ORIGINS = tuple(
    origin.strip()
    for origin in os.environ.get(
        'PDFTOOLS_ALLOWED_ORIGINS',
        'http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173',
    ).split(',')
    if origin.strip()
)

# The same three labels the app shows. `low` keeps the most quality, `high` produces the smallest file.
#   ghostscript : the -dPDFSETTINGS preset (prepress = 300 dpi, ebook = 150 dpi, screen = 72 dpi)
#   pymupdf     : rewrite_images() settings (DPI threshold, DPI target, JPEG quality)
PRESETS = {
    'low': {
        'ghostscript': '/prepress',
        'dpi_threshold': 300,
        'dpi_target': 220,
        'quality': 85,
        'bitonal': False,
    },
    'medium': {
        'ghostscript': '/ebook',
        'dpi_threshold': 200,
        'dpi_target': 150,
        'quality': 72,
        'bitonal': True,
    },
    'high': {
        'ghostscript': '/screen',
        'dpi_threshold': 150,
        'dpi_target': 96,
        'quality': 55,
        'bitonal': True,
    },
}
