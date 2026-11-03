"""Participant and dashboard templates escape untrusted text."""

import json
from importlib import resources

import pytest
from dominate import tags
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
from markupsafe import Markup

from psynet.pytest_psynet import path_to_test_experiment

pytestmark = [
    pytest.mark.parametrize(
        "experiment_directory",
        [path_to_test_experiment("timeline")],
        indirect=True,
    ),
    pytest.mark.usefixtures("in_experiment_directory"),
]

PAYLOAD = "\"'><script>alert(1)</script>"


@pytest.fixture
def app(db_session, deployment_info, monkeypatch):
    from dallinger.experiment_server.experiment_server import app

    # Deployments copy PsyNet's templates next to Dallinger's; tests don't.
    layout = (
        "<html>{% block title %}{% endblock %}{% block head %}{% endblock %}"
        "{% block body %}{% endblock %}{% block scripts %}{% endblock %}</html>"
    )
    loader = ChoiceLoader(
        [
            FileSystemLoader(str(resources.files("psynet") / "templates")),
            DictLoader(
                {
                    "base/layout.html": layout,
                    "base/consent.html": layout,
                    "layout.html": layout,
                }
            ),
            app.jinja_loader,
        ]
    )
    monkeypatch.setattr(app, "jinja_loader", loader)
    monkeypatch.setattr(app.jinja_env, "loader", loader)
    return app


def render(app, template, **kwargs):
    from psynet.utils import render_string_with_translations

    with app.test_request_context("/"):
        return render_string_with_translations(template, locale="en", **kwargs)


def test_strings_are_escaped_but_markup_and_dominate_are_not(app):
    html = render(
        app,
        "{{ text }}|{{ markup }}|{{ tag }}|{{ gettext('A <strong>b</strong>') }}",
        text="<b>x</b>",
        markup=Markup("<i>y</i>"),
        tag=tags.p("<z>"),
    )

    assert html == (
        "&lt;b&gt;x&lt;/b&gt;|<i>y</i>|<p>&lt;z&gt;</p>|A <strong>b</strong>"
    )


def test_push_button_labels_escape_strings_and_keep_markup(app):
    from psynet.modular_page import PushButtonControl

    control = PushButtonControl(
        choices=["a", "b"], labels=[PAYLOAD, Markup("<img alt='b'>")]
    )
    html = render(
        app,
        '{% import "macros/control.html" as c %}{{ c.push_buttons(control) }}',
        control=control,
    )

    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img alt='b'>" in html


def test_button_text_escapes_strings_and_keeps_markup(app):
    from psynet.modular_page import Button

    template = '{% import "macros/control.html" as c %}{{ c.generic_button(button) }}'
    plain = render(app, template, button=Button("buttonA", PAYLOAD))
    trusted = render(app, template, button=Button("buttonB", Markup("<kbd>B</kbd>")))

    assert "<script>alert(1)" not in plain
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in plain
    assert "<kbd>B</kbd>" in trusted


def test_graphic_text_is_written_as_json():
    from psynet.graphics import Text

    js = Text("label", PAYLOAD + "\\", x=0, y=0).js_init[-1]

    assert "</script>" not in js
    assert json.loads(js[js.index('"') : js.rindex(")")]) == PAYLOAD + "\\"


@pytest.mark.parametrize(
    "message, expected",
    [
        (PAYLOAD, "&lt;script&gt;alert(1)&lt;/script&gt;"),
        (Markup("<em>Thanks</em>"), "<em>Thanks</em>"),
    ],
)
def test_generic_recruiter_exit_message(app, message, expected):
    from psynet.recruiters import GenericRecruiter

    class Experiment:
        def render_exit_message(self, participant):
            return message

    with app.test_request_context("/"):
        html = GenericRecruiter().exit_response(Experiment(), participant=None)

    assert "<script>alert(1)" not in html
    assert expected in html


def test_error_page_escapes_the_assignment_id(app):
    response = app.test_client().get(
        "/error-page", query_string={"assignment_id": PAYLOAD}
    )

    assert response.status_code == 200
    assert "<script>alert(1)" not in response.text
    assert 'data-assignment-id="&#34;&#39;&gt;&lt;script&gt;' in response.text


@pytest.mark.parametrize(
    "route, redirect_js",
    [
        ("/consent", 'window.location.replace("/start?" + "hitId=h'),
        ("/ad", '"/consent" + "?" + "hitId=h'),
    ],
)
def test_entry_pages_json_encode_the_query_string(app, route, redirect_js):
    query = {"hitId": "h", "assignmentId": "a", "workerId": "w", "x": PAYLOAD}
    response = app.test_client().get(route, query_string=query)

    assert response.status_code == 200
    assert "<script>alert(1)" not in response.text
    assert redirect_js in response.text
    assert "\\u0027" in response.text


def test_lucid_dashboard_cards_escape_termination_reasons(app):
    from psynet.dashboard.lucid import render_msg

    item = render_msg(PAYLOAD, 3, "", "black")
    with app.test_request_context("/"):
        html = app.jinja_env.from_string(
            '{% from "macros/dashboard.html" import make_card %}{{ make_card(card) }}'
        ).render(card={"title": "Reasons", "body": "", "item_list": [item]})

    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<span style='font-weight:bold'>" in html
