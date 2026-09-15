"""
Microbenchmarks for hot-path psynet functions.

Each class targets one function or roundtrip and reports timing plus any
relevant tracked metrics (e.g. serialized payload size). Payloads are
built once per benchmark process via ``setup_cache`` and shared across
all timing iterations.
"""

from psynet.serialize import serialize, unserialize


class SerializeRoundtrip:
    """
    Benchmark ``psynet.serialize.serialize`` / ``unserialize`` on a
    nested-dict payload representative of a small experiment state.

    Attributes
    ----------

    timeout : int
        Hard upper bound (seconds) for ``setup_cache``. Defaults to ``120``.
    """

    timeout = 120

    # Explicit benchmark version; see
    # ``slow.experiment_performance._BaseExperiment``. Bump this integer when a
    # benchmark change makes new results incomparable to old ones.
    version = 1

    def setup_cache(self):
        obj = _make_payload()
        return {"obj": obj, "encoded": serialize(obj)}

    def time_serialize(self, cache):
        serialize(cache["obj"])

    def time_unserialize(self, cache):
        unserialize(cache["encoded"])

    def track_encoded_size(self, cache):
        return len(cache["encoded"])

    track_encoded_size.unit = "bytes"


def _make_payload():
    return {
        "participants": [
            {
                "id": i,
                "name": f"participant_{i}",
                "score": i * 1.5,
                "answers": [
                    {"q": f"q{j}", "a": (i + j) % 7, "ok": (i + j) % 2 == 0}
                    for j in range(20)
                ],
                "metadata": {"group": ["A", "B", "C"][i % 3], "active": i % 2 == 0},
            }
            for i in range(50)
        ],
        "config": {"version": "1.0", "tags": ["alpha", "beta", "gamma"]},
    }
