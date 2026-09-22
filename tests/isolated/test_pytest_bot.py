import pytest

from psynet import pytest_psynet

AD_URL = (
    "http://localhost:5000/ad"
    "?recruiter=hotair&assignmentId=HQ3PYE&hitId=7JF9M9&workerId=JF2UYZ&mode=debug"
)


class _Response:
    def __init__(self, ok=True, status_code=200):
        self.ok = ok
        self.status_code = status_code


@pytest.fixture
def bot(monkeypatch):
    """A PsyNet test bot whose browser raises if anything touches it."""

    def no_browser(self):
        raise AssertionError("complete_experiment must not use the browser.")

    bot = pytest_psynet.bot_class()(AD_URL)
    bot.participant_id = "1"
    monkeypatch.setattr(type(bot), "driver", property(no_browser))
    return bot


@pytest.fixture
def requests_calls(monkeypatch):
    calls = []

    def fake_request(method, url, params=None, timeout=None):
        calls.append((method, url, params, timeout))
        return _Response()

    monkeypatch.setattr(pytest_psynet.requests, "request", fake_request)
    return calls


def test_worker_complete_is_posted_without_a_page_load(bot, requests_calls):
    """The browser is already on the exit page; navigating there can hang."""
    bot.complete_experiment("worker_complete")
    assert requests_calls == [
        (
            "POST",
            "http://localhost:5000/worker_complete",
            {"participant_id": "1"},
            pytest_psynet.WORKER_STATUS_TIMEOUT_SEC,
        )
    ]


def test_worker_failed_uses_the_get_only_route(bot, requests_calls):
    bot.complete_experiment("worker_failed")
    method, url, _, _ = requests_calls[0]
    assert (method, url) == ("GET", "http://localhost:5000/worker_failed")


def test_rejected_worker_status_is_logged(bot, monkeypatch, caplog):
    monkeypatch.setattr(
        pytest_psynet.requests,
        "request",
        lambda *args, **kwargs: _Response(ok=False, status_code=400),
    )
    bot.complete_experiment("worker_complete")
    assert "returned HTTP 400" in caplog.text


def test_worker_status_routes_accept_the_methods_the_bot_uses():
    """Pin the Dallinger contract that decides the request method above."""
    from dallinger.experiment_server.experiment_server import app

    methods = {
        rule.rule: rule.methods
        for rule in app.url_map.iter_rules()
        if rule.rule in {"/worker_complete", "/worker_failed"}
    }
    assert "POST" in methods["/worker_complete"]
    assert "GET" in methods["/worker_failed"]


def test_missing_participant_id_is_rejected(bot):
    bot.participant_id = ""
    with pytest.raises(ValueError, match="participant_id is not set"):
        bot.complete_experiment("worker_complete")
