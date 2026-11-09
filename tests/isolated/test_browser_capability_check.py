import pytest

from psynet.experiment import BROWSER_CAPABILITY_TOKENS, Experiment
from psynet.modular_page import NextButton
from psynet.page import InfoPage, UnsuccessfulEndPage
from psynet.prescreen import (
    BrowserCapabilityCheck,
    BrowserCapabilityCheckPage,
    _capability_failure_prompt,
)
from psynet.timeline import StartSwitch, Timeline, conditional


def _make_timeline(*elts):
    return Timeline(*elts, InfoPage("Hello", time_estimate=1))


def _max_time(cls):
    return cls.timeline.estimated_time_credit.get_max("time")


def test_experiment_inserts_capability_check_at_start():
    class Exp(Experiment):
        browser_capabilities = {"microphone"}
        timeline = _make_timeline()

    first = Exp.timeline.module_list[0]
    assert isinstance(first, BrowserCapabilityCheck)
    assert first.capabilities == {"microphone"}
    assert Exp.timeline["main"][0].id == ["main", 0]


def test_insert_at_start_matches_timeline_built_with_element():
    def elts():
        return [
            conditional(lambda: True, InfoPage("A", time_estimate=2)),
            InfoPage("B", time_estimate=1),
        ]

    def summary(timeline):
        return (
            [(type(e).__name__, e.id) for e in timeline.all_elts],
            timeline.estimated_time_credit.get_max("time"),
        )

    inserted = Timeline(*elts())
    inserted.insert_at_start(BrowserCapabilityCheck({"microphone"}))
    built = Timeline(BrowserCapabilityCheck({"microphone"}), *elts())

    assert summary(inserted) == summary(built)


def test_experiment_without_capabilities_has_no_check():
    class Exp(Experiment):
        timeline = _make_timeline()

    assert not Exp.timeline.module_list


def test_experiment_accepts_generator_capabilities():
    class Exp(Experiment):
        browser_capabilities = (x for x in ["camera"])
        timeline = _make_timeline()

    assert Exp.browser_capabilities == {"camera"}
    assert Exp.timeline.module_list[0].capabilities == {"camera"}


def test_experiment_rejects_unknown_capability_at_definition():
    with pytest.raises(ValueError, match="not_a_real_capability"):

        class Exp(Experiment):
            browser_capabilities = {"not_a_real_capability"}


def test_experiment_rejects_check_already_in_timeline():
    shared = _make_timeline(BrowserCapabilityCheck({"microphone"}))
    with pytest.raises(ValueError, match="get_browser_capability_check"):

        class Exp(Experiment):
            browser_capabilities = {"microphone"}
            timeline = shared

    assert shared.experiment_class is None


def test_experiment_rejects_unknown_capability_from_mixin():
    class Mixin:
        browser_capabilities = {"not_a_real_capability"}

    with pytest.raises(ValueError, match="not_a_real_capability"):

        class Exp(Mixin, Experiment):
            pass


def test_experiment_can_place_check_manually():
    class Exp(Experiment):
        browser_capabilities = {"microphone"}

        @classmethod
        def get_browser_capability_check(cls):
            return None

        timeline = _make_timeline(
            InfoPage("Consent", time_estimate=1),
            BrowserCapabilityCheck(browser_capabilities),
        )

    assert len(Exp.timeline.module_list) == 1
    assert isinstance(Exp.timeline["main"][0], InfoPage)


def test_experiment_uses_custom_check():
    class Exp(Experiment):
        @classmethod
        def get_browser_capability_check(cls):
            return BrowserCapabilityCheck({"camera"}, label="custom_check")

        timeline = _make_timeline()

    assert Exp.timeline.module_list[0].id == "custom_check"


def test_subclass_changing_capabilities_must_define_timeline():
    class Base(Experiment):
        browser_capabilities = {"audio_playback"}
        timeline = _make_timeline()

    with pytest.raises(ValueError, match="Define timeline on Sub"):

        class Sub(Base):
            browser_capabilities = {"microphone"}


