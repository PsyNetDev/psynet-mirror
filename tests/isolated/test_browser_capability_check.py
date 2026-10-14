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


def test_browser_capability_check_rejects_unknown_token():
    from psynet.prescreen import BrowserCapabilityCheck

    with pytest.raises(ValueError, match="not_a_real_capability"):
        BrowserCapabilityCheck(capabilities={"not_a_real_capability"})


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
