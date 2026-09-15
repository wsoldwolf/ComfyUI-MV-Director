"""Decode browser-embedded UTF-8 text without opening a user path."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json


MAX_TEXT_BYTES = 16 * 1024 * 1024


def _validate_metadata(basename: str, browser_metadata_json: str) -> object:
    if not isinstance(basename, str) or not basename:
        raise ValueError("basename must not be empty")
    if "/" in basename or "\\" in basename:
        raise ValueError("basename must not contain a path")
    if not basename.lower().endswith(".txt"):
        raise ValueError("only .txt files are accepted")
    try:
        metadata = json.loads(browser_metadata_json)
    except json.JSONDecodeError as exc:
        raise ValueError("browser_metadata_json must be valid JSON") from exc
    if not isinstance(metadata, dict):
        raise ValueError("browser metadata must be a JSON object")
    return metadata


def decode_embedded_text(
    file_data_base64: str,
    basename: str,
    browser_metadata_json: str,
) -> str:
    _validate_metadata(basename, browser_metadata_json)
    if not isinstance(file_data_base64, str) or not file_data_base64:
        raise ValueError("embedded file data must not be empty")
    max_encoded_length = 4 * ((MAX_TEXT_BYTES + 2) // 3)
    if len(file_data_base64) > max_encoded_length:
        raise ValueError("text file exceeds the 16 MiB limit")
    try:
        raw = base64.b64decode(file_data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("embedded file data is not valid Base64") from exc
    if len(raw) > MAX_TEXT_BYTES:
        raise ValueError("text file exceeds the 16 MiB limit")
    if b"\x00" in raw:
        raise ValueError("text file must not contain NUL")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("text file must be UTF-8 or UTF-8 BOM") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n")


def text_file_fingerprint(
    file_data_base64: str,
    basename: str,
    browser_metadata_json: str,
) -> str:
    text = decode_embedded_text(file_data_base64, basename, browser_metadata_json)
    metadata = _validate_metadata(basename, browser_metadata_json)
    canonical_metadata = json.dumps(
        metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256()
    for value in (text, basename, canonical_metadata):
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()
