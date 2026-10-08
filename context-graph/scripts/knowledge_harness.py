"""Standalone copy of the knowledge harness dispatcher."""
from pathlib import Path
import runpy

_module = Path(__file__).resolve().parents[1] / "skills" / "knowledge-engineering" / "scripts" / "knowledge_harness.py"
globals().update(runpy.run_path(str(_module)))

if __name__ == "__main__":
    raise SystemExit(main())
