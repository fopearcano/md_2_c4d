"""Polling watcher for the Marvelous Designer export folder.

Implementation notes
--------------------
* No third-party dependencies (no ``watchdog``). Polls every
  ``interval`` seconds.
* Debounce: a file must appear with the same size *and* mtime for
  ``stable_rounds`` consecutive scans before it counts as "complete".
  This is what stops us reacting to a half-written export — a long MD
  export keeps growing for several scans, only quieting once writing
  finishes.
* Once a path has been reported as complete, the watcher remembers
  its (size, mtime) and ignores it on subsequent scans. If the file
  is rewritten (size or mtime moves) it goes back through the
  debounce gate and is re-reported.
* The bridge's own ``manifest.json`` is filtered out so we cannot
  feed our own writes back into the watch loop.
* Watched extensions: ``.obj``, ``.fbx``, ``.abc`` (geometry, fed
  into the manifest writer) and ``.json`` (informational — printed
  but never auto-recorded).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .config import BridgeConfig
from .export_manifest import MANIFEST_FILENAME, record_export
from .utils import iter_geometry

DEFAULT_INTERVAL = 2.0  # seconds between scans
DEFAULT_STABLE_ROUNDS = 2  # scans of unchanged size+mtime before "done"

GEOMETRY_EXTS: tuple[str, ...] = (".obj", ".fbx", ".abc")
MANIFEST_EXTS: tuple[str, ...] = (".json",)
WATCHED_EXTS: tuple[str, ...] = GEOMETRY_EXTS + MANIFEST_EXTS


class WatcherError(RuntimeError):
    """Raised for user-facing watcher problems (bad/unwritable folder)."""


@dataclass
class _Tracked:
    """Per-file debounce state."""

    size: int
    mtime: float
    stable_rounds: int


def _is_watchable(path: Path) -> bool:
    """True if ``path`` is a file we should debounce + report on."""
    if not path.is_file():
        return False
    if path.name == MANIFEST_FILENAME:
        # Skip our own manifest so writes from record_export don't
        # bounce back into the watcher.
        return False
    return path.suffix.lower() in WATCHED_EXTS


def _scan(folder: Path) -> dict[str, tuple[int, float]]:
    """Return ``{path: (size, mtime)}`` for every watched file in ``folder``."""
    snap: dict[str, tuple[int, float]] = {}
    if not folder.is_dir():
        return snap
    for child in folder.iterdir():
        if not _is_watchable(child):
            continue
        try:
            st = child.stat()
        except FileNotFoundError:
            # File vanished between listing and stat; ignore.
            continue
        snap[str(child)] = (st.st_size, st.st_mtime)
    return snap


def _ensure_export_folder(config: BridgeConfig) -> Path:
    """Resolve, create-if-missing and validate the export folder.

    Raises :class:`WatcherError` with a user-friendly message if the
    path is missing/unwritable or points at something that isn't a
    directory.
    """
    if not config.export_folder:
        raise WatcherError(
            "config.json has an empty 'export_folder'. Edit it to point "
            "at the directory Marvelous Designer writes its exports into."
        )
    folder = Path(config.export_folder).expanduser()
    if folder.exists() and not folder.is_dir():
        raise WatcherError(
            f"Export folder path exists but is not a directory: {folder}. "
            "Edit 'export_folder' in config.json to point at a folder."
        )
    if not folder.exists():
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WatcherError(
                f"Cannot create export folder {folder}: {exc}. "
                "Pick a writable location with `--config` or by editing "
                "'export_folder' in config.json."
            ) from exc
        print(f"[md_bridge] created export folder: {folder.resolve()}")
    return folder.resolve()


def _report_complete(path: Path, config: BridgeConfig) -> None:
    """Log a stable file; append to the manifest only for geometry."""
    ext = path.suffix.lower()
    if ext in GEOMETRY_EXTS:
        try:
            entry = record_export(path, config)
        except Exception as exc:  # noqa: BLE001
            print(f"[md_bridge] failed to record {path.name}: {exc}")
            return
        print(
            f"[md_bridge] complete: {entry['format']} '{entry['garment']}' "
            f"-> {entry['file']}"
        )
        textures = entry.get("textures") or []
        if textures:
            print(f"[md_bridge]   textures: {len(textures)} file(s)")
    elif ext in MANIFEST_EXTS:
        # External / user-supplied JSON sidecar. Announce but don't
        # interpret — we filter our own manifest.json out earlier.
        print(f"[md_bridge] complete: JSON sidecar -> {path}")


def watch(
    config: BridgeConfig,
    *,
    interval: float = DEFAULT_INTERVAL,
    stable_rounds: int = DEFAULT_STABLE_ROUNDS,
    on_complete: Callable[[Path], None] | None = None,
    iterations: int | None = None,
) -> None:
    """Watch ``config.export_folder`` and report each file when it goes quiet.

    Parameters
    ----------
    config:
        Loaded bridge configuration.
    interval:
        Seconds to sleep between scans. Must be > 0.
    stable_rounds:
        Consecutive scans where ``(size, mtime)`` must remain unchanged
        before a file is reported as complete. Higher = more debounce,
        slower reaction. Minimum 1.
    on_complete:
        Optional callback invoked with the :class:`Path` of each
        completed file, after the watcher has logged and (for geometry)
        recorded it.
    iterations:
        If given, the watcher stops after this many polling rounds.
        Mainly useful for tests; ``None`` means run forever.
    """
    if interval <= 0:
        raise ValueError("interval must be > 0")
    if stable_rounds < 1:
        raise ValueError("stable_rounds must be >= 1")

    folder = _ensure_export_folder(config)
    print(
        f"[md_bridge] watching {folder} every {interval:.1f}s "
        f"(debounce: {stable_rounds} stable round(s))"
    )
    print("[md_bridge] press Ctrl+C to stop")

    tracked: dict[str, _Tracked] = {}
    completed: dict[str, tuple[int, float]] = {}

    rounds = 0
    while True:
        time.sleep(interval)
        snap = _scan(folder)

        # Drop bookkeeping for files that have disappeared.
        for gone in [p for p in tracked if p not in snap]:
            del tracked[gone]
        for gone in [p for p in completed if p not in snap]:
            del completed[gone]

        for path_str, (size, mtime) in snap.items():
            prev_complete = completed.get(path_str)
            if prev_complete is not None:
                if prev_complete == (size, mtime):
                    # Already announced and unchanged.
                    continue
                # Re-armed: the file moved again.
                del completed[path_str]

            prev = tracked.get(path_str)
            if prev is None or prev.size != size or prev.mtime != mtime:
                tracked[path_str] = _Tracked(size=size, mtime=mtime, stable_rounds=1)
                continue

            prev.stable_rounds += 1
            if prev.stable_rounds < stable_rounds:
                continue

            # Stable long enough — promote and announce.
            del tracked[path_str]
            completed[path_str] = (size, mtime)
            path = Path(path_str)
            _report_complete(path, config)
            if on_complete is not None:
                try:
                    on_complete(path)
                except Exception as exc:  # noqa: BLE001
                    print(f"[md_bridge] on_complete callback failed for {path}: {exc}")

        rounds += 1
        if iterations is not None and rounds >= iterations:
            return


def scan_once(config: BridgeConfig) -> Iterable[dict]:
    """Record every supported geometry file currently in the export folder.

    Yields the manifest entry for each file recorded. Useful as a
    one-shot alternative to :func:`watch`, e.g. from a post-export
    hook or a CI check.
    """
    folder = _ensure_export_folder(config)
    for child in iter_geometry(folder):
        yield record_export(child, config)
