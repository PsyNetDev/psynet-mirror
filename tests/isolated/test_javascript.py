import warnings
from types import SimpleNamespace

import pytest

from psynet.page import ExecuteFrontEndJS, JsPsychPage, UnityPage
from psynet.sync import arrival_notice_payload
from psynet.timeline import Page
from psynet.timeline_hold import _timeline_hold_channel


def test_execute_front_end_js_shows_a_spinner_not_prose():
    """The page is too brief to read, so it shows activity rather than text."""
    content = ExecuteFrontEndJS("doSomething()").content
    assert 'class="psynet-activity"' in content
    assert 'class="spinner-border"' in content
    # Screen readers have nothing else to announce on this page.
    assert 'role="status"' in content
    assert 'class="visually-hidden">Working...' in content


def test_execute_front_end_js_rejects_a_message():
    with pytest.raises(TypeError, match="message"):
        ExecuteFrontEndJS("doSomething()", message="Finalizing...")


@pytest.mark.parametrize("argument_name", ["js_dependencies", "js_page_modules"])
@pytest.mark.parametrize(
    "invalid_value, error, match",
    [
        ([""], ValueError, "non-empty"),
        ([123], TypeError, "strings"),
        ("not-a-list", TypeError, "list or tuple"),
    ],
)
def test_page_validates_managed_javascript_urls(
    argument_name, invalid_value, error, match
):
    with pytest.raises(error, match=match):
        Page(
            template_fragment_str="<p>Managed JavaScript page</p>",
            **{argument_name: invalid_value},
        )


def test_page_normalizes_javascript_resources():
    page = Page(
        template_fragment_str="<p>Managed JavaScript page</p>",
        js_dependencies=[
            "/static/library.js",
            "  /static/other-library.js  ",
            "/static/library.js",
            " /static/library.js ",
        ],
        js_page_modules=[
            "/static/page.js",
            " /static/other-page.js ",
            "/static/page.js",
        ],
    )

    assert page.js_dependencies == [
        "/static/library.js",
        "/static/other-library.js",
    ]
    assert page.js_page_modules == [
        "/static/page.js",
        "/static/other-page.js",
    ]


def _page_participant(**overrides):
    participant = SimpleNamespace(
        unique_id="participant-1",
        page_uuid="page-1",
        id=7,
        active_sync_groups={},
    )
    participant.__dict__.update(overrides)
    return participant


def test_ungrouped_page_omits_arrival_updates(monkeypatch):
    """Solo pages must not open the partner-ready websocket."""

    def boom(_participant):
        raise AssertionError("should not look up arrival notices")

    monkeypatch.setattr("psynet.sync.pending_arrival_notice_for", boom)
    page = Page(template_fragment_str="<p>Solo page</p>")
    assert "arrival_updates" not in page.attributes(_page_participant())


def test_grouped_page_includes_arrival_updates(monkeypatch):
    monkeypatch.setattr(
        "psynet.sync.pending_arrival_notice_for",
        lambda _participant: "Your partner is ready.",
    )
    page = Page(template_fragment_str="<p>Grouped page</p>")
    participant = _page_participant(active_sync_groups={"main": object()})
    updates = page.attributes(participant)["arrival_updates"]
    assert updates["channel"] == _timeline_hold_channel(participant.id)
    assert updates["notice"] == "Your partner is ready."


def test_arrival_notice_payload_without_a_participant():
    assert arrival_notice_payload(None) == {"notice": None}
    assert arrival_notice_payload("") == {"notice": None}


def test_hold_page_omits_arrival_updates_even_when_grouped(monkeypatch):
    """The hold websocket already receives partner-ready and overlay messages."""

    class HoldPage(Page):
        is_timeline_hold = True

    def boom(_participant):
        raise AssertionError("should not look up arrival notices")

    monkeypatch.setattr("psynet.sync.pending_arrival_notice_for", boom)
    page = HoldPage(template_fragment_str="<p>Hold page</p>")
    participant = _page_participant(active_sync_groups={"main": object()})
    assert "arrival_updates" not in page.attributes(participant)


def test_page_rejects_javascript_url_with_conflicting_lifecycles():
    with pytest.raises(ValueError, match="both js_dependencies and js_page_modules"):
        Page(
            template_fragment_str="<p>Conflicting JavaScript page</p>",
            js_dependencies=["/static/shared.js"],
            js_page_modules=["/static/shared.js"],
        )


