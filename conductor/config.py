"""
Configuration management for Conductor.

Handles loading and accessing configuration from config.yaml.
"""

from pathlib import Path
from typing import Any

import yaml

# Default paths
SCRIPT_DIR = Path(__file__).parent.parent.resolve()
CONFIG_FILE = SCRIPT_DIR / "config.yaml"
SCRIPTS_DIR = SCRIPT_DIR / "scripts"


def load_config() -> dict[str, Any]:
    """
    Load configuration from config.yaml.
    
    Returns:
        Dictionary containing configuration, or empty dict if file doesn't exist
    """
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return yaml.safe_load(f)
    return {}


