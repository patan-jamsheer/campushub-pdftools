"""Campus Hub PDF Tools compression API.

Run it from this folder:

    python app.py

Endpoints
---------
GET  /api/health          Which engine is ready, and the upload/page limits.
POST /api/pdf/compress    multipart/form-data: `file` (PDF), `preset` = low | medium | high.
                          Returns the compressed PDF itself (application/pdf).
"""
from __future__ import annotations

import io
import os
import re
import shutil
import tempfile

from flask import Flask, jsonify, request, send_file

import config
from compress import (
    PdfError,
    available_engines,
    compress_pdf,
    preferred_engine,
)

EXPOSED_HEADERS = (
    'X-Original-Bytes',
    'X-Output-Bytes',
    'X-Saved-Bytes',
    'X-Reduction-Percent',
    'X-Pages',
    'X-Engine',
    'X-Reduced',
)


def _error(status: int, code: str, message: str):
    return jsonify({'error': {'code': code, 'message': message}}), status


def _output_name(original: str | None) -> str:
    """A safe download name: no folders, no control characters, at most 80 characters."""
    stem = os.path.splitext(os.path.basename(original or 'document'))[0]
    stem = re.sub(r'[^A-Za-z0-9._ -]+', '_', stem).strip(' ._-')
    stem = re.sub(r'\s+', ' ', stem)[:60].strip() or 'document'
    return f'{stem}-compressed.pdf'


def create_app() -> Flask:
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = config.MAX_UPLOAD_BYTES + (2 * 1024 * 1024)
    app.config['JSON_SORT_KEYS'] = False

    @app.after_request
    def add_headers(response):
        # No document is cached by a proxy or by the browser.
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'

        origin = request.headers.get('Origin')
        if origin and origin in config.ALLOWED_ORIGINS:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Vary'] = 'Origin'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
            response.headers['Access-Control-Expose-Headers'] = ', '.join(EXPOSED_HEADERS)
        return response

    @app.get('/api/health')
    def health():
        engine = preferred_engine()
        return jsonify(
            {
                'status': 'ok' if engine != 'none' else 'degraded',
                'service': config.SERVICE_NAME,
                'version': config.SERVICE_VERSION,
                'engine': engine,
                'engines': available_engines(),
                'maxUploadBytes': config.MAX_UPLOAD_BYTES,
                'maxPages': config.MAX_PAGES,
                'presets': list(config.PRESETS),
            }
        )

    @app.post('/api/pdf/compress')
    def compress():
        upload = request.files.get('file')
        if upload is None:
            return _error(400, 'missing_file', 'Attach a PDF in the "file" field.')

        preset = request.form['preset'].strip().lower() if 'preset' in request.form else 'medium'
        if preset not in config.PRESETS:
            return _error(400, 'invalid_preset', 'Compression preset must be low, medium or high.')

        data = upload.stream.read(config.MAX_UPLOAD_BYTES + 1)
        if not data:
            return _error(400, 'empty_file', 'The uploaded file is empty.')
        if len(data) > config.MAX_UPLOAD_BYTES:
            return _error(
                413,
                'file_too_large',
                f'The PDF is larger than the {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.',
            )
        if not data.startswith(b'%PDF-'):
            return _error(415, 'not_a_pdf', 'That file is not a PDF.')

        work_dir = tempfile.mkdtemp(prefix='pdftools-')
        try:
            source = os.path.join(work_dir, 'input.pdf')
            with open(source, 'wb') as handle:
                handle.write(data)

            outcome = compress_pdf(source, work_dir, preset)

            with open(outcome.output_path, 'rb') as handle:
                payload = handle.read()
            if not payload.startswith(b'%PDF-'):
                raise PdfError('The compressed file was not a valid PDF.', 'processing_failed', 500)

            response = send_file(
                io.BytesIO(payload),
                mimetype='application/pdf',
                as_attachment=True,
                download_name=_output_name(upload.filename),
                max_age=0,
            )
            response.headers['X-Original-Bytes'] = str(outcome.original_bytes)
            response.headers['X-Output-Bytes'] = str(outcome.output_bytes)
            response.headers['X-Saved-Bytes'] = str(outcome.saved_bytes)
            response.headers['X-Reduction-Percent'] = f'{outcome.reduction_percent:.2f}'
            response.headers['X-Pages'] = str(outcome.pages)
            response.headers['X-Engine'] = outcome.engine
            response.headers['X-Reduced'] = 'true' if outcome.reduced else 'false'
            return response
        except PdfError as exc:
            return _error(exc.status, exc.code, exc.message)
        except Exception:
            app.logger.exception('PDF compression failed')
            return _error(500, 'server_error', 'The server could not compress this PDF. Try again.')
        finally:
            # The uploaded file and every candidate output live only for the length of this request.
            shutil.rmtree(work_dir, ignore_errors=True)

    @app.errorhandler(413)
    def too_large(_exc):
        return _error(
            413,
            'file_too_large',
            f'The upload is larger than the {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.',
        )

    @app.errorhandler(404)
    def not_found(_exc):
        return _error(404, 'not_found', 'No such endpoint.')

    return app


app = create_app()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=config.PORT, threaded=True)