@pytest.mark.parametrize(
    "value, expected",
    [
        ("window.first = true;", ["window.first = true;"]),
        (
            ("window.first = true;", "window.second = true;"),
            ["window.first = true;", "window.second = true;"],
        ),
    ],
)
def test_page_normalizes_js_page_code(value, expected):
    page = Page(
        template_fragment_str="<p>Inline page code</p>",
        js_page_code=value,
    )

    assert page.js_page_code == expected


@pytest.mark.parametrize(
    "value, error, match",
    [
        (123, TypeError, "string, list, or tuple"),
        ([123], TypeError, "entries must be strings"),
        ([""], ValueError, "entries must be non-empty"),
    ],
)
def test_page_validates_js_page_code(value, error, match):
    with pytest.raises(error, match=match):
        Page(
            template_fragment_str="<p>Invalid inline page code</p>",
            js_page_code=value,
        )


@pytest.mark.parametrize(
    "value, error, match",
    [
        (123, TypeError, r"\bscripts\b.*string, list, or tuple"),
        ([123], TypeError, r"\bscripts\b.*entries must be strings"),
        ([""], ValueError, r"\bscripts\b.*entries must be non-empty"),
    ],
)
def test_page_validates_deprecated_scripts_argument(value, error, match):
    with pytest.raises(error, match=match):
        Page(
            template_fragment_str="<p>Invalid legacy scripts</p>",
            scripts=value,
        )


def test_page_supports_deprecated_javascript_arguments():
    with pytest.warns(FutureWarning) as warning_log:
        page = Page(
            template_fragment_str="<p>Legacy JavaScript API</p>",
            js_links=["/static/legacy.js"],
            scripts=["var legacyGlobal = true;"],
            js_page_code="window.managed = true;",
        )

    assert [str(item.message) for item in warning_log] == [
        "js_links is deprecated; migrate to js_dependencies or js_page_modules.",
        "scripts is deprecated; migrate to js_page_code.",
    ]
    assert page.legacy_js_links == ["/static/legacy.js"]
    assert page.legacy_scripts == ["var legacyGlobal = true;"]
    assert page.js_page_code == ["window.managed = true;"]
    assert page.requires_full_page_reload is True


def test_empty_deprecated_javascript_arguments_do_not_warn():
    with warnings.catch_warnings(record=True) as warning_log:
        warnings.simplefilter("always")
        page = Page(
            template_fragment_str="<p>Empty legacy JavaScript API</p>",
            js_links=[],
            scripts=[],
        )

    assert warning_log == []
    assert page.legacy_js_links == []
    assert page.legacy_scripts == []
    assert page.js_page_code == []
    assert page.requires_full_page_reload is False


def test_legacy_js_links_alone_force_full_reload():
    with pytest.warns(FutureWarning, match="js_links is deprecated"):
        page = Page(
            template_fragment_str="<p>Legacy links only</p>",
            js_links=["/static/legacy.js"],
        )

    assert page.requires_full_page_reload is True
    assert page.legacy_js_links == ["/static/legacy.js"]
    assert page.legacy_scripts == []
    assert page.js_page_code == []


def test_wait_page_gates_auto_advance_on_page_ready():
    from psynet.page import WaitPage

    page = WaitPage(
        wait_time=1.5,
        js_page_code="window.afterWaitSetup = true;",
    )

    assert page.js_page_code[0] == (
        'trial.onEvent("pageReady", () => {\n'
        "    trial.setTimer(() => psynet.nextPage(), 1500);\n"
        "});"
    )
    assert page.js_page_code[1] == "window.afterWaitSetup = true;"
    assert "psynet.trial.setTimer" not in page.template_str
    assert "setTimer" not in page.template_str


@pytest.mark.parametrize("pgcode", ["40001", "40P01", "55P03"])
def test_transient_transaction_errors_are_retryable(pgcode):
    from types import SimpleNamespace

    from psynet.experiment import Experiment

    error = SimpleNamespace(orig=SimpleNamespace(pgcode=pgcode))
    assert Experiment._is_transient_transaction_error(error)


