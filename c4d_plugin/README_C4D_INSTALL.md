# MD2C4D Bridge — Cinema 4D Plugin Installation

This plugin adds an **MD2C4D Bridge: Import Latest** command to Cinema
4D's *Extensions* menu. Running it imports the most recent Marvelous
Designer export listed in the bridge's `manifest.json`, parents it
under a `MD2C4D_<garment>` null, applies the configured scale and axis
preset, and repairs material texture paths from the manifest where
possible.

## Compatibility

Cinema 4D R23 or newer (any release that ships Python 3 in the C4D
Python API). The plugin only uses public `c4d` and `c4d.documents`
APIs — no GeListNode internals, no symbols from `c4d.modules.*`.

## Layout you should end up with

The plugin assumes it lives **inside the bridge repo** so it can
locate `config.json` and `manifest.json` relative to its own path:

```
md_2_c4d/                           <-- repo root, contains config.json
├── config.json
├── md_bridge/
├── marvelous_scripts/
└── c4d_plugin/                     <-- this folder
    ├── MD2C4D_Bridge.pyp
    ├── README_C4D_INSTALL.md
    └── res/
```

## Install options

Pick **one** of the following.

### A. Symlink the `c4d_plugin/` folder into Cinema 4D's plugin path (recommended)

This keeps the plugin in version control and lets the `.pyp` import
the bridge files in place — no copies, no path env var.

Cinema 4D scans these folders for plugins (paths shown for R26+; older
versions use `MAXON` instead of `Maxon`):

| Platform | Per-user plugin folder                                                                      |
| -------- | ------------------------------------------------------------------------------------------- |
| macOS    | `~/Library/Preferences/Maxon/Maxon Cinema 4D <version>_<hash>/plugins/`                     |
| Windows  | `%APPDATA%\Maxon\Maxon Cinema 4D <version>_<hash>\plugins\`                                 |
| Linux    | `~/.config/Maxon/Maxon Cinema 4D <version>_<hash>/plugins/`                                 |

You can find the exact path inside Cinema 4D under
*Edit -> Preferences -> Open Preferences Folder*.

Create a symlink there pointing at this `c4d_plugin/` folder:

```bash
# macOS / Linux
ln -s /absolute/path/to/md_2_c4d/c4d_plugin \
      "$HOME/.config/Maxon/Maxon Cinema 4D 2025_XXXXXXXX/plugins/MD2C4D_Bridge"
```

```powershell
# Windows (run from an elevated terminal)
mklink /D "%APPDATA%\Maxon\Maxon Cinema 4D 2025_XXXXXXXX\plugins\MD2C4D_Bridge" ^
          "C:\path\to\md_2_c4d\c4d_plugin"
