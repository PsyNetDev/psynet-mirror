from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from markupsafe import Markup, escape

from psynet.page import WaitPage, wait_while
from psynet.timeline import (
    AsyncCodeBlock,
    StartFixProgress,
    StartFixTimeCredit,
    StartSwitch,
    _while_loop_state_key,
    _while_loop_timed_out,
)
from psynet.timeline_hold import (
    TimelineHoldRecord,
    _ConditionHoldPage,
    _queue_timeline_hold_wake,
    _TimelineHoldPage,
    compose_hold_overlay_html,
)
from psynet.utils import serialise


def participant():
    obj = SimpleNamespace(
        time_credit=0.0,
        time_credit_fixes=[],
        total_wait_page_time=0.0,
    )

    def inc_time_credit(seconds):
        obj.time_credit += seconds

    obj.inc_time_credit = inc_time_credit
    return obj


def test_timeline_hold_accounts_release_to_resume_once():
    start = datetime(2026, 1, 1)
    record = TimelineHoldRecord(
        started_at=start,
        expected_wait=1.5,
        max_wait_time=20,
        fix_time_credit=False,
    )
    p = participant()

    record.mark_released(p, start + timedelta(seconds=3))
    record.settle(p, start + timedelta(seconds=5))
    record.settle(p, start + timedelta(seconds=5))

    assert record.released_at == start + timedelta(seconds=3)
    assert record.resumed_at == start + timedelta(seconds=5)
    assert record.actual_wait_seconds == pytest.approx(5)
    assert record.credited_wait_seconds == pytest.approx(5)
    assert p.time_credit == pytest.approx(5)
    assert p.total_wait_page_time == pytest.approx(5)


def test_timeline_hold_caps_credit_but_not_diagnostics():
    start = datetime(2026, 1, 1)
    record = TimelineHoldRecord(
        started_at=start,
        expected_wait=2,
        max_wait_time=4,
        fix_time_credit=False,
    )
    p = participant()

    record.settle(p, start + timedelta(seconds=7))

    assert record.actual_wait_seconds == pytest.approx(7)
    assert record.credited_wait_seconds == pytest.approx(4)
    assert p.time_credit == pytest.approx(4)
    assert p.total_wait_page_time == pytest.approx(7)


def test_fixed_timeline_hold_records_expected_credit():
    start = datetime(2026, 1, 1)
    record = TimelineHoldRecord(
        started_at=start,
        expected_wait=2,
        max_wait_time=10,
        fix_time_credit=True,
    )
    p = participant()

    record.settle(p, start + timedelta(seconds=7))

    assert record.actual_wait_seconds == pytest.approx(7)
    assert record.credited_wait_seconds == pytest.approx(2)
    assert p.time_credit == pytest.approx(2)
    assert p.total_wait_page_time == pytest.approx(7)


def test_separate_hold_visits_do_not_recredit_earlier_waiting():
    start = datetime(2026, 1, 1)
    p = participant()
    first = TimelineHoldRecord(
        started_at=start,
        expected_wait=1,
        max_wait_time=10,
        fix_time_credit=False,
    )
    second = TimelineHoldRecord(
        started_at=start + timedelta(seconds=2),
        expected_wait=1,
        max_wait_time=10,
        fix_time_credit=False,
    )

    first.settle(p, start + timedelta(seconds=1))
    second.settle(p, start + timedelta(seconds=3))

    assert p.time_credit == pytest.approx(2)
    assert p.total_wait_page_time == pytest.approx(2)


def test_while_loop_timeout_uses_exact_elapsed_time():
    start = datetime(2026, 1, 1)
    key = _while_loop_state_key("wait_while", "loop_start_time")
    p = SimpleNamespace(
        var=SimpleNamespace(
            get=lambda name, default=None: {key: serialise(start)}.get(name, default)
        )
    )

    assert not _while_loop_timed_out(
        p, "wait_while", 2, now=start + timedelta(seconds=1.999)
    )
    assert _while_loop_timed_out(p, "wait_while", 2, now=start + timedelta(seconds=2))


def test_wait_while_defaults_to_timeline_hold():
    logic = wait_while(lambda: True, expected_wait=3)
    holds = [elt for elt in logic if getattr(elt, "is_timeline_hold", False)]

    assert len(holds) == 1
    assert holds[0].time_estimate == 3
    assert not any(isinstance(elt, WaitPage) for elt in logic)
    assert not any(isinstance(elt, StartFixTimeCredit) for elt in logic)
    assert any(isinstance(elt, StartFixProgress) for elt in logic)


def test_wait_while_skips_hold_when_condition_is_already_false():
    logic = wait_while(lambda: False, expected_wait=3)
    switch = next(elt for elt in logic if isinstance(elt, StartSwitch))

    target = switch.get_target(
        experiment=object(),
        participant=SimpleNamespace(module_state=None),
    )

    assert target.name is False


def test_wait_while_preserves_explicit_wait_page_behavior():
    logic = wait_while(lambda: True, expected_wait=3, wait_page=WaitPage)

    assert any(isinstance(elt, WaitPage) for elt in logic)
    assert not any(getattr(elt, "is_timeline_hold", False) for elt in logic)
    assert any(isinstance(elt, StartFixTimeCredit) for elt in logic)


def test_wait_while_can_fix_timeline_hold_credit():
    logic = wait_while(
        lambda: True,
        expected_wait=3,
        fix_time_credit=True,
    )
    hold = next(elt for elt in logic if getattr(elt, "is_timeline_hold", False))

    assert hold.fix_time_credit
    assert any(isinstance(elt, StartFixTimeCredit) for elt in logic)


def test_wait_while_accepts_custom_hold_content():
    logic = wait_while(
        lambda: True,
        expected_wait=1,
        content="Custom hold message",
    )
    hold = next(elt for elt in logic if getattr(elt, "is_timeline_hold", False))

    assert hold.content == "Custom hold message"