def test_other_database_errors_are_not_retryable():
    from types import SimpleNamespace

    from psynet.experiment import Experiment

    error = SimpleNamespace(orig=SimpleNamespace(pgcode="23505"))
    assert not Experiment._is_transient_transaction_error(error)


def test_busy_response_is_retryable_http_503():
    from flask import Flask

    from psynet.experiment import Experiment

    app = Flask(__name__)
    with app.app_context():
        response, status = Experiment.busy_response()

    assert status == 503
    data = response.get_json()
    assert data["status"] == "busy"
    assert data["submission"] == "busy"
    assert "temporarily busy" in data["message"]


def test_html_timeline_lock_timeout_returns_busy_503(monkeypatch):
    import sqlalchemy
    from flask import Flask
    from psycopg2.errors import LockNotAvailable

    from psynet.experiment import Experiment

    err = sqlalchemy.exc.OperationalError("stmt", {}, LockNotAvailable())
    monkeypatch.setattr(
        Experiment,
        "_is_transient_transaction_error",
        classmethod(lambda cls, error: True),
    )
    monkeypatch.setattr(
        "psynet.experiment._set_transaction_lock_timeout", lambda *_args: None
    )
    monkeypatch.setattr(
        "psynet.experiment.get_config",
        lambda: SimpleNamespace(get=lambda _key: 5),
    )

    def raise_lock(*_args, **_kwargs):
        raise err

    monkeypatch.setattr(
        Experiment, "_get_request_participant_from_unique_id", raise_lock
    )
    app = Flask(__name__)
    with app.test_request_context("/timeline?unique_id=worker-1"):
        response = Experiment.route_timeline()

    if isinstance(response, tuple):
        body, status = response
    else:
        body, status = response, response.status_code
    assert status == 503
    assert body.get_json()["status"] == "busy"
    timing = body.headers.get("Server-Timing", "")
    assert "lock;dur=" in timing
    assert "app;dur=" in timing
    assert "page;" not in timing
    assert "barriers;" not in timing
    assert "render;" not in timing


def test_server_timing_clock_closes_only_the_open_phase():
    from psynet.experiment import Experiment

    clock = Experiment._ServerTimingClock()
    clock.close("lock")
    clock.close_open("lock", "page", "barriers", "render")
    assert set(clock.phases) == {"lock", "page"}


def test_timeline_timing_omits_unclosed_phases():
    from flask import Flask, make_response

    from psynet.experiment import Experiment

    app = Flask(__name__)
    with app.app_context():
        response = Experiment._apply_timeline_timing(
            make_response("ok"),
            participant_id=1,
            phases={"lock": 12.0},
            total_ms=100.0,
            mode=None,
        )
    header = response.headers["Server-Timing"]
    assert "lock;dur=12.0" in header
    assert "app;dur=100.0" in header
    assert "page;" not in header
    assert "barriers;" not in header
    assert "render;" not in header


def test_html_timeline_lock_timeout_returns_html_busy_page(monkeypatch):
    import sqlalchemy
    from flask import Flask
    from psycopg2.errors import LockNotAvailable

    from psynet.experiment import Experiment

    err = sqlalchemy.exc.OperationalError("stmt", {}, LockNotAvailable())
    monkeypatch.setattr(
        Experiment,
        "_is_transient_transaction_error",
        classmethod(lambda cls, error: True),
    )
    monkeypatch.setattr(
        "psynet.experiment._set_transaction_lock_timeout", lambda *_args: None
    )
    monkeypatch.setattr(
        "psynet.experiment.get_config",
        lambda: SimpleNamespace(get=lambda _key: 5),
    )

    def raise_lock(*_args, **_kwargs):
        raise err

    monkeypatch.setattr(
        Experiment, "_get_request_participant_from_unique_id", raise_lock
    )
    app = Flask(__name__)
    with app.test_request_context(
        "/timeline?unique_id=worker-1",
        headers={"Accept": "text/html"},
    ):
        response = Experiment.route_timeline()

    if isinstance(response, tuple):
        body, status = response
        html = body.get_data(as_text=True)
    else:
        body, status = response, response.status_code
        html = body.get_data(as_text=True)
    assert status == 503
    assert body.get_json() is None
    assert "temporarily busy" in html
    assert 'http-equiv="refresh"' in html