```

Restart Cinema 4D. The command appears under
*Extensions -> MD2C4D Bridge: Import Latest*.

### B. Copy the plugin and point it at the repo via env var

If you cannot symlink (locked-down studio install, etc.), copy
`c4d_plugin/` into the plugin folder under any name, then set
`MD2C4D_REPO_ROOT` to the repo path before launching Cinema 4D:

```bash
# macOS / Linux
export MD2C4D_REPO_ROOT="/absolute/path/to/md_2_c4d"
"/Applications/Maxon Cinema 4D 2025/Cinema 4D.app/Contents/MacOS/Cinema 4D"
```

```powershell
# Windows
setx MD2C4D_REPO_ROOT "C:\path\to\md_2_c4d"
# then launch Cinema 4D normally
```

The plugin's repo-root resolution order is:

1. `MD2C4D_REPO_ROOT` environment variable.
2. The directory two levels above the `.pyp` file (i.e. the parent of
   `c4d_plugin/`).
3. The current working directory.

It uses the first one that contains a `config.json`.

## Verifying the install

1. Open Cinema 4D and check the **Extensions** menu for
   *MD2C4D Bridge: Import Latest*. If it is missing:
   - Open *Script -> Console* (or *Extensions -> Console*).
   - Look for `[MD2C4D] registered command plugin ...`. If you see
     `FAILED to register`, another plugin is using the same plugin ID
     (1066666). Edit `PLUGIN_ID` in `MD2C4D_Bridge.pyp` and restart.
2. Run `python -m md_bridge init` from the repo (creates
   `config.json`).
3. Export an OBJ from Marvelous Designer with
   `marvelous_scripts/export_to_c4d_obj.py`, or drop a hand-made OBJ
   into `<export_folder>` and run `python -m md_bridge write-manifest
   <file>`.
4. Click *Extensions -> MD2C4D Bridge: Import Latest*.
5. Check the Python console — you should see lines like:

   ```
   [MD2C4D] repo root: /path/to/md_2_c4d
   [MD2C4D] export folder: /path/to/md_2_c4d/exports
   [MD2C4D] importing OBJ 'jacket' from /.../jacket.obj
   [MD2C4D] OBJ load: 1 top-level object(s), 1 material(s)
   [MD2C4D] created parent null: MD2C4D_jacket (scale=1.0, axis=Y_UP)
   [MD2C4D] import complete
   ```

## What the command does

| Step                  | Detail                                                          |
| --------------------- | --------------------------------------------------------------- |
| Read config           | `MD2C4D_REPO_ROOT` -> plugin-parent dir -> CWD.                 |
| Pick latest export    | Entry with the largest `timestamp` field in `manifest.json`.    |
| Load geometry         | OBJ via `c4d.documents.LoadDocument` into a temp doc.           |
| Create parent null    | Named `MD2C4D_<garment>`, inserted in the active document.      |
| Apply scale           | Uniform `scale_factor` from manifest entry on the parent null.  |
| Apply axis preset     | `Y_UP` = identity; `Z_UP` = -90 deg pitch on parent null.       |
| Re-parent meshes      | All top-level objects from the temp doc become children.        |
| Move materials        | All temp-doc materials inserted into the active document.       |
| Repair materials      | Standard materials with broken bitmap paths fixed from manifest |
|                       | textures by name match.                                         |
| Synthesise materials  | If no materials but the manifest lists textures, build basic    |
|                       | materials and tag them onto imported meshes.                    |
| Undo                  | The whole import is one undo step (Ctrl+Z reverses it).         |

## Known limitations (intentional, MVP)

- **OBJ only.** `import_fbx` and `import_abc` are clearly marked
  TODO stubs that raise an error if the latest manifest entry's
  `format` is `FBX` or `ABC`.
- **No UI.** The command runs with no dialog and no parameters; all
  knobs come from `config.json` and the manifest.
- **No live link.** Each invocation pulls the most recent manifest
  entry; there is no file watcher or push-from-MD path on the C4D side.
- **Standard material only.** Material repair only touches the
  classic `Mmaterial`. Redshift/Octane/etc. materials are passed
  through unmodified.
- **Plugin ID.** `1066666` is a placeholder. Request a real ID from
  Maxon's PluginCafé before distributing the plugin to other artists.

## Troubleshooting

| Symptom                                         | Likely cause                                                    |
| ----------------------------------------------- | --------------------------------------------------------------- |
| Menu item missing.                              | Plugin folder not in C4D's plugin search path; check that the   |
|                                                 | restart picked up the symlink/copy.                             |
| Console shows `config.json not found`.          | Plugin can't locate the repo. Use install option B and set      |
|                                                 | `MD2C4D_REPO_ROOT`, or move the plugin folder back inside the   |
|                                                 | repo at `c4d_plugin/`.                                          |
| Console shows `manifest.json not found`.        | Run an MD export, or `python -m md_bridge write-manifest`.      |
| Console shows `Unsupported format in manifest`. | Latest entry is FBX or ABC; those importers are still TODO.     |
| `Cinema 4D failed to load <file>`.              | The OBJ was written incomplete or to an unreachable path. Re-   |
|                                                 | export from MD and confirm the path inside the manifest entry.  |
| Materials look untextured after import.         | `find_textures` did not match anything for that garment. Check  |
|                                                 | the manifest entry's `textures` array.                          |
