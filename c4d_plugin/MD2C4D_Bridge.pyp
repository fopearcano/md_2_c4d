"""MD2C4D Bridge — Cinema 4D import command.

A minimal Cinema 4D plugin that registers the *Import Latest MD Export*
menu command. It delegates manifest parsing, validation, and "newest
valid entry" selection to :mod:`md_bridge.export_resolver`, then loads
the resolved file into the active Cinema 4D document under a single
parent null whose transform encodes the bridge's scale and axis
correction.

The work is split into three small, testable steps:

* :func:`resolve_latest_export` — wrap the bridge's resolver, return a
  ``ResolvedExport``.
* :func:`import_export_file` — load an OBJ/FBX/ABC file into a temp
  Cinema 4D document and detach its top-level objects + materials.
* :func:`parent_imported_objects` — create the ``MD2C4D_<garment>``
  null, attach the imported items under it, and apply scale + axis.

Refresh / replace behaviour for an already-imported garment is
**not** in this version; running the command always inserts a fresh
import.

Install
-------
See ``README_C4D_INSTALL.md`` next to this file.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

import c4d
from c4d import documents, gui, plugins, utils


# ---------------------------------------------------------------------------
# Plugin identity
# ---------------------------------------------------------------------------
# NOTE: 1066666 is a development placeholder. Before shipping, replace it
# with a unique plugin ID issued by Maxon at https://plugincafe.maxon.net/
# to avoid collisions with other third-party plugins.
PLUGIN_ID = 1066666
PLUGIN_NAME = "Import Latest MD Export"
PLUGIN_HELP = "Import the most recent Marvelous Designer export listed in manifest.json."


# ---------------------------------------------------------------------------
# Errors + logging
# ---------------------------------------------------------------------------
class BridgeError(RuntimeError):
    """Raised for any expected, user-facing failure during import."""


def log(msg: str) -> None:
    """Write to Cinema 4D's Python console with a consistent prefix."""
    print(f"[MD2C4D] {msg}")


# ---------------------------------------------------------------------------
# Bridge-package bootstrap
# ---------------------------------------------------------------------------
# The plugin imports ``md_bridge.*`` from the bridge repo. We add the
# repo root to ``sys.path`` at module import time so the regular
# ``from md_bridge...`` lines below work. Resolution order matches the
# previous plugin: env var -> plugin's parent dir -> cwd.
def _candidate_repo_roots() -> list[Path]:
    roots: list[Path] = []
    env = os.environ.get("MD2C4D_REPO_ROOT")
    if env:
        roots.append(Path(env).expanduser())
    here = Path(__file__).resolve().parent
    roots.append(here.parent)  # <repo>/c4d_plugin/.. == <repo>
    roots.append(here)
    roots.append(Path.cwd())
    return roots


def _bootstrap_repo_root() -> Path | None:
    for cand in _candidate_repo_roots():
        if (cand / "config.json").exists() and (cand / "md_bridge").is_dir():
            s = str(cand.resolve())
            if s not in sys.path:
                sys.path.insert(0, s)
            return cand.resolve()
    return None


_REPO_ROOT: Path | None = _bootstrap_repo_root()

try:
    from md_bridge.config import load_config  # type: ignore[import-not-found]
    from md_bridge.export_resolver import (  # type: ignore[import-not-found]
        ResolvedExport,
        ResolverError,
        resolve_latest,
    )

    _BRIDGE_OK = True
    _BRIDGE_IMPORT_ERROR: Exception | None = None
except Exception as _exc:  # noqa: BLE001 - any failure means we run in degraded mode
    ResolvedExport = None  # type: ignore[assignment,misc]
    ResolverError = Exception  # type: ignore[assignment,misc]
    load_config = None  # type: ignore[assignment]
    resolve_latest = None  # type: ignore[assignment]
    _BRIDGE_OK = False
    _BRIDGE_IMPORT_ERROR = _exc


# ---------------------------------------------------------------------------
# 1) resolve_latest_export
# ---------------------------------------------------------------------------
def resolve_latest_export() -> "ResolvedExport":
    """Return the newest valid export described by the bridge manifest.

    Wraps :func:`md_bridge.export_resolver.resolve_latest`, surfacing a
    single :class:`BridgeError` so callers only need to handle one
    exception type.
    """
    if not _BRIDGE_OK:
        raise BridgeError(
            f"md_bridge package is not importable: {_BRIDGE_IMPORT_ERROR}. "
            "Install the plugin inside the bridge repo (so it lives at "
            "<repo>/c4d_plugin/) or set the MD2C4D_REPO_ROOT environment "
            "variable to the repo path."
        )
    if _REPO_ROOT is None:
        raise BridgeError(
            "config.json not found. Set MD2C4D_REPO_ROOT, or place the "
            "plugin inside the bridge repo's c4d_plugin/ folder."
        )

    cfg_path = _REPO_ROOT / "config.json"
    try:
        cfg = load_config(cfg_path)
    except FileNotFoundError as exc:
        raise BridgeError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise BridgeError(f"Cannot read {cfg_path}: {exc}") from exc

    try:
        return resolve_latest(cfg)
    except ResolverError as exc:
        raise BridgeError(str(exc)) from exc


