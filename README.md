# MD2C4D Bridge

A small Python-based bridge for moving garments and models from
**Marvelous Designer** into **Cinema 4D**.

## Purpose

Marvelous Designer (MD) exports geometry as `OBJ`, `FBX`, or `Alembic`,
and Cinema 4D (C4D) can import all three formats. There is no public
live-link between the two applications, so production teams typically
move files by hand and re-key scale, axis orientation, and texture
paths on every round-trip.

This repository is the first minimal version of an automation layer
that sits *between* the two tools. It does **not** attempt a real-time
link. Instead it:

1. Watches a known export folder for new MD output.
2. Records every export in a JSON manifest with timestamp, format,
   garment name, scale, axis preset, and any texture files found
   alongside the geometry.
3. Provides a small CLI so the rest of the pipeline (or a future C4D
   importer script) has a single, predictable place to read from.

## Status

MVP. Only the export-side scaffolding is implemented:

- Config loader (`config.json`).
- Manifest writer.
- Folder watcher (polling, no extra dependencies).
- Utility helpers (texture discovery, hashing, timestamps).
- CLI: `init`, `watch`, `write-manifest <file>`.

The C4D-side importer is intentionally *not* in this version.

## Layout

```
md_2_c4d/
├── README.md
├── config.json
├── md_bridge/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── export_manifest.py
│   ├── file_watcher.py
│   └── utils.py
└── marvelous_scripts/
    ├── export_to_c4d_obj.py    # implemented
    ├── export_to_c4d_fbx.py    # placeholder
    └── export_to_c4d_abc.py    # placeholder
```

## Marvelous Designer scripts

`marvelous_scripts/export_to_c4d_obj.py` is meant to be run from inside
Marvelous Designer (`File -> Python Script -> Run Script`). It reads
the same `config.json` used by the CLI, calls the MD Python API to
export the open scene as OBJ into `export_folder`, then appends an
entry to `manifest.json` via `md_bridge.export_manifest`.

The FBX and ABC scripts are deliberate placeholders for now. See the
docstring of each file for the implementation plan.

## Configuration

`config.json` (created/refreshed by `python -m md_bridge init`):

| Key              | Meaning                                              |
| ---------------- | ---------------------------------------------------- |
| `export_folder`  | Directory MD writes exports into.                    |
| `default_format` | One of `OBJ`, `FBX`, `ABC`.                          |
| `scale_factor`   | Multiplier applied on the C4D side (e.g. `1.0`).     |
| `axis_preset`    | Axis convention name, e.g. `Y_UP` or `Z_UP`.         |
| `texture_folder` | Directory to scan for textures next to each export.  |

## CLI

```
python -m md_bridge init
python -m md_bridge watch
python -m md_bridge write-manifest <file>
```

- `init` — creates `config.json` with sensible defaults if missing.
- `watch` — polls `export_folder` and writes a manifest entry for each
  new `OBJ` / `FBX` / `ABC` file.
- `write-manifest <file>` — writes a manifest entry for one specific
  exported file (useful from a post-export hook in MD).

Manifests are written to `<export_folder>/manifest.json` as a JSON
array of entries. Each entry contains the exported file path, format,
timestamp, garment name, texture paths, and scale/axis metadata.
