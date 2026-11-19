"""Harness-side, bounded extraction for dashboard document attachments.

Reads one JSON request from stdin and writes one JSON result to stdout. No
network access and no persistent copy of the uploaded file.
"""
import base64
import binascii
import json
import re
import subprocess
import sys
from pathlib import Path

MAX_BYTES = 8 * 1024 * 1024
MAX_CHARS = 10000
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json", ".html", ".xml", ".py", ".js", ".ts", ".css", ".log"}
DATA_URL = re.compile(r"^data:([a-zA-Z0-9.+/-]+);base64,([A-Za-z0-9+/=]+)$")


def convert(item):
    name = item.get("name")
    url = item.get("data_url")
    if not isinstance(name, str) or not name or len(name) > 160 or Path(name).name != name:
        raise ValueError("attachment needs a simple file name")
    match = DATA_URL.fullmatch(url) if isinstance(url, str) else None
    if not match:
        raise ValueError("attachment needs a base64 data URL")
    suffix = Path(name).suffix.lower()
    mime = match.group(1).lower()
    if suffix == ".pdf":
        if mime != "application/pdf":
            raise ValueError("PDF extension and content type disagree")
    elif suffix in TEXT_SUFFIXES:
        if not (mime.startswith("text/") or mime in {"application/json", "application/xml", "application/javascript", "application/octet-stream"}):
            raise ValueError("text file extension and content type disagree")
    else:
        raise ValueError("unsupported attachment type: " + suffix)
    try:
        data = base64.b64decode(match.group(2), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid attachment encoding") from exc
    if not data or len(data) > MAX_BYTES:
        raise ValueError("attachment must be between 1 byte and 8 MiB")
    if suffix == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError("file is not a PDF")
        try:
            run = subprocess.run(["pdftotext", "-layout", "-f", "1", "-l", "30", "-", "-"],
                                 input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 timeout=20, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("PDF text extraction unavailable") from exc
        if run.returncode:
            raise ValueError("PDF text extraction failed")
        content = run.stdout.decode("utf-8", errors="replace").strip()
        method = "pdf_text"
        note = "Extracted PDF text (first 30 pages); page images, charts, and layout may be omitted."
    else:
        try:
            content = data.decode("utf-8-sig").strip()
        except UnicodeDecodeError as exc:
            raise ValueError("text attachment must be UTF-8") from exc
        method = "plain_text"
        note = "Read as UTF-8 text."
    if not content:
        raise ValueError("No extractable text; scanned PDFs need OCR or a vision-capable model")
    source_chars = len(content)
    truncated = source_chars > MAX_CHARS
    if truncated:
        content = content[:MAX_CHARS]
        note += " Content was truncated to 10,000 characters."
    return {"name": name, "type": mime, "method": method, "text": content,
            "source_chars": source_chars, "truncated": truncated, "note": note}


if __name__ == "__main__":
    try:
        print(json.dumps({"ok": True, "result": convert(json.load(sys.stdin))}, ensure_ascii=False))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)
