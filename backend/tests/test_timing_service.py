import time

from backend.app.services.timing_service import timer


def test_timer_records_elapsed_ms():
    store: dict[str, float] = {}
    with timer("step", store):
        time.sleep(0.01)
    assert "step" in store
    assert store["step"] >= 5  # at least a few ms elapsed


def test_timer_records_even_on_exception():
    store: dict[str, float] = {}
    try:
        with timer("step", store):
            raise ValueError("boom")
    except ValueError:
        pass
    assert "step" in store
