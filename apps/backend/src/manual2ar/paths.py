"""Workspace defaults for developer commands; deployment paths come from configuration."""
from pathlib import Path

def workspace_root():
    for candidate in (Path.cwd(),*Path(__file__).resolve().parents):
        if (candidate/'configs/app.example.json').is_file() and (candidate/'resources/catalog.json').is_file():return candidate
    return Path.cwd().resolve()  # installed backend: load an explicit config with absolute paths
ROOT=workspace_root()