def test_response_prepare_error_returns_busy_for_transient_lock(monkeypatch):

    import sqlalchemy
    from flask import Flask
    from psycopg2.errors import LockNotAvailable

    from psynet.experiment import Experiment

    class FakeOperationalError(sqlalchemy.exc.OperationalError):
        pass

    err = FakeOperationalError("stmt", {}, LockNotAvailable())
    monkeypatch.setattr(
        Experiment,
        "_is_transient_transaction_error",
        classmethod(lambda cls, error: True),
    )
    app = Flask(__name__)
    with app.app_context():
        response, status = Experiment._handle_response_prepare_error(
            Experiment.__new__(Experiment),
            participant_id=1,
            error=err,
        )
    assert status == 503
    assert response.get_json()["submission"] == "busy"


def test_response_prepare_error_returns_busy_for_any_transient_error(monkeypatch):
    from flask import Flask

    from psynet.experiment import Experiment

    monkeypatch.setattr(
        Experiment,
        "_is_transient_transaction_error",
        classmethod(lambda cls, error: True),
    )
    app = Flask(__name__)
    with app.app_context():
        response, status = Experiment._handle_response_prepare_error(
            Experiment.__new__(Experiment),
            participant_id=1,
            error=RuntimeError("serialization failure"),
        )
    assert status == 503
    assert response.get_json()["submission"] == "busy"


def test_process_response_reraises_transient_lock_errors(monkeypatch):
    from types import SimpleNamespace

    import sqlalchemy

    from psynet.experiment import Experiment

    orig = SimpleNamespace(pgcode="55P03")
    err = sqlalchemy.exc.OperationalError("stmt", {}, orig)
    handled = {}

    class Query:
        def with_for_update(self, **kwargs):
            return self

        def populate_existing(self):
            return self

        def get(self, participant_id):
            return SimpleNamespace(
                id=participant_id,
                page_uuid="page",
                current_trial=None,
            )

    def raise_lock(*args, **kwargs):
        raise err

    exp = Experiment.__new__(Experiment)
    exp.timeline = SimpleNamespace(get_current_elt=raise_lock)
    exp.handle_error = lambda *args, **kwargs: handled.setdefault("called", True)
    monkeypatch.setattr(
        Experiment,
        "_participant_request_query",
        classmethod(lambda cls: Query()),
    )

    with pytest.raises(sqlalchemy.exc.OperationalError):
        exp.process_response(
            participant_id=1,
            raw_answer=None,
            blobs={},
            metadata={},
            page_uuid="page",
            client_ip_address="127.0.0.1",
        )
    assert "called" not in handled


def test_response_render_error_after_commit_does_not_return_busy(monkeypatch):
    from types import SimpleNamespace

    import sqlalchemy
    from psycopg2.errors import LockNotAvailable

    from psynet.experiment import Experiment

    class FakeOperationalError(sqlalchemy.exc.OperationalError):
        pass

    err = FakeOperationalError("stmt", {}, LockNotAvailable())
    monkeypatch.setattr(
        Experiment,
        "_is_transient_transaction_error",
        classmethod(lambda cls, error: True),
    )
    handled = {}
    rolled_back = []

    class FakeExperiment:
        HandledError = type("HandledError", (Exception,), {})

        def handle_error(self, error, **kwargs):
            handled["error"] = error

    class Query:
        def get(self, participant_id):
            assert rolled_back
            return SimpleNamespace(current_trial=None, id=participant_id)

    monkeypatch.setattr(
        "psynet.experiment.db.session.rollback",
        lambda: rolled_back.append(True),
    )
    monkeypatch.setattr(
        "psynet.experiment.Participant.query",
        Query(),
    )
    monkeypatch.setattr(
        "psynet.experiment.error_response",
        lambda **kwargs: ("error-page", 500),
    )
    result = Experiment._handle_response_render_error(
        FakeExperiment(),
        participant_id=1,
        error=err,
    )
    assert result == ("error-page", 500)
    assert "error" in handled
    assert rolled_back == [True]


