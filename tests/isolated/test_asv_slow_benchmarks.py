import pytest

from benchmarks.slow.experiment_performance import AsyncJobs, Static


def test_slow_asv_tracks_median_response_time():
    benchmark = Static()
    data = {
        (5, 2.0): {
            "median_response_time": 0.123,
        }
    }

    assert benchmark.track_median_response_time_ms(data, 5, 2.0) == 123.0


def test_slow_asv_tracks_median_queue_delay_for_async_experiment():
    benchmark = AsyncJobs()
    data = {
        (5, 2.0): {
            "q_delay_median": 0.045,
        }
    }

    assert benchmark.track_median_queue_delay_ms(data, 5, 2.0) == 45.0


def test_slow_asv_tracks_export_time():
    benchmark = Static()
    data = {(5, 2.0): {"export": {"duration_s": 3.5, "error": None, "db_rows": {}}}}

    assert benchmark.track_export_time_s(data, 5, 2.0) == 3.5


@pytest.mark.parametrize(
    "export, message",
    [
        ({"duration_s": 0.1, "error": "timeout", "db_rows": {}}, "export failed"),
        (None, "--no-export"),
    ],
)
def test_slow_asv_raises_without_export_time(export, message):
    benchmark = Static()

    with pytest.raises(RuntimeError, match=message):
        benchmark.track_export_time_s({(5, 2.0): {"export": export}}, 5, 2.0)


def test_slow_asv_no_longer_tracks_completion_window_metrics():
    benchmark = Static()

    assert not hasattr(benchmark, "track_failure_rate")
    assert not hasattr(benchmark, "track_incomplete_rate")
    assert not hasattr(benchmark, "track_sec_per_bot")
