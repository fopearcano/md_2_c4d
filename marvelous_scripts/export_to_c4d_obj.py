"""Export the current Marvelous Designer scene to OBJ for the C4D bridge.

Run from inside Marvelous Designer:

    File -> Python Script -> Run Script -> select this file.

What it does
------------
1. Reads the bridge ``config.json`` from the parent repo (export folder,
   scale, axis preset, texture folder).
2. Calls the Marvelous Designer Python API to export the open scene as
   OBJ into that folder. Marvelous Designer writes the companion ``.mtl``
   and copies textures next to the OBJ as part of its native exporter.
3. Appends a manifest entry via :mod:`md_bridge.export_manifest` so the
   downstream Cinema 4D importer (future work) has a single, predictable
   place to read from.

Why so much defensive code
--------------------------
Marvelous Designer's Python Script API is shipped with the application
and is *not* publicly versioned in a stable way. Function names have
varied across releases (``ExportOBJ`` vs ``exportOBJ`` vs
``ExportToOBJ``). The MD-specific calls are isolated below
``# MD API:`` markers so they are easy to find and adjust per MD
version.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# MD API import
# ---------------------------------------------------------------------------
# Marvelous Designer exposes its scripting API through the ``MD`` module
# inside its bundled Python. Importing it from any other Python install
# will fail, which is fine: this script only does real work when run
# from inside MD. Importing it standalone is allowed so editors and
# linters can still read the file.
try:  # pragma: no cover - only importable inside Marvelous Designer
    import MD  # type: ignore[import-not-found]
    _MD_AVAILABLE = True
except ImportError:
    MD = None  # type: ignore[assignment]
    _MD_AVAILABLE = False


# ---------------------------------------------------------------------------
# Bridge package import
# ---------------------------------------------------------------------------
# Make the parent repo importable so we can reuse the manifest writer
# and config loader. Falls back to a tiny inline manifest writer if the
# package is unreachable (e.g. user copied this script outside the repo).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from md_bridge.config import BridgeConfig, load_config
    from md_bridge.export_manifest import record_export

    _BRIDGE_AVAILABLE = True
except Exception:  # noqa: BLE001 - any import failure means standalone mode
    BridgeConfig = None  # type: ignore[assignment,misc]
    load_config = None  # type: ignore[assignment]
    record_export = None  # type: ignore[assignment]
    _BRIDGE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ExportError(RuntimeError):
    """Raised for any expected, user-facing export failure."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_config() -> "BridgeConfig | None":
    """Load ``config.json`` from the repo root if the bridge is available."""
    if not _BRIDGE_AVAILABLE or load_config is None:
        return None
    cfg_path = _REPO_ROOT / "config.json"
    if not cfg_path.exists():
        return None
    try:
        return load_config(cfg_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[md_bridge] warning: could not load config ({exc}); using defaults")
        return None


def _resolve_export_folder(cfg: "BridgeConfig | None") -> Path:
    """Decide where to write the OBJ.

    Order of precedence:
      1. ``MD2C4D_EXPORT_FOLDER`` environment variable.
      2. ``export_folder`` from ``config.json``.
      3. ``<repo_root>/exports``.
    """
    env = os.environ.get("MD2C4D_EXPORT_FOLDER")
    if env:
        return Path(env).expanduser().resolve()
    if cfg is not None:
        return Path(cfg.export_folder).expanduser().resolve()
    return (_REPO_ROOT / "exports").resolve()


def _ensure_folder(folder: Path) -> None:
    """Create the export folder if missing; fail clearly if we cannot."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ExportError(f"Cannot create export folder {folder}: {exc}") from exc
    if not folder.is_dir():
        raise ExportError(f"Export folder is not a directory: {folder}")


def _scene_file_path() -> str | None:
    """Return the open scene's source path, or ``None`` if unknown.

    Used both as a "is anything open?" probe and to derive a default
    garment name. MD's API for this has been renamed across versions so
    we try the known spellings.
    """
    if not _MD_AVAILABLE or MD is None:
        return None
    # MD API: query the path of the currently open scene file. Different
    # MD releases expose this under slightly different names.
    for attr in (
        "GetCurrentSceneFilePath",
        "getCurrentSceneFilePath",
        "GetSceneFilePath",
    ):
        fn = getattr(MD, attr, None)
        if fn is None:
            continue
        try:
            value = fn()
        except Exception:  # noqa: BLE001
            continue
        if value:
            return str(value)
    return None


def _ensure_scene_open() -> None:
    """Verify a scene is open in MD before we try to export it."""
    if not _MD_AVAILABLE:
        raise ExportError(
            "Marvelous Designer Python API not available. "
            "Run this script from inside Marvelous Designer."
        )
    # Best-effort: if MD exposes a scene-path query and it returns
    # nothing we treat that as "no scene open". If no such query exists
    # in this MD version, we let the export call itself surface the
    # error, which is still caught and reported below.
    path = _scene_file_path()
    if path is None:
        return
    if not path.strip():
        raise ExportError("No Marvelous Designer scene is currently open.")


def _default_garment_name() -> str:
    """Pick a sensible name for the OBJ when the caller doesn't supply one."""
    scene = _scene_file_path()
    if scene:
        stem = Path(scene).stem.strip()
        if stem:
            return stem
    return "garment_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _resolve_md_export_callable() -> tuple[str, Callable[..., Any]]:
    """Find an OBJ-export entry point on the ``MD`` module.

    Returns ``(name, callable)``. Raises :class:`ExportError` if no
    plausible entry point exists.
    """
    # MD API: the OBJ export entry point. Names observed in the wild:
    #   MD.ExportOBJ, MD.exportOBJ, MD.ExportObj, MD.exportObj,
    #   MD.ExportToOBJ. We probe in priority order; first hit wins.
    for name in (
        "ExportOBJ",
        "exportOBJ",
        "ExportObj",
        "exportObj",
        "ExportToOBJ",
        "exportToOBJ",
    ):
        fn = getattr(MD, name, None)
        if callable(fn):
            return name, fn
    raise ExportError(
        "No OBJ export function found on the MD module. "
        "Check your Marvelous Designer version's Python API."
    )


def _call_md_export(fn: Callable[..., Any], out_path: Path) -> None:
    """Invoke the MD OBJ export call, tolerating signature variation.

    Most MD versions take just a path; some take ``(path, options)``.
    """
    out_str = str(out_path)
    # MD API: invoke with the simplest signature first.
    try:
        fn(out_str)
        return
    except TypeError:
        pass
    # MD API: some MD builds require an options dict. Empty dict means
    # "use the user's MD preferences for scale and axis"; the bridge
    # records its own scale/axis in the manifest so C4D can re-apply.
    try:
        fn(out_str, {})
        return
    except TypeError as exc:
        raise ExportError(
            f"Could not call MD OBJ exporter with a known signature: {exc}"
        ) from exc


def _try_export_textures(out_path: Path) -> None:
    """Best-effort texture export.

    MD's OBJ exporter normally writes the companion ``.mtl`` and copies
    textures next to the OBJ on its own. If the MD version exposes an
    explicit texture-export call we invoke it as well, but missing
    support is not an error.
    """
    if not _MD_AVAILABLE or MD is None:
        return
    # MD API: optional explicit texture export. Not present in every
    # version — silent fallback to MD's built-in OBJ-side texture copy.
    for name in ("ExportTextures", "exportTextures", "ExportTextureFiles"):
        fn = getattr(MD, name, None)
        if not callable(fn):
            continue
        try:
            fn(str(out_path.parent))
            return
        except Exception as exc:  # noqa: BLE001
            print(f"[md_bridge] {name} failed ({exc}); relying on default OBJ+MTL output")
            return


def _write_inline_manifest(out_path: Path, folder: Path) -> dict[str, Any]:
    """Fallback manifest writer used when the md_bridge package is unreachable."""
    manifest_file = folder / "manifest.json"
    entry: dict[str, Any] = {
        "file": str(out_path),
        "format": "OBJ",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "garment": out_path.stem,
        "textures": [],
        "scale_factor": 1.0,
        "axis_preset": "Y_UP",
    }
    existing: list[dict[str, Any]] = []
    if manifest_file.exists():
        try:
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                existing = data
        except Exception:  # noqa: BLE001
            existing = []
    existing.append(entry)
    manifest_file.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return entry


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def export_obj(garment_name: str | None = None) -> dict[str, Any]:
    """Export the open MD scene as OBJ and append a manifest entry.

    Parameters
    ----------
    garment_name:
        Optional override for the OBJ filename stem. If omitted we use
        the scene's source file name, falling back to a timestamped name.

    Returns
    -------
    dict
        The manifest entry that was appended.
    """
    _ensure_scene_open()

    cfg = _load_config()
    folder = _resolve_export_folder(cfg)
    _ensure_folder(folder)

    name = (garment_name or _default_garment_name()).strip()
    if not name:
        raise ExportError("Garment name is empty.")
    out_path = folder / f"{name}.obj"

    api_name, fn = _resolve_md_export_callable()
    try:
        _call_md_export(fn, out_path)
    except ExportError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ExportError(f"MD.{api_name} failed: {exc}") from exc

    if not out_path.exists():
        raise ExportError(
            f"MD.{api_name} returned without error but no file was written at {out_path}"
        )

    _try_export_textures(out_path)

    if _BRIDGE_AVAILABLE and cfg is not None and record_export is not None:
        return record_export(out_path, cfg)
    return _write_inline_manifest(out_path, folder)


# ---------------------------------------------------------------------------
# Script entry
# ---------------------------------------------------------------------------
def _run() -> int:
    try:
        entry = export_obj()
    except ExportError as exc:
        print(f"[md_bridge] export aborted: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[md_bridge] unexpected error: {exc}")
        traceback.print_exc()
        return 2
    print(f"[md_bridge] exported OBJ: {entry['file']}")
    if entry.get("textures"):
        print(f"[md_bridge] textures: {len(entry['textures'])} file(s)")
    return 0


if __name__ == "__main__":  # pragma: no cover - executed inside MD
    sys.exit(_run())
