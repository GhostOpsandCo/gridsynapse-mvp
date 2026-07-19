from __future__ import annotations

from pathlib import Path

import pytest
from gridsynapse_contracts import OptimizationRequest


@pytest.fixture
def reference_request() -> OptimizationRequest:
    path = Path(__file__).parents[2] / "data" / "scenarios" / "reference-scenario.json"
    return OptimizationRequest.model_validate_json(path.read_text())
