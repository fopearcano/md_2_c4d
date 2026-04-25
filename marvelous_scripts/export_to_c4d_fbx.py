"""FBX export script for the MD2C4D bridge — placeholder.

Run from inside Marvelous Designer once implemented:

    File -> Python Script -> Run Script -> select this file.

Status
------
**Not implemented yet.** Use ``export_to_c4d_obj.py`` for now.

Implementation notes (for the next iteration)
---------------------------------------------
The structure should mirror the OBJ exporter:

1. Reuse ``_load_config``, ``_resolve_export_folder``, ``_ensure_folder``,
   ``_ensure_scene_open``, ``_default_garment_name`` and the manifest
   plumbing from ``export_to_c4d_obj.py`` (lift them into a small shared
   helper module under ``marvelous_scripts/`` when the second exporter
   lands — premature to extract for a single caller).
2. Replace the ``MD.ExportOBJ`` probe with the FBX entry point. Names
   observed across MD versions:

       MD.ExportFBX, MD.exportFBX, MD.ExportToFBX

   FBX export usually accepts an options dict; defaults from MD's UI
   are typically what we want for a first cut. Bake animation = False
   for static garments.
3. Write the result to ``<export_folder>/<garment>.fbx`` and call
   ``md_bridge.export_manifest.record_export`` — its
   ``detect_format`` helper already maps ``.fbx`` to ``"FBX"``.
4. FBX embeds materials, so explicit texture-export calls are usually
   unnecessary. The manifest's ``find_textures`` pass will still pick
   up sidecar maps if MD wrote any.
"""

from __future__ import annotations


def export_fbx(*_args, **_kwargs):
    raise NotImplementedError(
        "FBX export is not implemented yet. "
        "Use marvelous_scripts/export_to_c4d_obj.py for now."
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(
        "[md_bridge] FBX export is not implemented yet. "
        "Use export_to_c4d_obj.py for the time being."
    )