# ---------------------------------------------------------------------------
# 2) import_export_file
# ---------------------------------------------------------------------------
def _drain_top_objects(src_doc) -> list:
    out: list = []
    obj = src_doc.GetFirstObject()
    while obj is not None:
        nxt = obj.GetNext()
        obj.Remove()
        out.append(obj)
        obj = nxt
    return out


def _drain_materials(src_doc) -> list:
    out: list = []
    mat = src_doc.GetFirstMaterial()
    while mat is not None:
        nxt = mat.GetNext()
        mat.Remove()
        out.append(mat)
        mat = nxt
    return out


def _load_file_into_temp_doc(file_path: Path):
    """Load an OBJ / FBX / ABC into a fresh BaseDocument."""
    if not file_path.exists():
        raise BridgeError(f"Export file does not exist: {file_path}")
    # C4D API: LoadDocument auto-detects format from extension via the
    # registered scene-loader plugins. Returns None on failure.
    temp = documents.LoadDocument(
        str(file_path),
        c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS,
    )
    if temp is None:
        raise BridgeError(f"Cinema 4D failed to load {file_path}")
    return temp


def import_export_file(file_path: Path, fmt: str) -> tuple[list, list]:
    """Load a Marvelous Designer export and return ``(objects, materials)``.

    The returned objects and materials are detached from the temporary
    document so the caller can re-parent them. Today only OBJ is fully
    wired up; FBX and Alembic are explicit TODO stubs that raise
    :class:`BridgeError` when invoked.
    """
    fmt_norm = (fmt or "").upper()

    if fmt_norm == "OBJ":
        temp = _load_file_into_temp_doc(file_path)
        objs = _drain_top_objects(temp)
        mats = _drain_materials(temp)
        if not objs:
            raise BridgeError(f"OBJ {file_path.name} contained no objects.")
        log(f"OBJ load: {len(objs)} top-level object(s), {len(mats)} material(s)")
        return objs, mats

    if fmt_norm == "FBX":
        # TODO: FBX import. LoadDocument will read the file; the open
        # question is what to do with FBX-only payloads (cameras,
        # lights, embedded animation) before they pollute the active
        # scene.
        raise BridgeError("FBX import is not implemented yet (TODO).")

    if fmt_norm == "ABC":
        # TODO: Alembic import. For animated cloth caches we likely
        # want to wire the file up via c4d.Oalembicgenerator instead
        # of baking geometry into the scene.
        raise BridgeError("Alembic import is not implemented yet (TODO).")

    raise BridgeError(f"Unsupported format: {fmt!r}")


# ---------------------------------------------------------------------------
# 3) parent_imported_objects
# ---------------------------------------------------------------------------
def _make_parent_null(garment: str, scale: float, axis: str):
    null = c4d.BaseObject(c4d.Onull)
    null.SetName(f"MD2C4D_{garment}")

    if scale and scale > 0 and scale != 1.0:
        null.SetRelScale(c4d.Vector(scale, scale, scale))

    # Axis preset: only Y_UP and Z_UP are defined in the bridge config.
    # MD's native frame is Y_UP; Cinema 4D is Y_UP. For Z_UP we apply
    # a -90 deg rotation about X (Pitch) on the parent null so a
    # single transform corrects the whole import.
    axis_norm = (axis or "Y_UP").upper()
    if axis_norm == "Z_UP":
        null.SetRelRot(c4d.Vector(0.0, utils.DegToRad(-90.0), 0.0))
    elif axis_norm != "Y_UP":
        log(f"warning: unknown axis_preset {axis!r}, leaving rotation at identity")

    return null


def parent_imported_objects(
    doc,
    objs: list,
    mats: list,
    *,
    garment: str,
    scale: float,
    axis: str,
):
    """Create the ``MD2C4D_<garment>`` null and attach imported items.

    All inserts are wrapped in a single ``StartUndo``/``EndUndo`` block
    so a single ``Ctrl+Z`` reverses the entire import. Returns the
    parent null.
    """
    null = _make_parent_null(garment, scale, axis)

    doc.StartUndo()
    try:
        # C4D API: insert objects/materials, then register them with
        # the undo stack using UNDOTYPE_NEW.
        doc.InsertObject(null)
        doc.AddUndo(c4d.UNDOTYPE_NEW, null)

        for obj in objs:
            obj.InsertUnder(null)
            doc.AddUndo(c4d.UNDOTYPE_NEW, obj)

        for mat in mats:
            doc.InsertMaterial(mat)
            doc.AddUndo(c4d.UNDOTYPE_NEW, mat)
    finally:
        doc.EndUndo()

    return null


# ---------------------------------------------------------------------------
# Material repair (best-effort, kept from the previous version)
# ---------------------------------------------------------------------------
def _bitmap_filename(shader) -> str:
    if shader is None:
        return ""
    if shader.GetType() != c4d.Xbitmap:
        return ""
    return shader[c4d.BITMAPSHADER_FILENAME] or ""


