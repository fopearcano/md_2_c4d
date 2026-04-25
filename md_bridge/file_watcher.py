"""Polling watcher for the Marvelous Designer export folder.

Implemented with the standard library only — no ``watchdog`` dependency.
For an MVP that monitors a single export folder this is more than fast
enough, and it works identically on every OS Cinema 4D ships on.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Iterable

from .config import BridgeConfig
from .export_manifest import record_export
from .utils import iter_geometry

DEFAULT_INTERVAL = 2.0  # seconds between scans


def _snapshot(folder: Path) -> dict[str, float]:
    """Return ``{path: mtime}`` for every supported file directly in ``folder``."""
    snap: dict[str, float] = {}
    for f in iter_geometry(folder):
        try:
            snap[str(f)] = f.stat().st_mtime
        except FileNotFoundError:
            # File was removed between listing and stat; ignore.
            continue
    return snap


def _diff(old: dict[str, float], new: dict[str, float]) -> list[str]:
    """Return paths that are new or have a newer mtime than before."""
    changed: list[str] = []
    for path, mtime in new.items():
        if path not in old or mtime > old[path]:
            changed.append(path)
    return changed


def watch(
    config: BridgeConfig,
    *,
    interval: float = DEFAULT_INTERVAL,
    on_export: Callable[[dict], None] | None = None,
    iterations: int | None = None,
) -> None:
    """Watch ``config.export_folder`` and record every new export.

    Parameters
    ----------
    config:
        Loaded bridge configuration.
    interval:
        Seconds to sleep between scans.
    on_export:
        Optional callback invoked with the manifest entry for each new
        file, useful for logging or downstream hooks.
    iterations:
        If given, the watcher stops after this many polling rounds.
        Mainly useful for tests; ``None`` means run forever.
    """
    folder = Path(config.export_folder)
    folder.mkdir(parents=True, exist_ok=True)

    print(f"[md_bridge] watching {folder.resolve()} every {interval:.1f}s")
    seen = _snapshot(folder)

    rounds = 0
    while True:
        time.sleep(interval)
        current = _snapshot(folder)
        for path in _diff(seen, current):
            try:
                entry = record_export(path, config)
            except Exception as exc:  # noqa: BLE001
                print(f"[md_bridge] failed to record {path}: {exc}")
                continue
            print(f"[md_bridge] recorded {entry['format']} {entry['garment']}")
            if on_export is not None:
                on_export(entry)
        seen = current

        rounds += 1
        if iterations is not None and rounds >= iterations:
            return


def scan_once(config: BridgeConfig) -> Iterable[dict]:
    """Record every supported file currently in the export folder.

    Yields the manifest entry for each file recorded. Handy as a
    one-shot alternative to :func:`watch` from a post-export hook.
    """
    folder = Path(config.export_folder)
    folder.mkdir(parents=True, exist_ok=True)
    for f in iter_geometry(folder):
        yield record_export(f, config)
