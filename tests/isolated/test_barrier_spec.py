import json

import pytest
from markupsafe import Markup

from psynet.barrier_spec import (
    BarrierSpecError,
    barrier_from_spec_json,
    barrier_spec_json,
    behavior_hash,
)
from psynet.sync import Barrier, GroupBarrier, GroupCloser, SimpleGrouper

_PAGE_ATTRS = (
    "waiting_logic",
    "_uses_timeline_hold",
    "waiting_logic_expected_repetitions",
)


def _assert_page_fields_omitted(spec, restored):
    assert "page_policy" not in spec
    for name in _PAGE_ATTRS:
        assert name not in spec.get("state", {})
        assert not hasattr(restored, name)


class ThresholdBarrier(Barrier):
    def __init__(self, id_, threshold):
        super().__init__(id_)
        self.threshold = threshold

    def choose_who_to_release(self, waiting_participants):
        if len(waiting_participants) < self.threshold:
            return []
        return waiting_participants


def on_release(group, participants):
    group.released_count = len(participants)


def test_custom_barrier_round_trip_uses_plain_json():
    original = ThresholdBarrier("threshold", threshold=2)

    serialized = barrier_spec_json(original)
    restored = barrier_from_spec_json(serialized)
    spec = json.loads(serialized)

    assert spec["class"] == "test_barrier_spec.ThresholdBarrier"
    assert spec["state"] == {"id": "threshold", "threshold": 2}
    assert spec["version"] == 1
    assert spec["presentation"]["content"] is None
    _assert_page_fields_omitted(spec, restored)
    assert isinstance(restored, ThresholdBarrier)
    assert restored.id == "threshold"
    assert restored.threshold == 2
    assert restored.content is None


def test_callback_round_trip():
    original = GroupBarrier(
        "callback",
        group_type="pair",
        on_release=on_release,
    )

    restored = barrier_from_spec_json(barrier_spec_json(original))

    assert restored.group_type == "pair"
    assert restored.on_release.function is on_release


def test_reconstructed_barrier_runs_release_hooks():
    original = ThresholdBarrier("threshold", threshold=2)
    restored = barrier_from_spec_json(barrier_spec_json(original))
    waiters = [object(), object()]

    assert restored.choose_who_to_release(waiters) == waiters
    assert restored.choose_who_to_release(waiters[:1]) == []
    _assert_page_fields_omitted(json.loads(barrier_spec_json(original)), restored)


@pytest.mark.parametrize(
    "original",
    [
        SimpleGrouper(group_type="pair", initial_group_size=2),
        GroupCloser(group_type="pair"),
    ],
)
def test_built_in_barrier_round_trip(original):
    serialized = barrier_spec_json(original)
    restored = barrier_from_spec_json(serialized)

    assert type(restored) is type(original)
    assert restored.id == original.id
    _assert_page_fields_omitted(json.loads(serialized), restored)
    assert behavior_hash(restored) == behavior_hash(original)


def test_behavior_hash_tracks_release_state():
    first = ThresholdBarrier("threshold", threshold=2)
    same = ThresholdBarrier("threshold", threshold=2)
    different = ThresholdBarrier("threshold", threshold=3)

    assert behavior_hash(first) == behavior_hash(same)
    assert behavior_hash(first) != behavior_hash(different)


def test_simple_grouper_auto_id_includes_initial_group_size():
    assert SimpleGrouper(group_type="main", initial_group_size=3).id == "main_grouper_3"
    assert SimpleGrouper(group_type="main", initial_group_size=2).id == "main_grouper_2"
    assert SimpleGrouper(group_type="main", initial_group_size=2, id_="custom").id == (
        "custom"
    )


def test_timeline_rejects_same_barrier_id_with_different_behavior():
    from psynet.timeline import Timeline

    with pytest.raises(ValueError, match="different behavior"):
        Timeline(
            SimpleGrouper(group_type="main", initial_group_size=3, id_="same"),
            SimpleGrouper(group_type="main", initial_group_size=2, id_="same"),
        )


def test_timeline_allows_same_barrier_id_with_matching_behavior():
    from psynet.timeline import Timeline

    Timeline(
        SimpleGrouper(group_type="main", initial_group_size=2, id_="same"),
        SimpleGrouper(group_type="main", initial_group_size=2, id_="same"),
    )


def test_invalid_spec_version_is_rejected():
    serialized = json.dumps(
        {
            "version": 99,
            "class": "test_barrier_spec.ThresholdBarrier",
            "state": {"id": "threshold", "threshold": 2},
        }
    )

    with pytest.raises(BarrierSpecError, match="version"):
        barrier_from_spec_json(serialized)


def test_unsupported_state_is_rejected():
    barrier = ThresholdBarrier("threshold", threshold=2)
    barrier.unsupported = object()

    with pytest.raises(BarrierSpecError, match="unsupported"):
        barrier_spec_json(barrier)


def arrival_message(**kwargs):
    return "Someone arrived"


def test_group_barrier_restores_on_arrival_message_callable():
    original = GroupBarrier(
        "pair_hold",
        group_type="pair",
        on_arrival_message=arrival_message,
    )

    restored = barrier_from_spec_json(barrier_spec_json(original))
    spec = json.loads(barrier_spec_json(original))

    assert restored.notify_arrivals is True
    assert restored.on_arrival_message.function is arrival_message
    assert spec["notifications"]["on_arrival_message"]["__type__"] == "callable"
    assert spec["notifications"]["notify_arrivals"] is True
    assert behavior_hash(restored) == behavior_hash(
        GroupBarrier("pair_hold", group_type="pair", notify_arrivals=False)
    )


def test_group_barrier_restores_scalar_presentation_not_waiting_pages():
    original = GroupBarrier(
        "pair_hold",
        group_type="pair",
        content="Waiting for your partner",
        max_wait_time=30,
        max_wait_action="kick",
        notify_arrivals=False,
    )

    restored = barrier_from_spec_json(barrier_spec_json(original))
    spec = json.loads(barrier_spec_json(original))

    assert restored.content == "Waiting for your partner"
    assert restored.max_wait_time == 30
    assert restored.max_wait_action == "kick"
    assert restored.notify_arrivals is False
    _assert_page_fields_omitted(spec, restored)
    assert behavior_hash(restored) == behavior_hash(
        GroupBarrier(
            "pair_hold",
            group_type="pair",
            content="Waiting for someone else",
            max_wait_time=90,
            notify_arrivals=True,
        )
    )


def test_non_json_numeric_state_is_rejected():
    barrier = ThresholdBarrier("threshold", threshold=2)
    barrier.score = float("nan")

    with pytest.raises(BarrierSpecError, match="non-JSON numeric"):
        barrier_spec_json(barrier)


def test_local_barrier_class_is_rejected_at_encode_time():
    class LocalBarrier(Barrier):
        def choose_who_to_release(self, waiting_participants):
            return waiting_participants

    with pytest.raises(BarrierSpecError, match="local class"):
        barrier_spec_json(LocalBarrier("local"))


def test_local_class_value_is_rejected_at_encode_time():
    class LocalHelper:
        pass

    barrier = ThresholdBarrier("threshold", threshold=2)
    barrier.helper_cls = LocalHelper
    with pytest.raises(BarrierSpecError, match="local class"):
        barrier_spec_json(barrier)


def test_markup_content_round_trips():
    original = ThresholdBarrier("threshold", threshold=2)
    original.content = Markup("<em>Wait</em>")
    restored = barrier_from_spec_json(barrier_spec_json(original))
    assert isinstance(restored.content, Markup)
    assert str(restored.content) == "<em>Wait</em>"
