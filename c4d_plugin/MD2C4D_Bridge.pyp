"""MD2C4D Bridge — Cinema 4D import command.

A minimal Cinema 4D plugin that reads the bridge ``config.json`` and
the export-folder ``manifest.json`` produced by the MD-side scripts,
then imports the most recent Marvelous Designer export into the active
Cinema 4D document.

What it does on each invocation
-------------------------------
1. Locates ``config.json`` (env var ``MD2C4D_REPO_ROOT`` -> plugin's
   parent dir -> CWD).
2. Reads ``<export_folder>/manifest.json`` and picks the entry with
   the most recent timestamp.
3. Loads that geometry file into a temporary Cinema 4D document
   (OBJ today; FBX/Alembic are TODO stubs).
4. Creates a parent null named ``MD2C4D_<garment>`` in the active doc.
5. Re-parents the imported objects under the null and copies the
   imported materials across.
6. Applies ``scale_factor`` and ``axis_preset`` from the manifest entry
   to the parent null so a single transform governs the whole import.
7. Tries to repair material texture paths from the manifest's
   ``textures`` list; if no materials were imported but textures exist,
   creates basic standard materials and assigns the first to the
   imported meshes.
8. Logs every step to the Cinema 4D Python console.

Install
-------
See ``README_C4D_INSTALL.md`` next to this file.
"""

from __future__ import annotations

import json
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
PLUGIN_NAME = "MD2C4D Bridge: Import Latest"
PLUGIN_HELP = "Import the most recent Marvelous Designer export listed in manifest.json."


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class BridgeError(RuntimeError):
    """Raised for any expected, user-facing failure during import."""


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    """Write to Cinema 4D's Python console with a consistent prefix."""
    print(f"[MD2C4D] {msg}")


# ---------------------------------------------------------------------------
# Config + manifest
# ---------------------------------------------------------------------------
def _candidate_repo_roots() -> list[Path]:
    """Possible locations for the bridge repo, in priority order."""
    roots: list[Path] = []
    env = os.environ.get("MD2C4D_REPO_ROOT")
    if env:
        roots.append(Path(env).expanduser())
    # The .pyp typically lives at <repo>/c4d_plugin/MD2C4D_Bridge.pyp,
    # so the repo root is two levels up from this file.
    here = Path(__file__).resolve().parent
    roots.append(here.parent)
    roots.append(here)
    roots.append(Path.cwd())
    return roots


def _find_repo_root() -> Path:
    for cand in _candidate_repo_roots():
        if (cand / "config.json").exists():
            return cand.resolve()
    raise BridgeError(
        "config.json not found. Set MD2C4D_REPO_ROOT or place the plugin "
        "inside the bridge repo's c4d_plugin/ folder."
    )


