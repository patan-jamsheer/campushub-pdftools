"""The real PDF compression engine.

Compression means what it means on iLovePDF: large images are downsampled and re-encoded, not just re-wrapped.
Two engines can do that here:

* Ghostscript (used when installed) with its /prepress, /ebook and /screen presets.
* PyMuPDF's ``Document.rewrite_images()``, which is a pip dependency and therefore always available.

PyMuPDF is also used to read the page count and to verify every candidate output before it is returned. The engine
picks the smallest valid candidate, and if the original is already the smallest it returns the original bytes instead
of handing back a larger file.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Optional

import config

try:  # PyMuPDF is a hard dependency, but a clear message beats an import traceback at request time.
    import pymupdf
except Exception:  # pragma: no cover - only happens on a broken install
    pymupdf = None  # type: ignore[assignment]


class PdfError(Exception):
    """An error that is safe to show to the person using the app."""

    def __init__(self, message: str, code: str = 'invalid_pdf', status: int = 422):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


@dataclass
class CompressOutcome:
    output_path: str
    engine: str
    pages: int
    original_bytes: int
    output_bytes: int
    reduced: bool

    @property
    def saved_bytes(self) -> int:
        return self.original_bytes - self.output_bytes

    @property
    def reduction_percent(self) -> float:
        if self.original_bytes <= 0:
            return 0.0
        return (self.saved_bytes / self.original_bytes) * 100.0


def pymupdf_available() -> bool:
    return pymupdf is not None


def available_engines() -> dict:
    return {'ghostscript': bool(config.GS_BINARY), 'pymupdf': pymupdf_available()}


def preferred_engine() -> str:
    if config.GS_BINARY and pymupdf_available():
        return 'ghostscript'
    if pymupdf_available():
        return 'pymupdf'
    return 'none'


def probe_pdf(path: str) -> int:
    """Verifies that `path` is a readable, unencrypted PDF and returns its page count."""
    if pymupdf is None:
        raise PdfError(
            'The PDF engine is not installed on the server. Run pip install -r requirements.txt.',
            'engine_unavailable',
            503,
        )
    try:
        doc = pymupdf.open(path)
    except Exception:
        raise PdfError('This file is not a valid PDF, or it is damaged.', 'invalid_pdf', 422)
    try:
        if not doc.is_pdf:
            raise PdfError('This file is not a valid PDF, or it is damaged.', 'invalid_pdf', 422)
        if doc.needs_pass:
            raise PdfError(
                'This PDF is password-protected. Remove the password, then try again.',
                'encrypted_pdf',
                422,
            )
        pages = doc.page_count
        if pages < 1:
            raise PdfError('This PDF has no pages.', 'empty_pdf', 422)
        if pages > config.MAX_PAGES:
            raise PdfError(
                f'This PDF has {pages} pages. The limit is {config.MAX_PAGES} pages per file.',
                'too_many_pages',
                413,
            )
        return pages
    finally:
        doc.close()


def compress_pdf(input_path: str, work_dir: str, preset: str) -> CompressOutcome:
    """Compresses `input_path` inside `work_dir` and returns the smallest valid result.

    Raises PdfError for input the service refuses (damaged, encrypted, too many pages) or when every engine fails.
    """
    if preset not in config.PRESETS:
        raise PdfError(
            f'Unknown compression preset "{preset}". Use low, medium or high.',
            'invalid_preset',
            400,
        )

    original_bytes = os.path.getsize(input_path)
    pages = probe_pdf(input_path)
    settings = config.PRESETS[preset]

    candidates: list[tuple[str, str]] = []
    failures: list[str] = []

    if config.GS_BINARY:
        gs_out = os.path.join(work_dir, 'ghostscript.pdf')
        try:
            _run_ghostscript(input_path, gs_out, settings)
            _verify_output(gs_out, pages)
            candidates.append((gs_out, 'ghostscript'))
        except Exception as exc:  # a Ghostscript failure must not stop the PyMuPDF attempt
            failures.append(f'ghostscript: {exc}')

    if pymupdf_available():
        py_out = os.path.join(work_dir, 'pymupdf.pdf')
        try:
            _run_pymupdf(input_path, py_out, settings)
            _verify_output(py_out, pages)
            candidates.append((py_out, 'pymupdf'))
        except Exception as exc:
            failures.append(f'pymupdf: {exc}')

        clean_out = os.path.join(work_dir, 'cleaned.pdf')
        try:
            _run_pymupdf_clean(input_path, clean_out)
            _verify_output(clean_out, pages)
            candidates.append((clean_out, 'pymupdf'))
        except Exception as exc:
            failures.append(f'pymupdf-clean: {exc}')

    if not candidates:
        raise PdfError(
            'The PDF could not be compressed. It may use features this server cannot process.',
            'processing_failed',
            422,
        )

    # The untouched upload is a candidate too. Returning it is honest when the file is already optimised,
    # and it guarantees that compression never makes someone's file bigger.
    candidates.append((input_path, 'original'))
    best_path, engine = min(candidates, key=lambda item: os.path.getsize(item[0]))
    output_bytes = os.path.getsize(best_path)

    return CompressOutcome(
        output_path=best_path,
        engine=engine,
        pages=pages,
        original_bytes=original_bytes,
        output_bytes=output_bytes,
        reduced=output_bytes < original_bytes,
    )


def _verify_output(path: str, expected_pages: int) -> None:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        raise ValueError('the engine produced no output')
    with open(path, 'rb') as handle:
        if handle.read(5) != b'%PDF-':
            raise ValueError('the engine produced something that is not a PDF')
    pages = probe_pdf(path)
    if pages != expected_pages:
        raise ValueError(f'the engine changed the page count ({expected_pages} -> {pages})')


def _run_ghostscript(input_path: str, output_path: str, settings: dict) -> None:
    command = [
        config.GS_BINARY,
        '-sDEVICE=pdfwrite',
        '-dCompatibilityLevel=1.7',
        f'-dPDFSETTINGS={settings["ghostscript"]}',
        '-dNOPAUSE',
        '-dQUIET',
        '-dBATCH',
        '-dSAFER',
        # Keep the page orientation the author chose instead of letting Ghostscript rotate pages.
        '-dAutoRotatePages=/None',
        '-dDetectDuplicateImages=true',
        '-dCompressFonts=true',
        '-dSubsetFonts=true',
        f'-sOutputFile={output_path}',
        input_path,
    ]
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=config.PROCESS_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode('utf-8', 'replace').strip().splitlines()
        raise RuntimeError(detail[-1] if detail else f'exit code {completed.returncode}')


def _run_pymupdf(input_path: str, output_path: str, settings: dict) -> None:
    doc = pymupdf.open(input_path)
    try:
        if doc.needs_pass:
            raise PdfError('This PDF is password-protected.', 'encrypted_pdf', 422)
        try:
            doc.subset_fonts()
        except Exception:
            pass  # an optional optimisation; not every font can be subset
        doc.rewrite_images(
            dpi_threshold=settings['dpi_threshold'],
            dpi_target=settings['dpi_target'],
            quality=settings['quality'],
            lossy=True,
            lossless=True,
            bitonal=settings['bitonal'],
            color=True,
            gray=True,
        )
        doc.save(
            output_path,
            garbage=4,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            clean=True,
        )
    finally:
        doc.close()


def _run_pymupdf_clean(input_path: str, output_path: str) -> None:
    """Structural clean-up only. It can still help PDFs with unused objects or uncompressed streams."""
    doc = pymupdf.open(input_path)
    try:
        doc.save(
            output_path,
            garbage=4,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            clean=True,
        )
    finally:
        doc.close()
