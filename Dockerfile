# PDF Tools compression service.
#
# Ghostscript is installed in the image on purpose: its /prepress, /ebook and /screen presets are the same
# downsample-and-recompress pipeline iLovePDF uses, so the deployed server is not limited to the PyMuPDF fallback.
# PyMuPDF is still used as a second engine and to verify every output.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

# ghostscript: PDF image downsampling. No GUI packages, so the image stays small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ghostscript \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py compress.py config.py ./

# Never run the web server as root.
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

# A container has no curl, so the check uses Python itself.
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/api/health',timeout=8)"

# waitress is a production WSGI server; the Flask development server is not exposed.
# 4 threads keeps one large compression from blocking the health check.
CMD ["sh", "-c", "waitress-serve --listen=0.0.0.0:${PORT} --threads=4 --channel-timeout=300 app:app"]
