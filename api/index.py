from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for package_root in (
    ROOT / "packages" / "contracts",
    ROOT / "packages" / "optimizer",
    ROOT / "packages" / "adapters",
    ROOT / "packages" / "explanations",
    ROOT / "services" / "api",
):
    sys.path.insert(0, str(package_root))

from app.main import app  # noqa: E402,F401
