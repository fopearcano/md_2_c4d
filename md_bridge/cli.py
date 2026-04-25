"""Command-line interface for MD2C4D Bridge."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import DEFAULT_CONFIG_PATH, load_config, write_default_config
from .export_manifest import manifest_path, record_export
from .file_watcher import (
    DEFAULT_INTERVAL,
    DEFAULT_STABLE_ROUNDS,
    WatcherError,
    watch,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="md_bridge",
        description="Bridge Marvelous Designer exports into Cinema 4D.",
    )
    parser.add_argument(
        "--version", action="version", version=f"md_bridge {__version__}"
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to config.json (default: ./config.json).",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="Create a default config.json.")
    init_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing config.json.",
    )

    watch_p = sub.add_parser(
        "watch",
        help="Watch the export folder for new OBJ/FBX/ABC/JSON files.",
    )
    watch_p.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help=f"Polling interval in seconds (default: {DEFAULT_INTERVAL}).",
    )
    watch_p.add_argument(
        "--stable-rounds",
        type=int,
        default=DEFAULT_STABLE_ROUNDS,
        help=(
            "Consecutive scans where size+mtime must stay unchanged before "
            f"a file is reported as complete (default: {DEFAULT_STABLE_ROUNDS}). "
            "Raise this if MD writes very large exports slowly."
        ),
    )

    wm_p = sub.add_parser(
        "write-manifest",
        help="Write a manifest entry for a single exported file.",
    )
    wm_p.add_argument("file", help="Path to the exported OBJ/FBX/ABC file.")

    return parser


def cmd_init(args: argparse.Namespace) -> int:
    path = write_default_config(args.config, overwrite=args.force)
    if path.stat().st_size == 0:
        print(f"[md_bridge] created empty config at {path}")
    else:
        action = "overwrote" if args.force else "ensured"
        print(f"[md_bridge] {action} config at {path}")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    try:
        watch(
            cfg,
            interval=args.interval,
            stable_rounds=args.stable_rounds,
        )
    except KeyboardInterrupt:
        # Clean Ctrl+C: print on its own line and exit normally.
        print("\n[md_bridge] watcher stopped")
        return 0
    return 0


def cmd_write_manifest(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    target = Path(args.file)
    entry = record_export(target, cfg)
    print(f"[md_bridge] appended entry to {manifest_path(cfg)}")
    print(json.dumps(entry, indent=2))
    return 0


COMMANDS = {
    "init": cmd_init,
    "watch": cmd_watch,
    "write-manifest": cmd_write_manifest,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = COMMANDS[args.command]
    try:
        return handler(args)
    except FileNotFoundError as exc:
        # load_config raises this when config.json is missing.
        print(f"[md_bridge] {exc}", file=sys.stderr)
        return 1
    except WatcherError as exc:
        print(f"[md_bridge] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
