from benchmarks.slow.experiment_performance import AsyncProcesses, Static


def test_slow_asv_tracks_median_response_time():
    benchmark = Static()
    data = {
        (5, 2.0): {
            "median_response_time": 0.123,
        }
    }

    assert benchmark.track_median_response_time_ms(data, 5, 2.0) == 123.0


def test_slow_asv_tracks_median_queue_delay_for_async_experiment():
    benchmark = AsyncProcesses()
    data = {
        (5, 2.0): {
            "q_delay_median": 0.045,
        }
    }

    assert benchmark.track_median_queue_delay_ms(data, 5, 2.0) == 45.0


def test_slow_asv_no_longer_tracks_completion_window_metrics():
    benchmark = Static()

    assert not hasattr(benchmark, "track_failure_rate")
    assert not hasattr(benchmark, "track_incomplete_rate")
    assert not hasattr(benchmark, "track_sec_per_bot")
