"""Config hashing — detect material config changes that require re-validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Union


def hash_config_file(config_path: Union[str, Path]) -> str:
    """
    Compute SHA256 hash of a config file.

    Used to detect material config changes that invalidate promotion artifacts.
    """
    path = Path(config_path)
    content = path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def hash_config_dict(config: dict) -> str:
    """
    Compute SHA256 hash of a config dictionary.

    Uses sorted keys for deterministic output.
    """
    canonical = json.dumps(config, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def hash_multiple_configs(config_paths: list[str]) -> str:
    """
    Compute a single hash representing all provided config files.
    Order of paths matters — use consistent ordering.
    """
    combined = b""
    for path in sorted(config_paths):
        combined += Path(path).read_bytes()
    return hashlib.sha256(combined).hexdigest()
