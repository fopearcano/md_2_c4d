"""Resolve the newest *valid* export listed in the bridge manifest.

A valid manifest entry has all of the following:

- ``format`` is one of ``OBJ``, ``FBX`` or ``ABC``.
- ``garment`` is a non-empty string.
- ``timestamp`` parses as ISO-8601.
- ``file`` resolves to a real file on disk (paths in the manifest may
  be absolute or relative to the export folder).

Resolution walks entries newest-first; the first one that passes
validation wins. That way a corrupted *latest* entry — for example
the file got moved or the export crashed mid-write — does not block
the pipeline from picking up the previous good export.

Texture paths are validated best-effort: missing textures are dropped
from the returned list and counted in :attr:`ResolvedExport.textures_missing`.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import BridgeConfig
from .export_manifest import MANIFEST_FILENAME

VALID_FORMATS: tuple[str, ...] = ("OBJ", "FBX", "ABC")


class ResolverError(RuntimeError):
    """Raised for user-facing resolver failures."""


@dataclass
class ResolvedExport:
    """Structured info about a resolved export entry."""

    garment: str
    format: str
    file: Path
    timestamp: str
    textures: list[Path] = field(default_factory=list)
    textures_missing: int = 0
    scale_factor: float = 1.0
    axis_preset: str = "Y_UP"
    sha1: str | None = None
    raw_entry: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "garment": self.garment,
            "format": self.format,
            "file": str(self.file),
            "timestamp": self.timestamp,
            "textures": [str(p) for p in self.textures],
            "textures_missing": self.textures_missing,
            "scale_factor": self.scale_factor,
            "axis_preset": self.axis_preset,
            "sha1": self.sha1,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _resolve_export_folder(config: BridgeConfig) -> Path:
    folder = Path(config.export_folder).expanduser()
    if not folder.is_absolute():
        folder = folder.resolve()
    return folder


def _read_entries(manifest: Path) -> list[dict[str, Any]]:
    if not manifest.exists():
        raise ResolverError(
            f"manifest.json not found at {manifest}. "
            "Run an export or `python -m md_bridge write-manifest <file>` first."
        )
    try:
        with manifest.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ResolverError(f"{manifest} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ResolverError(
            f"{manifest} must contain a JSON array, got {type(data).__name__}"
        )
    return data


def _parse_timestamp(value: Any) -> _dt.datetime | None:
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # ``fromisoformat`` on Python <3.11 doesn't accept a trailing ``Z``;
    # normalise it to ``+00:00`` so hand-written manifests still parse.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return _dt.datetime.fromisoformat(s)
    except ValueError:
        return None


def _resolve_file(raw: Any, folder: Path) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = (folder / p).resolve()
    if not p.is_file():
        return None
    return p


def _validate_entry(
    entry: Any,
    folder: Path,
) -> tuple[ResolvedExport | None, str]:
    """Return ``(export, "")`` on success, or ``(None, reason)`` on failure."""
    if not isinstance(entry, dict):
        return None, "entry is not a JSON object"

    fmt_raw = entry.get("format")
    fmt = str(fmt_raw).upper() if fmt_raw is not None else ""
    if fmt not in VALID_FORMATS:
        return None, f"format {fmt_raw!r} not in {VALID_FORMATS}"

    garment = entry.get("garment")
    if not isinstance(garment, str) or not garment.strip():
        return None, "garment is missing or empty"

    timestamp = entry.get("timestamp")
    if _parse_timestamp(timestamp) is None:
        return None, f"timestamp {timestamp!r} is not ISO-8601"

    file_path = _resolve_file(entry.get("file"), folder)
    if file_path is None:
        return None, f"file {entry.get('file')!r} does not exist"

    raw_textures = entry.get("textures") or []
    if not isinstance(raw_textures, list):
        return None, "textures field is not a list"

    textures: list[Path] = []
    missing = 0
    for t in raw_textures:
        if not isinstance(t, str):
            missing += 1
            continue
        p = Path(t)
        if not p.is_absolute():
            p = (folder / p).resolve()
        if p.is_file():
            textures.append(p)
        else:
            missing += 1

    try:
        scale = float(entry.get("scale_factor", 1.0))
    except (TypeError, ValueError):
        scale = 1.0

    axis = entry.get("axis_preset", "Y_UP")
    if not isinstance(axis, str) or not axis.strip():
        axis = "Y_UP"

    sha = entry.get("sha1")
    if not isinstance(sha, str):
        sha = None

    return (
        ResolvedExport(
            garment=garment.strip(),
            format=fmt,
            file=file_path,
            timestamp=str(timestamp),
            textures=textures,
            textures_missing=missing,
            scale_factor=scale,
            axis_preset=axis,
            sha1=sha,
            raw_entry=dict(entry),
        ),
        "",
    )


def _sort_key(entry: Any) -> tuple[int, _dt.datetime]:
    """Sort key: parseable-timestamp tier first, then the timestamp itself.

    Entries whose timestamp does not parse fall into a lower tier so
    they sort *behind* every well-formed entry, regardless of the
    string they contain.
    """
    if not isinstance(entry, dict):
        return (0, _dt.datetime.min.replace(tzinfo=_dt.timezone.utc))
    ts = _parse_timestamp(entry.get("timestamp"))
    if ts is None:
        return (0, _dt.datetime.min.replace(tzinfo=_dt.timezone.utc))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_dt.timezone.utc)
    return (1, ts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def resolve_latest(config: BridgeConfig) -> ResolvedExport:
    """Return the newest valid export described in the manifest.

    Raises :class:`ResolverError` with a user-friendly message if the
    export folder is missing, the manifest is missing/empty/malformed,
    or no entry passes validation.
    """
    folder = _resolve_export_folder(config)
    if not folder.is_dir():
        raise ResolverError(
            f"Export folder is missing: {folder}. "
            "Edit 'export_folder' in config.json or run an export first."
        )

    manifest = folder / MANIFEST_FILENAME
    entries = _read_entries(manifest)
    if not entries:
        raise ResolverError(f"{manifest} is empty.")

    last_reason = "no entries inspected"
    for entry in sorted(entries, key=_sort_key, reverse=True):
        export, reason = _validate_entry(entry, folder)
        if export is not None:
            return export
        last_reason = reason

    raise ResolverError(
        f"No valid export entries in {manifest} (last reason: {last_reason})."
    )
