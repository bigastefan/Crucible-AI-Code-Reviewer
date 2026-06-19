"""Ensures the repo root is on sys.path so tests can `import core` / `import providers`
even on older pytest configs that don't read pyproject's pythonpath."""
import sys
from pathlib import Path

root = str(Path(__file__).parent)
if root not in sys.path:
    sys.path.insert(0, root)
