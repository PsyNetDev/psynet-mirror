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
    from unittest.mock import MagicMock

    from psynet.timeline import StartSwitch
    from psynet.prescreen import BrowserCapabilityCheck

    check = BrowserCapabilityCheck(capabilities=frozenset())
    start_switch = next(e for e in check.elts if isinstance(e, StartSwitch))

    participant = MagicMock()
    participant.answer = {"passed": False}
    experiment = MagicMock()
    experiment.browser_capabilities = frozenset()

    # When capabilities are empty the condition must be False,
    # regardless of a preceding page's answer matching the fail shape.
    result = start_switch.function(experiment=experiment, participant=participant)
    assert not result


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


def test_browser_capability_check_page_no_next_button():
    from psynet.prescreen import BrowserCapabilityCheckPage

    page = BrowserCapabilityCheckPage({"audio_playback"})
    from psynet.modular_page import NextButton

    assert not any(isinstance(b, NextButton) for b in page.buttons)
