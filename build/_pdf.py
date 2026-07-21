"""Shared PDF text extraction for the statement parsers."""
import subprocess


def raw_text(path):
    """Return the layout-preserving text of a PDF via poppler's pdftotext."""
    return subprocess.run(
        ["pdftotext", "-layout", path, "-"], capture_output=True, text=True
    ).stdout
