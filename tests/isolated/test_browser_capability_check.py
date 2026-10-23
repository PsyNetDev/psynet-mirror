import pytest


def test_browser_capability_check_default_instantiation():
    from psynet.prescreen import BrowserCapabilityCheck

    BrowserCapabilityCheck()


def test_browser_capability_check_explicit_capabilities():
    from psynet.prescreen import BrowserCapabilityCheck

    BrowserCapabilityCheck(capabilities={"microphone", "camera"})


def test_browser_capability_check_all_tokens():
    from psynet.experiment import BROWSER_CAPABILITY_TOKENS
    from psynet.prescreen import BrowserCapabilityCheck

    BrowserCapabilityCheck(capabilities=BROWSER_CAPABILITY_TOKENS)


def test_browser_capability_check_generator_input():
    from psynet.prescreen import BrowserCapabilityCheck

    # Generator is consumed by frozenset() before validation; capabilities must
    # not be silently dropped if a generator is passed.
    check = BrowserCapabilityCheck(capabilities=(x for x in ["microphone"]))
    assert check.capabilities == frozenset({"microphone"})


def test_browser_capability_check_rejects_unknown_token():
    from psynet.prescreen import BrowserCapabilityCheck

    with pytest.raises(ValueError, match="not_a_real_capability"):
        BrowserCapabilityCheck(capabilities={"not_a_real_capability"})


def test_empty_capabilities_conditional_is_noop():
    from psynet.prescreen import BrowserCapabilityCheck
    from psynet.timeline import PageMaker, StartSwitch

    check = BrowserCapabilityCheck(capabilities=frozenset())

    # The conditional is built inside _make_pages, so when caps are empty
    # _make_pages returns [] and no StartSwitch ever appears in the timeline.
    # The only top-level elt should be the PageMaker itself.
    assert not any(isinstance(e, StartSwitch) for e in check.elts)
    assert any(isinstance(e, PageMaker) for e in check.elts)


def test_browser_capability_check_rejects_string_capabilities():
    from psynet.prescreen import BrowserCapabilityCheck

    with pytest.raises(ValueError, match="not a string"):
        BrowserCapabilityCheck(capabilities="microphone")


def test_browser_capability_check_label_propagates():
    from unittest.mock import MagicMock

    from psynet.page import UnsuccessfulEndPage
    from psynet.prescreen import BrowserCapabilityCheck, BrowserCapabilityCheckPage
    from psynet.timeline import PageMaker

    check = BrowserCapabilityCheck(label="my_check", capabilities={"audio_playback"})
    assert check.id == "my_check"

    page_maker = next(e for e in check.elts if isinstance(e, PageMaker))
    resolved = page_maker.resolve(MagicMock(), MagicMock(), position=[0])

    cap_page = next(e for e in resolved if isinstance(e, BrowserCapabilityCheckPage))
    assert cap_page.label == "my_check"

    end_page = next(e for e in resolved if isinstance(e, UnsuccessfulEndPage))
    assert end_page.failure_tags == ["my_check"]


def test_permission_capability_includes_intro_page():
    from unittest.mock import MagicMock

    from psynet.page import InfoPage
    from psynet.prescreen import BrowserCapabilityCheck
    from psynet.timeline import PageMaker

    check = BrowserCapabilityCheck(capabilities={"microphone"})
    page_maker = next(e for e in check.elts if isinstance(e, PageMaker))
    resolved = page_maker.resolve(MagicMock(), MagicMock(), position=[0])

    assert any(isinstance(e, InfoPage) for e in resolved)


def test_browser_capability_check_page_js_vars():
    from psynet.prescreen import BrowserCapabilityCheckPage

    caps = {"microphone", "audio_playback"}
    page = BrowserCapabilityCheckPage(caps)
    assert "capabilities" in page.js_vars
    assert set(page.js_vars["capabilities"]) == caps


def test_browser_capability_check_page_has_module():
    from psynet.prescreen import BrowserCapabilityCheckPage

    page = BrowserCapabilityCheckPage({"screen_capture"})
    assert any("browser-capability-check.js" in m for m in page.js_page_modules)


def test_capability_failure_prompt_per_token():
    from psynet.prescreen import _capability_failure_prompt

    # Each known token produces a distinct, non-empty message.
    tokens = ["microphone", "camera", "screen_capture", "video_recording", "audio_playback"]
    messages = [str(_capability_failure_prompt(t)) for t in tokens]
    assert all(messages), "at least one token produced an empty message"
    assert len(set(messages)) == len(tokens), "two tokens produced the same message"

    # Unknown token falls back gracefully.
    fallback = str(_capability_failure_prompt("unknown_token"))
    assert fallback, "fallback message is empty"
    assert fallback not in messages, "fallback collides with a known-token message"


def test_capability_failure_page_appears_in_conditional():
    from unittest.mock import MagicMock

    from psynet.page import InfoPage, UnsuccessfulEndPage
    from psynet.prescreen import BrowserCapabilityCheck
    from psynet.timeline import PageMaker

    check = BrowserCapabilityCheck(capabilities={"audio_playback"})
    outer_page_maker = next(e for e in check.elts if isinstance(e, PageMaker))

    mock_participant = MagicMock()
    mock_participant.answer = {"passed": False, "missing": "audio_playback"}
    resolved = outer_page_maker.resolve(MagicMock(), mock_participant, position=[0])

    # The conditional body contains a PageMaker (the fail explanation page)
    # followed by UnsuccessfulEndPage. Resolve the inner PageMaker to check content.
    inner_makers = [e for e in resolved if isinstance(e, PageMaker)]
    assert inner_makers, "No inner PageMaker found for failure explanation page."
    fail_pages = inner_makers[-1].resolve(MagicMock(), mock_participant, position=[0])
    info_pages = [e for e in fail_pages if isinstance(e, InfoPage)]
    assert any(
        "audio playback" in p.prompt.text.lower() for p in info_pages
    ), "Failure InfoPage does not mention 'audio playback'."

    assert any(isinstance(e, UnsuccessfulEndPage) for e in resolved)


def test_browser_capability_check_page_no_next_button():
    from psynet.prescreen import BrowserCapabilityCheckPage

    page = BrowserCapabilityCheckPage({"audio_playback"})
    from psynet.modular_page import NextButton

    assert not any(isinstance(b, NextButton) for b in page.buttons)
