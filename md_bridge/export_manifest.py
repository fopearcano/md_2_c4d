"""Manifest writer.

A manifest is a JSON array of entries kept inside the export folder
(default ``<export_folder>/manifest.json``). Each entry records one
exported file plus the metadata Cinema 4D needs to import it
correctly: scale, axis, garment name, and any associated textures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import BridgeConfig
from .utils import (
    detect_format,
    find_textures,
    garment_name,
    hash_file,
    utc_timestamp,
)

MANIFEST_FILENAME = "manifest.json"


def manifest_path(config: BridgeConfig) -> Path:
    """Return the path to the manifest file for the given config."""
    return Path(config.export_folder) / MANIFEST_FILENAME


def build_entry(file_path: str | Path, config: BridgeConfig) -> dict[str, Any]:
    """Build a single manifest entry for ``file_path``."""
    p = Path(file_path)
    if not p.is_file():
        raise FileNotFoundError(f"Export file not found: {p}")

    fmt = detect_format(p)
    textures = find_textures(p, config.texture_folder)

    return {
        "file": str(p),
        "format": fmt,
        "timestamp": utc_timestamp(),
        "garment": garment_name(p),
        "textures": textures,
        "scale_factor": config.scale_factor,
        "axis_preset": config.axis_preset,
        "sha1": hash_file(p),
    }


def read_manifest(path: str | Path) -> list[dict[str, Any]]:
    """Read an existing manifest file, returning ``[]`` if missing."""
    p = Path(path)
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"Manifest at {p} is not a JSON array")
    return data


def write_manifest(entries: list[dict[str, Any]], path: str | Path) -> Path:
    """Write the full list of entries back to disk."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2)
        fh.write("\n")
    return p


def append_entry(entry: dict[str, Any], path: str | Path) -> Path:
    """Append a single entry to the manifest at ``path``."""
    entries = read_manifest(path)
    entries.append(entry)
    return write_manifest(entries, path)


def record_export(file_path: str | Path, config: BridgeConfig) -> dict[str, Any]:
    """Build an entry for ``file_path`` and append it to the manifest.

    Returns the entry that was appended.
    """
    entry = build_entry(file_path, config)
    append_entry(entry, manifest_path(config))
    return entry