def _load_config(root: Path) -> dict:
    cfg_path = root / "config.json"
    try:
        with cfg_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as exc:
        raise BridgeError(f"Cannot read {cfg_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BridgeError(f"{cfg_path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise BridgeError(f"{cfg_path} must contain a JSON object")
    return data


def _resolve_export_folder(cfg: dict, root: Path) -> Path:
    raw = cfg.get("export_folder", "./exports")
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = root / p
    return p.resolve()


def _load_latest_entry(export_folder: Path) -> dict:
    manifest = export_folder / "manifest.json"
    if not manifest.exists():
        raise BridgeError(f"manifest.json not found at {manifest}")
    try:
        with manifest.open("r", encoding="utf-8") as fh:
            entries = json.load(fh)
    except json.JSONDecodeError as exc:
        raise BridgeError(f"{manifest} is not valid JSON: {exc}") from exc
    if not isinstance(entries, list) or not entries:
        raise BridgeError(f"{manifest} is empty — nothing to import")
    try:
        latest = max(entries, key=lambda e: str(e.get("timestamp", "")))
    except Exception:  # noqa: BLE001
        latest = entries[-1]
    if not isinstance(latest, dict) or "file" not in latest:
        raise BridgeError("Latest manifest entry is malformed (missing 'file').")
    return latest


# ---------------------------------------------------------------------------
# Geometry import
# ---------------------------------------------------------------------------
def _load_into_temp_doc(file_path: Path) -> "c4d.documents.BaseDocument":
    """Load a file into a fresh document so we can inspect what came in.

    Cinema 4D's scene-loader chain auto-detects format from the path
    extension, so OBJ, FBX and Alembic all flow through the same call.
    """
    if not file_path.exists():
        raise BridgeError(f"Export file does not exist: {file_path}")
    # C4D API: LoadDocument returns a new BaseDocument, or None on failure.
    temp = documents.LoadDocument(str(file_path), c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS)
    if temp is None:
        raise BridgeError(f"Cinema 4D failed to load {file_path}")
    return temp


def _drain_top_objects(src_doc) -> list:
    """Detach and return every top-level object from ``src_doc``."""
    out: list = []
    obj = src_doc.GetFirstObject()
    while obj is not None:
        nxt = obj.GetNext()
        obj.Remove()
        out.append(obj)
        obj = nxt
    return out


def _drain_materials(src_doc) -> list:
    """Detach and return every material from ``src_doc``."""
    out: list = []
    mat = src_doc.GetFirstMaterial()
    while mat is not None:
        nxt = mat.GetNext()
        mat.Remove()
        out.append(mat)
        mat = nxt
    return out


def import_obj(file_path: Path) -> tuple[list, list]:
    """Load an OBJ and return ``(top_objects, materials)`` detached from
    the temporary document so the caller can re-parent them."""
    temp = _load_into_temp_doc(file_path)
    objs = _drain_top_objects(temp)
    mats = _drain_materials(temp)
    if not objs:
        raise BridgeError(f"OBJ {file_path.name} contained no objects.")
    log(f"OBJ load: {len(objs)} top-level object(s), {len(mats)} material(s)")
    return objs, mats


def import_fbx(file_path: Path) -> tuple[list, list]:
    """TODO: FBX import.

    Implementation sketch: identical to :func:`import_obj` — Cinema 4D's
    scene loader handles ``.fbx`` natively via the same ``LoadDocument``
    call. The work here is *post*-import: deciding what to do with FBX-
    specific extras (cameras, lights, embedded animation) so we don't
    silently dump them into the active scene. Until that policy is
    settled this stays a stub.
    """
    raise BridgeError("FBX import is not implemented yet (TODO).")


def import_abc(file_path: Path) -> tuple[list, list]:
    """TODO: Alembic import.

    Implementation sketch: ``LoadDocument`` will read the ABC, but for
    cloth caches we usually want to wire the result up as an Alembic
    Generator (``c4d.Oalembicgenerator``) pointing at the file rather
    than baking geometry into the scene. That behaviour deserves its
    own pass; until then this is a stub.
    """
    raise BridgeError("Alembic import is not implemented yet (TODO).")


FORMAT_DISPATCH = {
    "OBJ": import_obj,
    "FBX": import_fbx,
    "ABC": import_abc,
}


# ---------------------------------------------------------------------------
# Scene assembly
# ---------------------------------------------------------------------------
def _make_parent_null(garment: str, scale: float, axis: str) -> "c4d.BaseObject":
    """Create the ``MD2C4D_<garment>`` null with scale + axis applied."""
    null = c4d.BaseObject(c4d.Onull)
    null.SetName(f"MD2C4D_{garment}")

    if scale and scale > 0 and scale != 1.0:
        null.SetRelScale(c4d.Vector(scale, scale, scale))

    # Axis preset: only Y_UP and Z_UP are defined in the bridge config.
    # MD's native frame is Y_UP; Cinema 4D is Y_UP. For Z_UP we apply a
    # -90 deg rotation about X (Pitch) on the parent null so a single
    # transform corrects the whole import.
    axis_norm = (axis or "Y_UP").upper()
    if axis_norm == "Z_UP":
        null.SetRelRot(c4d.Vector(0.0, utils.DegToRad(-90.0), 0.0))
    elif axis_norm != "Y_UP":
        log(f"warning: unknown axis_preset {axis!r}, leaving rotation at identity")

    return null


def _attach_imported(doc, null, objs: list, mats: list) -> None:
    """Insert null + imported items into ``doc`` with undo support."""
    doc.StartUndo()
    try:
        # C4D API: insert objects/materials, then register them with the
        # undo stack using UNDOTYPE_NEW so a single Ctrl+Z reverses the
        # whole import.
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


# ---------------------------------------------------------------------------
# Material repair
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


def _make_basic_material(name: str, texture_path: str) -> "c4d.BaseMaterial":
    """Build a minimal standard material with a bitmap in the colour channel."""
    mat = c4d.BaseMaterial(c4d.Mmaterial)
    mat.SetName(name)
    shader = c4d.BaseShader(c4d.Xbitmap)
    shader[c4d.BITMAPSHADER_FILENAME] = texture_path
    mat.InsertShader(shader)
    mat[c4d.MATERIAL_COLOR_SHADER] = shader
    mat.Update(True, True)
    return mat


def _assign_material(obj, mat) -> None:
    """Drop a Texture Tag onto ``obj`` using UVW projection."""
    tag = obj.MakeTag(c4d.Ttexture)
    tag[c4d.TEXTURETAG_MATERIAL] = mat
    tag[c4d.TEXTURETAG_PROJECTION] = c4d.TEXTURETAG_PROJECTION_UVW


def repair_or_create_materials(
    doc,
    mats: list,
    target_objects: list,
    manifest_entry: dict,
) -> tuple[int, int]:
    """Patch broken texture paths and synthesise fallback materials.

    Returns ``(repaired_count, created_count)`` for logging.
    """
    textures = [t for t in manifest_entry.get("textures", []) if isinstance(t, str)]
    repaired = 0
    created = 0

    # Pass 1: repair any standard material whose colour-channel bitmap
    # points at a missing file by swapping in a manifest-listed texture
    # whose stem matches the material name.
    for mat in mats:
        if mat.GetType() != c4d.Mmaterial:
            continue
        shader = mat[c4d.MATERIAL_COLOR_SHADER]
        path = _bitmap_filename(shader)
        if path and Path(path).exists():
            continue
        match = _find_matching_texture(mat.GetName(), textures)
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

    # Pass 2: if the import produced zero materials but the manifest
    # lists textures, build basic materials and tag them onto every
    # imported top-level object so the user sees something rendered.
    if not mats and textures and target_objects:
        for tex in textures:
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
    root = _find_repo_root()
    log(f"repo root: {root}")

    cfg = _load_config(root)
    export_folder = _resolve_export_folder(cfg, root)
    log(f"export folder: {export_folder}")

    entry = _load_latest_entry(export_folder)
    fmt = str(entry.get("format", "")).upper()
    garment = str(entry.get("garment") or Path(entry["file"]).stem)
    scale = float(entry.get("scale_factor", cfg.get("scale_factor", 1.0)))
    axis = str(entry.get("axis_preset", cfg.get("axis_preset", "Y_UP")))

    file_path = Path(entry["file"])
    if not file_path.is_absolute():
        file_path = (export_folder / file_path).resolve()

    log(f"importing {fmt} '{garment}' from {file_path}")

    importer = FORMAT_DISPATCH.get(fmt)
    if importer is None:
        raise BridgeError(f"Unsupported format in manifest: {fmt!r}")

    objs, mats = importer(file_path)

    null = _make_parent_null(garment, scale, axis)
    _attach_imported(doc, null, objs, mats)
    log(f"created parent null: {null.GetName()} (scale={scale}, axis={axis})")

    repaired, created = repair_or_create_materials(doc, mats, objs, entry)
    if repaired:
        log(f"repaired {repaired} material texture path(s)")
    if created:
        log(f"created {created} fallback material(s) from manifest textures")

    # C4D API: refresh viewport/Object Manager so the user sees the result.
    c4d.EventAdd()
    log("import complete")


# ---------------------------------------------------------------------------
# Plugin command
# ---------------------------------------------------------------------------
class ImportLatestCommand(plugins.CommandData):
    """Menu command entry point."""

    def Execute(self, doc):  # noqa: N802 - C4D API name
        try:
            run_import(doc)
        except BridgeError as exc:
            log(f"aborted: {exc}")
            gui.MessageDialog(f"MD2C4D Bridge:\n\n{exc}")
            return False
        except Exception as exc:  # noqa: BLE001
            log(f"unexpected error: {exc}")
            traceback.print_exc()
            gui.MessageDialog(f"MD2C4D Bridge: unexpected error\n\n{exc}")
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
        print(f"[MD2C4D] registered command plugin {PLUGIN_ID}: {PLUGIN_NAME}")
    else:
        print(f"[MD2C4D] FAILED to register command plugin {PLUGIN_ID}")


if __name__ == "__main__":
    _register()
