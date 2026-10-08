"""Standalone copy of the knowledge harness role authorizer."""
from pathlib import Path
import runpy

_module = Path(__file__).resolve().parents[1] / "skills" / "knowledge-engineering" / "scripts" / "role_access.py"
globals().update(runpy.run_path(str(_module)))