def test_base_class_may_declare_capabilities_without_timeline():
    class Base(Experiment):
        browser_capabilities = {"camera"}

    class Exp(Base):
        timeline = _make_timeline()

    assert Exp.timeline.module_list[0].capabilities == {"camera"}


def test_experiment_classes_cannot_share_a_timeline():
    class Exp(Experiment):
        timeline = _make_timeline()

    with pytest.raises(ValueError, match="same Timeline object"):

        class Other(Experiment):
            browser_capabilities = {"camera"}
            timeline = Exp.timeline


def test_classes_without_checks_may_share_a_timeline():
    class Exp(Experiment):
        timeline = _make_timeline()

    class Other(Experiment):
        timeline = Exp.timeline

    assert not Other.timeline.module_list


def test_subclass_may_redeclare_parent_timeline_and_capabilities():
    class Base(Experiment):
        browser_capabilities = {"camera"}
        timeline = _make_timeline()

    class Sub(Base):
        browser_capabilities = {"camera"}
        timeline = Base.timeline

    assert len(Sub.timeline.module_list) == 1


def test_subclass_inheriting_different_capabilities_must_define_timeline():
    class Base(Experiment):
        timeline = _make_timeline()

    class MicBase(Experiment):
        browser_capabilities = {"microphone"}

    with pytest.raises(ValueError, match="Define timeline on Sub"):

        class Sub(Base, MicBase):
            pass


@pytest.mark.parametrize("caps_on_class", [True, False])
def test_timeline_from_mixin_gets_check(caps_on_class):
    class Mixin:
        timeline = _make_timeline()

    class CapBase(Experiment):
        browser_capabilities = {"camera"}

    if caps_on_class:

        class Exp(Mixin, Experiment):
            browser_capabilities = {"camera"}

    else:

        class Exp(Mixin, CapBase):
            pass

    assert Exp.timeline.module_list[0].capabilities == {"camera"}


def test_permission_intro_counts_towards_time_estimate():
    class Mic(Experiment):
        browser_capabilities = {"microphone"}
        timeline = _make_timeline()

    class Audio(Experiment):
        browser_capabilities = {"audio_playback"}
        timeline = _make_timeline()

    assert _max_time(Mic) == _max_time(Audio) + 5.0


def test_browser_capability_check_validates_capabilities():
    BrowserCapabilityCheck(BROWSER_CAPABILITY_TOKENS)
    with pytest.raises(ValueError, match="not_a_real_capability"):
        BrowserCapabilityCheck({"not_a_real_capability"})
    with pytest.raises(ValueError, match="not a string"):
        BrowserCapabilityCheck("microphone")
    with pytest.raises(ValueError, match="not None"):
        BrowserCapabilityCheck(None)


def test_empty_capabilities_check_has_no_pages():
    check = BrowserCapabilityCheck(frozenset())
    assert not check.elts


def test_browser_capability_check_label_propagates():
    check = BrowserCapabilityCheck({"audio_playback"}, label="my_check")
    assert check.id == "my_check"

    page = next(e for e in check.elts if isinstance(e, BrowserCapabilityCheckPage))
    assert page.label == "my_check"
    assert any(isinstance(e, StartSwitch) for e in check.elts)
    end_page = next(e for e in check.elts if isinstance(e, UnsuccessfulEndPage))
    assert end_page.failure_tags == ["my_check"]


def test_browser_capability_check_page():
    caps = {"microphone", "audio_playback"}
    page = BrowserCapabilityCheckPage(caps)
    assert set(page.js_vars["capabilities"]) == caps
    assert any("browser-capability-check.js" in m for m in page.js_page_modules)
    assert not any(isinstance(b, NextButton) for b in page.buttons)


def test_capability_failure_prompt_per_token():
    messages = [str(_capability_failure_prompt(t)) for t in BROWSER_CAPABILITY_TOKENS]
    assert all(messages)
    assert len(set(messages)) == len(messages)

    fallback = str(_capability_failure_prompt("unknown_token"))
    assert fallback and fallback not in messages
