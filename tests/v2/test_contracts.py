from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_reference_request_has_expected_shape(reference_request):
    assert reference_request.horizon.slot_count == 16
    assert len(reference_request.workloads) == 3
    assert len(reference_request.resource_pools) == 3
    assert reference_request.policy.weights.cost_bps == 4000


def test_objective_weights_must_sum_to_10000(reference_request):
    payload = reference_request.model_dump(mode="json", by_alias=True)
    payload["policy"]["weights"]["costBps"] = 3999
    with pytest.raises(ValidationError, match="must sum to 10000"):
        type(reference_request).model_validate(payload)


def test_pool_arrays_must_match_horizon(reference_request):
    payload = reference_request.model_dump(mode="json", by_alias=True)
    payload["resourcePools"][0]["capacityBySlot"] = [16] * 15
    payload["resourcePools"][0]["carbonGramsPerKwhBySlot"] = [410] * 15
    with pytest.raises(ValidationError, match="horizon requires 16"):
        type(reference_request).model_validate(payload)
