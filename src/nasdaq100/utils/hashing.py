"""Cryptographic hashing utilities and git version tracking."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def sha256_file(path: Path | str) -> str:
    """Compute the SHA-256 hash of a file on disk."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"File not found for hashing: {p}")

    hasher = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def sha256_json(obj: Any) -> str:
    """Compute deterministic SHA-256 over canonical sorted JSON."""
    encoded = json.dumps(
        obj,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def get_git_commit() -> str:
    """Return the current git commit hash (HEAD), or 'unknown' if not available."""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return commit if commit else "unknown"
    except Exception:
        return "unknown"
