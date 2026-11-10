"""API tests for the PDF Tools compression service.

The sample PDFs contain large photographic-style images, so PyMuPDF's rewrite_images() and Ghostscript have
something real to downsample and re-encode. A structural-only re-save would barely change them.
"""
from __future__ import annotations

import io
import os
import tempfile

import pymupdf
import pytest

import config
from app import create_app


def _image_pdf(path: str, pages: int = 2, pixels: int = 1800) -> None:
    """A PDF whose pages are full-page JPEGs of random noise (worst case for compression)."""
    doc = pymupdf.open()
    try:
        for _ in range(pages):
            page = doc.new_page(width=595, height=842)
            pix = pymupdf.Pixmap(pymupdf.csRGB, pixels, pixels, os.urandom(pixels * pixels * 3), False)
            jpeg = pix.tobytes('jpeg', jpg_quality=98)
            page.insert_image(page.rect, stream=jpeg)
        doc.save(path, deflate=False)
    finally:
        doc.close()


@pytest.fixture(scope='session')
def image_pdf_bytes() -> bytes:
    handle, path = tempfile.mkstemp(suffix='.pdf')
    os.close(handle)
    try:
        _image_pdf(path)
        with open(path, 'rb') as source:
            return source.read()
    finally:
        os.unlink(path)


@pytest.fixture()
def client():
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def _upload(client, data: bytes, name: str = 'noise.pdf', preset: str | None = 'medium'):
    form = {'file': (io.BytesIO(data), name)}
    if preset is not None:
        form['preset'] = preset
    return client.post('/api/pdf/compress', data=form, content_type='multipart/form-data')


def test_health_reports_a_ready_engine(client):
    response = client.get('/api/health')
    assert response.status_code == 200
    body = response.get_json()
    assert body['status'] == 'ok'
    assert body['engine'] in {'ghostscript', 'pymupdf'}
    assert body['engines']['pymupdf'] is True
    assert body['maxUploadBytes'] == config.MAX_UPLOAD_BYTES
    assert body['presets'] == ['low', 'medium', 'high']


@pytest.mark.parametrize('preset', ['low', 'medium', 'high'])
def test_compress_returns_a_smaller_valid_pdf(client, image_pdf_bytes, preset):
    response = _upload(client, image_pdf_bytes, preset=preset)

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.mimetype == 'application/pdf'
    assert response.data.startswith(b'%PDF-')
    assert response.headers['Content-Disposition'].startswith('attachment')

    output = pymupdf.open(stream=response.data, filetype='pdf')
    try:
        assert output.page_count == 2
        assert output.metadata is not None
    finally:
        output.close()

    original_bytes = len(image_pdf_bytes)
    output_bytes = len(response.data)
    assert int(response.headers['X-Original-Bytes']) == original_bytes
    assert int(response.headers['X-Output-Bytes']) == output_bytes
    assert int(response.headers['X-Pages']) == 2
    assert response.headers['X-Engine'] in {'ghostscript', 'pymupdf', 'original'}

    # Compression must never hand back a bigger file than the one that was uploaded.
    assert output_bytes <= original_bytes
    assert response.headers['X-Reduced'] == ('true' if output_bytes < original_bytes else 'false')

    saved = original_bytes - output_bytes
    assert int(response.headers['X-Saved-Bytes']) == saved
    assert float(response.headers['X-Reduction-Percent']) == pytest.approx(saved / original_bytes * 100, abs=0.01)

    # These fixtures are large, noisy images, so a real engine must actually shrink them.
    assert output_bytes < original_bytes


def test_high_is_smaller_than_low(client, image_pdf_bytes):
    low = _upload(client, image_pdf_bytes, preset='low')
    high = _upload(client, image_pdf_bytes, preset='high')
    assert low.status_code == high.status_code == 200
    assert len(high.data) < len(low.data)


def test_default_preset_is_medium(client, image_pdf_bytes):
    response = _upload(client, image_pdf_bytes, preset=None)
    assert response.status_code == 200
    assert response.headers['X-Engine'] in {'ghostscript', 'pymupdf'}
    assert response.headers['X-Pages'] == '2'


@pytest.mark.parametrize(
    'preset',
    ['', 'LOWEST', 'recommended', '../etc/passwd'],
)
def test_invalid_preset_is_rejected(client, image_pdf_bytes, preset):
    response = _upload(client, image_pdf_bytes, preset=preset)
    assert response.status_code == 400
    assert response.get_json()['error']['code'] == 'invalid_preset'


def test_missing_file_is_rejected(client):
    response = client.post('/api/pdf/compress', data={'preset': 'medium'}, content_type='multipart/form-data')
    assert response.status_code == 400
    assert response.get_json()['error']['code'] == 'missing_file'


def test_empty_file_is_rejected(client):
    response = _upload(client, b'')
    assert response.status_code == 400
    assert response.get_json()['error']['code'] == 'empty_file'


def test_non_pdf_content_is_rejected(client):
    response = _upload(client, b'this is plainly not a pdf')
    assert response.status_code == 415
    assert response.get_json()['error']['code'] == 'not_a_pdf'


def test_damaged_pdf_is_rejected(client):
    response = _upload(client, b'%PDF-1.7\nthis is not actually a PDF body')
    assert response.status_code == 422
    assert response.get_json()['error']['code'] == 'invalid_pdf'


def test_encrypted_pdf_is_rejected_with_a_useful_message(client):
    doc = pymupdf.open()
    try:
        doc.new_page()
        data = doc.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw='secret',
            owner_pw='secret',
            permissions=pymupdf.PDF_PERM_ACCESSIBILITY,
        )
    finally:
        doc.close()

    response = _upload(client, data)
    assert response.status_code == 422
    body = response.get_json()
    assert body['error']['code'] == 'encrypted_pdf'
    assert 'password' in body['error']['message'].lower()


def test_page_limit_is_enforced(client, image_pdf_bytes, monkeypatch):
    monkeypatch.setattr(config, 'MAX_PAGES', 1)
    response = _upload(client, image_pdf_bytes)
    assert response.status_code == 413
    assert response.get_json()['error']['code'] == 'too_many_pages'


def test_download_name_is_safe_and_marked(client, image_pdf_bytes):
    response = _upload(client, image_pdf_bytes, name='../My Report?.PDF')
    assert response.status_code == 200
    disposition = response.headers['Content-Disposition']
    assert 'My Report-compressed.pdf' in disposition


def test_temporary_directories_are_removed(client, image_pdf_bytes):
    before = {name for name in os.listdir(tempfile.gettempdir()) if name.startswith('pdftools-')}
    response = _upload(client, image_pdf_bytes)
    assert response.status_code == 200
    after = {name for name in os.listdir(tempfile.gettempdir()) if name.startswith('pdftools-')}
    assert after == before


def test_unknown_endpoint_returns_json(client):
    response = client.get('/api/nope')
    assert response.status_code == 404
    assert response.get_json()['error']['code'] == 'not_found'
