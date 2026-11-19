import pytest

from cosmas_os.application.worker_progress import WorkerProgress


def test_valid_intervals():
    for val in [90, 90.0, 0.5, 300]:
        progress = WorkerProgress(val)
        assert not progress.is_ready()


@pytest.mark.parametrize("bad_val", [True, False, 0, -1, 300.01, float("nan"), float("inf")])
def test_invalid_intervals(bad_val):
    with pytest.raises(ValueError) as excinfo:
        WorkerProgress(bad_val)
    assert str(excinfo.value) == "invalid worker progress interval"