def test_wait_while_rejects_content_with_wait_page():
    with pytest.raises(
        ValueError, match="content only applies when wait_page is omitted"
    ):
        wait_while(
            lambda: True,
            expected_wait=1,
            wait_page=WaitPage,
            content="Waiting…",
        )


def _async_placeholder(participant):
    return None


def test_async_code_block_passes_content_to_hold():
    block = AsyncCodeBlock(
        _async_placeholder,
        wait=True,
        expected_wait=1,
        content="Working…",
    )
    hold = next(
        elt for elt in block.resolve() if getattr(elt, "is_timeline_hold", False)
    )
    assert hold.content == "Working…"


def test_hold_overlay_html_matches_markup_and_plain_text():
    plain = next(
        elt
        for elt in wait_while(
            lambda: True, expected_wait=1, content="<strong>Waiting</strong>"
        )
        if getattr(elt, "is_timeline_hold", False)
    )
    trusted = next(
        elt
        for elt in wait_while(
            lambda: True,
            expected_wait=1,
            content=Markup("<strong>Waiting</strong>"),
        )
        if getattr(elt, "is_timeline_hold", False)
    )

    assert plain.overlay_html() == (
        '<span class="psynet-timeline-hold-title">'
        f"{escape('<strong>Waiting</strong>')}"
        "</span>"
    )
    assert (
        trusted.overlay_html()
        == '<span class="psynet-timeline-hold-title"><strong>Waiting</strong></span>'
    )


def test_safe_hold_wake_does_not_propagate_notification_errors(monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise RuntimeError("wake failed")

    monkeypatch.setattr(
        "psynet.timeline_hold._enqueue_timeline_hold_wake",
        fail,
    )

    _queue_timeline_hold_wake(1)

    assert "Failed to queue a timeline hold wake" in caplog.text


class ResumeTestHold(_TimelineHoldPage):
    def __init__(self, *, can_resume, timed_out):
        self._can_resume = can_resume
        self._timed_out = timed_out
        self.prepared = False
        self.timeout_applied = False
        super().__init__(
            hold_id="test",
            expected_wait=1,
            max_wait_time=2,
            fix_time_credit=False,
            check_interval=1,
        )

    def participant_can_resume(self, experiment, participant):
        return self._can_resume

    def participant_timed_out(self, participant):
        return self._timed_out

    def prepare_to_resume(self, participant):
        self.prepared = True

    def apply_timeout(self, participant):
        self.timeout_applied = True


def test_timeout_wins_over_simultaneous_release():
    hold = ResumeTestHold(can_resume=True, timed_out=True)
    participant = SimpleNamespace(pending_redirect=None, failed=False)

    assert hold.is_ready_to_resume(object(), participant)
    assert not hold.prepared
    assert not hold.timeout_applied
    assert hold.prepare_resume_if_ready(object(), participant)
    assert hold.prepared
    assert hold.timeout_applied


def test_forced_resume_does_not_evaluate_author_condition():
    hold = _ConditionHoldPage(
        condition=lambda: pytest.fail("condition should not be evaluated"),
        hold_id="test",
        expected_wait=1,
        max_wait_time=2,
        fix_time_credit=False,
        check_interval=1,
    )
    participant = SimpleNamespace(pending_redirect="unsuccessful_end", failed=True)

    assert hold.prepare_resume_if_ready(object(), participant)


def test_uncleared_timed_out_hold_applies_timeout():
    hold = ResumeTestHold(can_resume=False, timed_out=True)
    participant = SimpleNamespace(pending_redirect=None, failed=False)

    assert hold.prepare_resume_if_ready(object(), participant)
    assert hold.prepared
    assert hold.timeout_applied


def test_timed_out_hold_does_not_evaluate_condition():
    hold = ResumeTestHold(can_resume=False, timed_out=True)
    participant = SimpleNamespace(pending_redirect=None, failed=False)

    def raise_condition_error(experiment, participant):
        pytest.fail("expired hold condition should not be evaluated")

    hold.participant_can_resume = raise_condition_error

    assert hold.prepare_resume_if_ready(object(), participant)
    assert hold.prepared
    assert hold.timeout_applied


def test_hold_timeout_fails_participant_with_hold_tags():
    tags = []
    participant = SimpleNamespace(
        append_failure_tags=lambda *values: tags.extend(values),
        fail=lambda: tags.append("failed"),
    )
    hold = ResumeTestHold(can_resume=False, timed_out=True)

    _TimelineHoldPage.apply_timeout(hold, participant)

    assert tags == ["timeline_hold:test", "fail_on_timeout", "failed"]


def test_timeline_hold_payload_is_omitted_without_a_record():
    """A stale hold page object must not crash while building browser attributes."""

    class Hold(_TimelineHoldPage):
        def participant_can_resume(self, experiment, participant):
            return False

    page = Hold(
        hold_id="missing",
        expected_wait=1,
        max_wait_time=20,
        fix_time_credit=False,
        check_interval=2,
    )
    participant = SimpleNamespace(id=1, page_uuid="gone")
    page.get_hold_record = lambda _participant: None
    assert page.timeline_hold_payload(participant) is None


def test_compose_hold_overlay_html_always_emits_the_title_span():
    assert (
        compose_hold_overlay_html("Waiting for your partner")
        == '<span class="psynet-timeline-hold-title">Waiting for your partner</span>'
    )
    html = compose_hold_overlay_html("Waiting for your group", "1 of 3 not ready yet")
    assert 'class="psynet-timeline-hold-title"' in html
    assert 'class="psynet-timeline-hold-progress"' in html
    assert "1 of 3 not ready yet" in html
