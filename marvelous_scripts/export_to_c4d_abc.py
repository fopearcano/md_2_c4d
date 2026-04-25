"""Alembic (ABC) export script for the MD2C4D bridge — placeholder.

Run from inside Marvelous Designer once implemented:

    File -> Python Script -> Run Script -> select this file.

Status
------
**Not implemented yet.** Use ``export_to_c4d_obj.py`` for now.

Implementation notes (for the next iteration)
---------------------------------------------
Alembic is the right choice when we need to bring simulated cloth
animation across into Cinema 4D rather than a single static frame.

1. Mirror the OBJ exporter's scaffolding (config load, folder
   resolution, scene-open check, garment name, manifest append).
2. Swap the MD export call to the Alembic entry point. Names observed
   across MD versions:

       MD.ExportAlembic, MD.exportAlembic, MD.ExportToAlembic

   Alembic export usually requires a frame range. For the first
   iteration we should:
     - Try to query the scene's animation range via the MD API.
     - Fall back to a single-frame export if the range is unavailable.
3. Write the result to ``<export_folder>/<garment>.abc`` and call
   ``md_bridge.export_manifest.record_export`` — ``detect_format``
   already maps ``.abc`` to ``"ABC"``.
4. Alembic does not carry materials. Continue to rely on the manifest's
   texture discovery pass to record any maps MD wrote alongside the
   geometry, and on the future C4D importer to wire them up.
"""

from __future__ import annotations


def export_abc(*_args, **_kwargs):
    raise NotImplementedError(
        "Alembic export is not implemented yet. "
        "Use marvelous_scripts/export_to_c4d_obj.py for now."
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(
        "[md_bridge] Alembic export is not implemented yet. "
        "Use export_to_c4d_obj.py for the time being."
    )
