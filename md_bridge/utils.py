"""Small helpers shared by the rest of the package."""

from __future__ import annotations

import datetime as _dt
import hashlib
import os
from pathlib import Path
from typing import Iterable

# File extensions Marvelous Designer can produce that Cinema 4D can read.
SUPPORTED_GEOMETRY_EXTS: tuple[str, ...] = (".obj", ".fbx", ".abc")

# Texture extensions we look for next to an exported geometry file.
SUPPORTED_TEXTURE_EXTS: tuple[str, ...] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".tga",
    ".exr",
    ".bmp",
)


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp suitable for manifests."""
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def detect_format(path: str | os.PathLike[str]) -> str:
    """Return ``OBJ``, ``FBX`` or ``ABC`` for a given geometry file.

    Raises ``ValueError`` if the extension is not one MD/C4D understand.
    """
    ext = Path(path).suffix.lower()
    if ext == ".obj":
        return "OBJ"
    if ext == ".fbx":
        return "FBX"
    if ext == ".abc":
        return "ABC"
    raise ValueError(f"Unsupported geometry extension: {ext!r}")


def garment_name(path: str | os.PathLike[str]) -> str:
    """Derive a human-friendly garment name from a file path."""
    return Path(path).stem


def find_textures(
    geometry_path: str | os.PathLike[str],
    texture_folder: str | os.PathLike[str] | None,
) -> list[str]:
    """Find textures associated with an export.

    Looks in two places:

    1. The directory the geometry file lives in.
    2. The ``texture_folder`` from config, if provided and different.

    Matching is by filename stem prefix — a texture whose name starts
    with the garment stem is treated as belonging to that garment.
    """
    geo = Path(geometry_path)
    stem = geo.stem.lower()

    candidates: list[Path] = []
    search_dirs: list[Path] = [geo.parent]
    if texture_folder:
        tf = Path(texture_folder)
        if tf.exists() and tf.resolve() != geo.parent.resolve():
            search_dirs.append(tf)

    for directory in search_dirs:
        if not directory.is_dir():
            continue
        for child in directory.iterdir():
            if not child.is_file():
                continue
            if child.suffix.lower() not in SUPPORTED_TEXTURE_EXTS:
                continue
            if child.stem.lower().startswith(stem):
                candidates.append(child)

    seen: set[str] = set()
    unique: list[str] = []
    for c in candidates:
        key = str(c.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(str(c))
    return unique


def hash_file(path: str | os.PathLike[str], chunk: int = 65536) -> str:
    """Return a short SHA-1 of the file contents.

    Useful for the manifest so downstream tools can tell whether two
    entries point at the same bytes.
    """
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def iter_geometry(folder: str | os.PathLike[str]) -> Iterable[Path]:
    """Yield every supported geometry file directly inside ``folder``."""
    p = Path(folder)
    if not p.is_dir():
        return
    for child in p.iterdir():
        if child.is_file() and child.suffix.lower() in SUPPORTED_GEOMETRY_EXTS:
            yield child


def ensure_dir(path: str | os.PathLike[str]) -> Path:
    """Create ``path`` (and parents) if missing, return it as a ``Path``."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
