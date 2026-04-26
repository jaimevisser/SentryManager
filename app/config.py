from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from flask import Flask

logger = logging.getLogger(__name__)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - config load should not crash app startup
        logger.warning("Failed to read config from %s: %s", path, exc)
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _cfg_value(cfg: dict[str, Any], key: str, env_key: str, default: Any) -> Any:
    if key in cfg and cfg[key] is not None:
        return cfg[key]
    env_val = os.getenv(env_key)
    return env_val if env_val is not None else default


def _merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _merge_config(merged[key], value)
            continue
        merged[key] = value
    return merged


@dataclass(slots=True)
class AppSettings:
    env: str
    teslacam_root: str
    previews_root: str
    max_previews_folder_size_gb: int

    def as_flask_config(self) -> dict[str, Any]:
        return {
            "APP_ENV": self.env,
            "TESLACAM_ROOT": self.teslacam_root,
            "PREVIEWS_ROOT": self.previews_root,
            "MAX_PREVIEWS_FOLDER_SIZE_GB": self.max_previews_folder_size_gb,
        }


def load_settings() -> AppSettings:
    config_root = Path(os.getenv("CONFIG_ROOT", Path(__file__).resolve().parent.parent / "config")).resolve()
    general_dir = config_root / "general"
    general_cfg = _merge_config(
        _load_yaml(general_dir / "config.example.yaml"),
        _load_yaml(general_dir / "config.yaml"),
    )

    storage_cfg = general_cfg.get("storage") if isinstance(general_cfg, dict) else None
    storage_cfg = storage_cfg if isinstance(storage_cfg, dict) else {}

    return AppSettings(
        env=str(_cfg_value(general_cfg, "app_env", "APP_ENV", "development")),
        teslacam_root=str(os.getenv("TESLACAM_ROOT", "/data/TeslaCam")),
        previews_root=str(os.getenv("PREVIEWS_ROOT", "/data/Previews")),
        max_previews_folder_size_gb=max(
            1,
            int(_cfg_value(storage_cfg, "max_previews_folder_size_gb", "MAX_PREVIEWS_FOLDER_SIZE_GB", 100)),
        ),
    )


def apply_settings(app: Flask) -> AppSettings:
    settings = load_settings()
    app.config.update(settings.as_flask_config())
    app.extensions["settings"] = settings
    return settings