def test_response_render_error_after_commit_reloads_timeline_when_transient(
    monkeypatch,
):
    from types import SimpleNamespace

    import sqlalchemy
    from psycopg2.errors import LockNotAvailable

    from psynet.experiment import Experiment

    class FakeOperationalError(sqlalchemy.exc.OperationalError):
        pass

    err = FakeOperationalError("stmt", {}, LockNotAvailable())
    monkeypatch.setattr(
        Experiment,
        "_is_transient_transaction_error",
        classmethod(lambda cls, error: True),
    )
    handled = {}
    rolled_back = []
    page = SimpleNamespace()
    page.__json__ = lambda participant: {"attributes": {}}
    participant = SimpleNamespace(id=1, current_trial=None)

    class FakeExperiment:
        HandledError = type("HandledError", (Exception,), {})

        def handle_error(self, error, **kwargs):
            handled["error"] = error

        def _approved_payload(self, participant, page):
            return {"submission": "approved", "page": page.__json__(participant)}

        timeline = SimpleNamespace(get_current_elt=lambda exp, p: page)

    monkeypatch.setattr(
        "psynet.experiment.db.session.rollback",
        lambda: rolled_back.append(True),
    )
    monkeypatch.setattr(
        Experiment,
        "_participant_request_query",
        classmethod(lambda cls: SimpleNamespace(get=lambda pid: participant)),
    )
    monkeypatch.setattr(
        "psynet.experiment.success_response",
        lambda **kwargs: ("reload", kwargs),
    )
    result = Experiment._handle_response_render_error(
        FakeExperiment(),
        participant_id=1,
        error=err,
    )
    assert result[0] == "reload"
    assert result[1]["page"]["attributes"]["requires_full_page_reload"] is True
    assert "error" not in handled
    assert rolled_back == [True]


@pytest.mark.parametrize(
    "timeline",
    [
        "templates/reaction-time-task.html",
        "/static/reaction-time-task.htm",
    ],
)
def test_jspsych_page_rejects_html_timeline_api(timeline):
    with pytest.raises(
        ValueError,
        match=r"(?s)JsPsychPage.*jspsych_html_timeline.*upgrade-to-psynet-14",
    ):
        JsPsychPage(
            "task",
            timeline=timeline,
            time_estimate=1,
            js_dependencies=[],
            css_links=[],
        )


def test_jspsych_page_detects_old_jinja_timeline_template(tmp_path):
    timeline = tmp_path / "timeline.txt"
    timeline.write_text(
        '{% extends "jspsych-page.html" %}\n{% block timeline %}{% endblock %}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"old Jinja timeline template"):
        JsPsychPage(
            "task",
            timeline=str(timeline),
            time_estimate=1,
            js_dependencies=[],
            css_links=[],
        )


def test_jspsych_page_configures_timeline_module():
    page = JsPsychPage(
        "task",
        timeline="/static/reaction-time-task.js",
        time_estimate=1,
        js_dependencies=["/static/jspsych.js"],
        css_links=["/static/jspsych.css"],
        js_vars={"welcome": "Hello"},
    )

    assert page.js_vars == {
        "welcome": "Hello",
        "jspsych_timeline_module": "/static/reaction-time-task.js",
    }
    assert page.js_dependencies == ["/static/jspsych.js"]
    assert page.js_page_modules == ["/static/scripts/jspsych-page.js"]
    assert "<script" not in page.template_str


def test_document_owning_pages_require_full_reload():
    assert Page.requires_full_page_reload is False
    assert JsPsychPage.requires_full_page_reload is True
    assert UnityPage.requires_full_page_reload is True


def test_progress_and_reward_updater_uses_uncached_ajax():
    from importlib import resources

    js = (resources.files("psynet") / "resources/scripts/psynet.js").read_text(
        encoding="utf-8"
    )
    start = js.index("let updateProgressAndReward = function")
    end = js.index(
        "if (psynetTemplateData.flags.dynamicallyUpdateProgressBarAndReward)"
    )
    snippet = js[start:end]
    assert "$.ajax" in snippet
    assert "cache: false" in snippet
    assert "$.get(" not in snippet


def test_hold_resume_busy_retry_schedules_a_queued_wake():
    from importlib import resources

    js = (resources.files("psynet") / "resources/scripts/psynet.js").read_text(
        encoding="utf-8"
    )
    assert "psynet.timelineHoldBusyRetryMs = 250" in js
    assert "psynet.scheduleTimelineHoldBusyRetry" in js
