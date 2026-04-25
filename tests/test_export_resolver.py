"""Stdlib-only tests for ``md_bridge.export_resolver``.

Run from the repo root::

    python -m unittest discover

Each test builds a synthetic export folder + ``manifest.json`` in a
``tempfile.TemporaryDirectory`` so the suite is hermetic and never
touches a real Marvelous Designer export.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from md_bridge.config import BridgeConfig
from md_bridge.export_resolver import (
    ResolvedExport,
    ResolverError,
    resolve_latest,
)


def _make_config(folder: Path) -> BridgeConfig:
    return BridgeConfig(
        export_folder=str(folder),
        default_format="OBJ",
        scale_factor=1.0,
        axis_preset="Y_UP",
        texture_folder=str(folder / "textures"),
    )


def _write_manifest(folder: Path, entries: list[dict]) -> Path:
    manifest = folder / "manifest.json"
    manifest.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return manifest


def _touch(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _entry(
    file: Path,
    *,
    fmt: str = "OBJ",
    timestamp: str = "2026-01-01T00:00:00+00:00",
    garment: str = "garment",
    textures: list[str] | None = None,
    scale: float = 1.0,
    axis: str = "Y_UP",
) -> dict:
    return {
        "file": str(file),
        "format": fmt,
        "timestamp": timestamp,
        "garment": garment,
        "textures": textures or [],
        "scale_factor": scale,
        "axis_preset": axis,
    }


class ResolveLatestHappyPath(unittest.TestCase):
    def test_picks_newest_entry_when_all_valid(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            old = _touch(folder / "old.obj")
            new = _touch(folder / "new.obj")
            _write_manifest(
                folder,
                [
                    _entry(old, garment="old", timestamp="2025-01-01T00:00:00+00:00"),
                    _entry(new, garment="new", timestamp="2026-01-01T00:00:00+00:00"),
                ],
            )

            export = resolve_latest(_make_config(folder))

            self.assertIsInstance(export, ResolvedExport)
            self.assertEqual(export.garment, "new")
            self.assertEqual(export.format, "OBJ")
            self.assertEqual(export.file, new)
            self.assertEqual(export.timestamp, "2026-01-01T00:00:00+00:00")

    def test_supports_obj_fbx_abc(self) -> None:
        for fmt, ext in (("OBJ", "obj"), ("FBX", "fbx"), ("ABC", "abc")):
            with self.subTest(fmt=fmt):
                with tempfile.TemporaryDirectory() as td:
                    folder = Path(td)
                    f = _touch(folder / f"x.{ext}")
                    _write_manifest(folder, [_entry(f, fmt=fmt, garment="x")])
                    export = resolve_latest(_make_config(folder))
                    self.assertEqual(export.format, fmt)
                    self.assertEqual(export.file, f)

    def test_relative_path_resolved_against_export_folder(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            _touch(folder / "rel.obj")
            _write_manifest(
                folder,
                [
                    {
                        "file": "rel.obj",  # relative
                        "format": "OBJ",
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "garment": "rel",
                    }
                ],
            )
            export = resolve_latest(_make_config(folder))
            self.assertEqual(export.file, (folder / "rel.obj").resolve())


class ResolveLatestFallsBack(unittest.TestCase):
    def test_skips_entry_whose_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            old = _touch(folder / "old.obj")
            _write_manifest(
                folder,
                [
                    _entry(old, garment="old", timestamp="2025-01-01T00:00:00+00:00"),
                    _entry(
                        folder / "ghost.obj",
                        garment="ghost",
                        timestamp="2026-01-01T00:00:00+00:00",
                    ),
                ],
            )
            export = resolve_latest(_make_config(folder))
            self.assertEqual(export.garment, "old")

    def test_skips_unknown_format(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            f = _touch(folder / "g.obj")
            _write_manifest(
                folder,
                [
                    _entry(f, fmt="OBJ", garment="good", timestamp="2024-01-01T00:00:00+00:00"),
                    _entry(f, fmt="DAE", garment="weird", timestamp="2026-01-01T00:00:00+00:00"),
                ],
            )
            export = resolve_latest(_make_config(folder))
            self.assertEqual(export.garment, "good")

    def test_skips_unparseable_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            f = _touch(folder / "g.obj")
            _write_manifest(
                folder,
                [
                    _entry(f, garment="good", timestamp="2024-01-01T00:00:00+00:00"),
                    _entry(f, garment="broken", timestamp="not-a-date"),
                ],
            )
            export = resolve_latest(_make_config(folder))
            self.assertEqual(export.garment, "good")

    def test_skips_empty_garment(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            f = _touch(folder / "g.obj")
            _write_manifest(
                folder,
                [
                    _entry(f, garment="good", timestamp="2024-01-01T00:00:00+00:00"),
                    _entry(f, garment="", timestamp="2026-01-01T00:00:00+00:00"),
                ],
            )
            export = resolve_latest(_make_config(folder))
            self.assertEqual(export.garment, "good")

    def test_accepts_z_suffix_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            f = _touch(folder / "g.obj")
            _write_manifest(folder, [_entry(f, garment="g", timestamp="2026-01-01T00:00:00Z")])
            export = resolve_latest(_make_config(folder))
            self.assertEqual(export.garment, "g")


class ResolveLatestTextures(unittest.TestCase):
    def test_textures_split_into_present_and_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            geo = _touch(folder / "g.obj")
            real = _touch(folder / "g_diffuse.png", b"\x89PNG")
            _write_manifest(
                folder,
                [
                    _entry(
                        geo,
                        garment="g",
                        textures=[str(real), str(folder / "g_ghost.png")],
                    )
                ],
            )
            export = resolve_latest(_make_config(folder))
            self.assertEqual(export.textures, [real])
            self.assertEqual(export.textures_missing, 1)

    def test_relative_texture_path_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            geo = _touch(folder / "g.obj")
            _touch(folder / "g_diffuse.png", b"\x89PNG")
            _write_manifest(
                folder,
                [_entry(geo, garment="g", textures=["g_diffuse.png"])],
            )
            export = resolve_latest(_make_config(folder))
            self.assertEqual(len(export.textures), 1)
            self.assertEqual(export.textures[0].name, "g_diffuse.png")


class ResolveLatestErrors(unittest.TestCase):
    def test_missing_manifest_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            with self.assertRaises(ResolverError) as ctx:
                resolve_latest(_make_config(folder))
            self.assertIn("manifest.json not found", str(ctx.exception))

    def test_empty_manifest_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            _write_manifest(folder, [])
            with self.assertRaises(ResolverError) as ctx:
                resolve_latest(_make_config(folder))
            self.assertIn("empty", str(ctx.exception))

    def test_malformed_manifest_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            (folder / "manifest.json").write_text("{ not json", encoding="utf-8")
            with self.assertRaises(ResolverError) as ctx:
                resolve_latest(_make_config(folder))
            self.assertIn("not valid JSON", str(ctx.exception))

    def test_no_valid_entries_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            _write_manifest(
                folder,
                [
                    _entry(
                        folder / "ghost.obj",
                        garment="ghost",
                        timestamp="2026-01-01T00:00:00+00:00",
                    )
                ],
            )
            with self.assertRaises(ResolverError) as ctx:
                resolve_latest(_make_config(folder))
            self.assertIn("No valid export entries", str(ctx.exception))

    def test_missing_export_folder_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ghost = Path(td) / "does_not_exist"
            with self.assertRaises(ResolverError) as ctx:
                resolve_latest(_make_config(ghost))
            self.assertIn("Export folder is missing", str(ctx.exception))


class ResolvedExportToDict(unittest.TestCase):
    def test_to_dict_round_trip(self) -> None:
        e = ResolvedExport(
            garment="x",
            format="OBJ",
            file=Path("/tmp/x.obj"),
            timestamp="2026-01-01T00:00:00+00:00",
            textures=[Path("/tmp/x_d.png")],
            textures_missing=1,
            scale_factor=2.0,
            axis_preset="Z_UP",
            sha1="abc",
        )
        d = e.to_dict()
        self.assertEqual(d["garment"], "x")
        self.assertEqual(d["format"], "OBJ")
        self.assertEqual(d["file"], "/tmp/x.obj")
        self.assertEqual(d["textures"], ["/tmp/x_d.png"])
        self.assertEqual(d["textures_missing"], 1)
        self.assertEqual(d["scale_factor"], 2.0)
        self.assertEqual(d["axis_preset"], "Z_UP")
        self.assertEqual(d["sha1"], "abc")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
