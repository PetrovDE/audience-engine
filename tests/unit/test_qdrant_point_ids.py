from pipelines.minimal_slice.qdrant_index import _point_id


def test_point_id_determinism_for_known_values():
    assert _point_id("cust_001") == 1854028926609399526
    assert _point_id("customer-abc") == 9043861497595082376
    assert _point_id("42") == 8306709966045482637


def test_point_id_determinism_across_repeated_calls():
    expected = _point_id("cust_repeat")
    for _ in range(100):
        assert _point_id("cust_repeat") == expected


def test_point_id_collision_sanity_for_sample_set():
    sample_ids = [_point_id(f"cust_{i:05d}") for i in range(10_000)]
    assert len(sample_ids) == len(set(sample_ids))
