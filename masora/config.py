"""User-side configuration locations and remote normalization (MASORA_DESIGN.md §9)."""

from __future__ import annotations

import os
import re
from pathlib import Path

HOME_ENV = "MASORA_HOME"
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")
_DOT_GIT_RE = re.compile(r"\.git$", re.IGNORECASE)


def masora_home() -> Path | None:
    value = os.environ.get(HOME_ENV)
    return Path(value) if value else None


def config_path() -> Path:
    home = masora_home()
    if home is not None:
        return home / "config.toml"
    return Path.home() / ".config" / "masora" / "config.toml"


def bases_root() -> Path:
    home = masora_home()
    if home is not None:
        return home / "bases"
    return Path.home() / ".local" / "share" / "masora" / "bases"


def normalize_remote(url: str) -> str:
    """Normalize a git remote for matching: lowercase host, no scheme, no user, no trailing `.git`."""
    text = url.strip()
    scheme = _SCHEME_RE.match(text)
    body = text[scheme.end() :] if scheme else text
    body = body.rstrip("/")
    if body.startswith("/"):
        return _DOT_GIT_RE.sub("", body)
    if not body:
        return ""
    at = body.rfind("@")
    if at >= 0:
        body = body[at + 1 :]
    head, slash, tail = body.partition("/")
    path = tail if slash else ""
    if ":" in head:
        host, _, rest = head.partition(":")
        path = f"{rest}/{path}" if path else rest
    else:
        host = head
    has_host = (scheme is not None and scheme.group(0) != "file://") or at >= 0 or "." in host
    host = host.lower() if has_host else host
    path = _DOT_GIT_RE.sub("", path)
    if not path:
        return host
    return f"{host}/{path}" if host else path