def _find_matching_texture(name: str, textures: list[str]) -> str | None:
    name_low = name.lower()
    for t in textures:
        stem = Path(t).stem.lower()
        if stem == name_low or name_low in stem or stem in name_low:
            return t
    return None


def _make_basic_material(name: str, texture_path: str):
    mat = c4d.BaseMaterial(c4d.Mmaterial)
    mat.SetName(name)
    shader = c4d.BaseShader(c4d.Xbitmap)
    shader[c4d.BITMAPSHADER_FILENAME] = texture_path
    mat.InsertShader(shader)
    mat[c4d.MATERIAL_COLOR_SHADER] = shader
    mat.Update(True, True)
    return mat


def _assign_material(obj, mat) -> None:
    tag = obj.MakeTag(c4d.Ttexture)
    tag[c4d.TEXTURETAG_MATERIAL] = mat
    tag[c4d.TEXTURETAG_PROJECTION] = c4d.TEXTURETAG_PROJECTION_UVW


def _repair_or_create_materials(
    doc,
    mats: list,
    target_objects: list,
    texture_paths: list[str],
) -> tuple[int, int]:
    """Patch broken texture paths and synthesise fallback materials.

    Returns ``(repaired_count, created_count)``.
    """
    repaired = 0
    created = 0

    for mat in mats:
        if mat.GetType() != c4d.Mmaterial:
            continue
        shader = mat[c4d.MATERIAL_COLOR_SHADER]
        path = _bitmap_filename(shader)
        if path and Path(path).exists():
            continue
        match = _find_matching_texture(mat.GetName(), texture_paths)
        if not match:
            continue
        if shader is not None and shader.GetType() == c4d.Xbitmap:
            shader[c4d.BITMAPSHADER_FILENAME] = match
        else:
            new_shader = c4d.BaseShader(c4d.Xbitmap)
            new_shader[c4d.BITMAPSHADER_FILENAME] = match
            mat.InsertShader(new_shader)
            mat[c4d.MATERIAL_COLOR_SHADER] = new_shader
        mat.Update(True, True)
        repaired += 1

    if not mats and texture_paths and target_objects:
        for tex in texture_paths:
            mat = _make_basic_material(Path(tex).stem or "MD2C4D_tex", tex)
            doc.InsertMaterial(mat)
            doc.AddUndo(c4d.UNDOTYPE_NEW, mat)
            mats.append(mat)
            created += 1
        primary = mats[0]
        for obj in target_objects:
            _assign_material(obj, primary)

    return repaired, created


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------
def run_import(doc) -> None:
    export = resolve_latest_export()
    log(f"resolved: {export.format} '{export.garment}' @ {export.timestamp}")
    log(f"file: {export.file}")
    if export.textures_missing:
        log(f"warning: {export.textures_missing} manifest texture(s) missing on disk")

    objs, mats = import_export_file(export.file, export.format)

    null = parent_imported_objects(
        doc,
        objs,
        mats,
        garment=export.garment,
        scale=export.scale_factor,
        axis=export.axis_preset,
    )
    log(
        f"created parent null: {null.GetName()} "
        f"(scale={export.scale_factor}, axis={export.axis_preset})"
    )

    texture_strings = [str(p) for p in export.textures]
    repaired, created = _repair_or_create_materials(doc, mats, objs, texture_strings)
    if repaired:
        log(f"repaired {repaired} material texture path(s)")
    if created:
        log(f"created {created} fallback material(s) from manifest textures")

    # C4D API: refresh viewport / Object Manager so the user sees the result.
    c4d.EventAdd()
    log("import complete")


# ---------------------------------------------------------------------------
# Plugin command
# ---------------------------------------------------------------------------
class ImportLatestCommand(plugins.CommandData):
    """Menu command entry point — *Import Latest MD Export*."""

    def Execute(self, doc):  # noqa: N802 - C4D API name
        try:
            run_import(doc)
        except BridgeError as exc:
            # Expected user-facing failure: log + dialog, no traceback.
            log(f"aborted: {exc}")
            gui.MessageDialog(f"MD2C4D Bridge:\n\n{exc}")
            return False
        except Exception as exc:  # noqa: BLE001 - never let C4D crash on us
            log(f"unexpected error: {exc}")
            traceback.print_exc()
            gui.MessageDialog(
                "MD2C4D Bridge: unexpected error\n\n"
                f"{exc}\n\nSee the Python console for the full traceback."
            )
            return False
        return True

    def GetState(self, doc):  # noqa: N802 - C4D API name
        return c4d.CMD_ENABLED


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def _register() -> None:
    ok = plugins.RegisterCommandPlugin(
        id=PLUGIN_ID,
        str=PLUGIN_NAME,
        info=0,
        help=PLUGIN_HELP,
        dat=ImportLatestCommand(),
        icon=None,
    )
    if ok:
        log(f"registered command plugin {PLUGIN_ID}: {PLUGIN_NAME}")
        if not _BRIDGE_OK:
            log(
                f"warning: md_bridge import failed at startup ({_BRIDGE_IMPORT_ERROR}); "
                "the command will fail until the repo is reachable."
            )
    else:
        log(f"FAILED to register command plugin {PLUGIN_ID}")


if __name__ == "__main__":
    _register()
