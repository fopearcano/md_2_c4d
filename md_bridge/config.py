"""Load, validate and persist the bridge configuration."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("config.json")

ALLOWED_FORMATS: tuple[str, ...] = ("OBJ", "FBX", "ABC")
ALLOWED_AXIS_PRESETS: tuple[str, ...] = ("Y_UP", "Z_UP")


@dataclass
class BridgeConfig:
    export_folder: str = "./exports"
    default_format: str = "FBX"
    scale_factor: float = 1.0
    axis_preset: str = "Y_UP"
    texture_folder: str = "./exports/textures"

    def validate(self) -> None:
        fmt = self.default_format.upper()
        if fmt not in ALLOWED_FORMATS:
            raise ValueError(
                f"default_format must be one of {ALLOWED_FORMATS}, got {self.default_format!r}"
            )
        self.default_format = fmt

        axis = self.axis_preset.upper()
        if axis not in ALLOWED_AXIS_PRESETS:
            raise ValueError(
                f"axis_preset must be one of {ALLOWED_AXIS_PRESETS}, got {self.axis_preset!r}"
            )
        self.axis_preset = axis

        if not isinstance(self.scale_factor, (int, float)):
            raise ValueError("scale_factor must be numeric")
        self.scale_factor = float(self.scale_factor)
        if self.scale_factor <= 0:
            raise ValueError("scale_factor must be > 0")

    def to_dict(self) -> dict:
        return asdict(self)


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> BridgeConfig:
    """Read ``config.json`` from disk and return a validated config."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Config not found at {p}. Run `python -m md_bridge init` first."
        )
    with p.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    cfg = BridgeConfig(
        export_folder=raw.get("export_folder", "./exports"),
        default_format=raw.get("default_format", "FBX"),
        scale_factor=raw.get("scale_factor", 1.0),
        axis_preset=raw.get("axis_preset", "Y_UP"),
        texture_folder=raw.get("texture_folder", "./exports/textures"),
    )
    cfg.validate()
    return cfg


def write_default_config(path: str | Path = DEFAULT_CONFIG_PATH, *, overwrite: bool = False) -> Path:
    """Create a default ``config.json`` at ``path``.

    If a file already exists and ``overwrite`` is False, the existing
    file is left untouched.
    """
    p = Path(path)
    if p.exists() and not overwrite:
        return p

    cfg = BridgeConfig()
    cfg.validate()
    with p.open("w", encoding="utf-8") as fh:
        json.dump(cfg.to_dict(), fh, indent=2)
        fh.write("\n")
    return p
