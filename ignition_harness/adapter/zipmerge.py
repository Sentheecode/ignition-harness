"""Merge project additions into a native Gateway export without replacing identity files."""

import hashlib
import io
import zipfile
from pathlib import Path

from .errors import AdapterError

MAX_ZIP_BYTES = 32 * 1024 * 1024
PROTECTED_SEGMENTS = {"project.json", "global-props", "global-props.json"}


def _safe_zip_name(name):
    if not isinstance(name, str) or not name or name.endswith("/"):
        return None
    parts = name.replace("\\", "/").split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    if name.startswith("/") or ":" in parts[0]:
        return None
    return "/".join(parts)


def is_protected(name):
    return any(part in PROTECTED_SEGMENTS for part in name.split("/"))


def _read_base(raw):
    if not isinstance(raw, (bytes, bytearray)):
        raise AdapterError("invalid_zip")
    if len(raw) > MAX_ZIP_BYTES:
        raise AdapterError("input_too_large")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise AdapterError("invalid_zip") from None
    entries = {}
    try:
        for info in archive.infolist():
            name = _safe_zip_name(info.filename)
            if name is None or info.is_dir():
                continue
            payload = archive.read(info)
            if len(payload) > MAX_ZIP_BYTES:
                raise AdapterError("input_too_large")
            entries[name] = payload
    finally:
        archive.close()
    return entries


def _read_additions(root):
    base = Path(root).resolve()
    if not base.is_dir():
        raise AdapterError("invalid_additions")
    found = {}
    total = 0
    for path in sorted(base.rglob("*")):
        if path.is_symlink() or not path.is_file():
            if path.is_symlink():
                raise AdapterError("symlink_rejected")
            continue
        relative = path.resolve().relative_to(base).as_posix()
        name = _safe_zip_name(relative)
        if name is None:
            raise AdapterError("invalid_additions")
        payload = path.read_bytes()
        total += len(payload)
        if total > MAX_ZIP_BYTES:
            raise AdapterError("input_too_large")
        found[name] = payload
    return found


def merge_project_zip(base_bytes, additions_dir=None):
    """Return zip bytes plus a public description of what was preserved.

    Native ``project.json`` and ``global-props`` entries stay byte-for-byte.
    Additions are not allowed to replace those paths.
    """
    entries = _read_base(base_bytes)
    additions = _read_additions(additions_dir) if additions_dir else {}
    skipped = []
    merged = []
    for name, payload in additions.items():
        if is_protected(name):
            skipped.append(name)
            continue
        entries[name] = payload
        merged.append(name)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            archive.writestr(name, entries[name])
    raw = buffer.getvalue()
    if len(raw) > MAX_ZIP_BYTES:
        raise AdapterError("input_too_large")
    preserved = sorted(name for name in entries if is_protected(name))
    return {
        "bytes": raw,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "byte_length": len(raw),
        "preserved": preserved,
        "merged_additions": merged,
        "skipped_protected_additions": skipped,
    }
