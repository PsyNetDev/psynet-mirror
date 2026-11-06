"""Participant and dashboard templates escape untrusted text."""

import json
from importlib import resources
from types import SimpleNamespace

import pytest
from dominate import tags
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
from markupsafe import Markup, escape

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
                    "base/dashboard.html": layout,
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


def test_graphic_strings_are_written_as_json():
    from psynet.graphics import Image, Path, Text

    value = PAYLOAD + "\\"
    cases = [
        (Text("label", value, x=0, y=0), "paper.text(0, 0, ", ");"),
        (Path("path", value), "paper.path(", ");"),
        (Image("image", value, x=0, y=0, width=1), "psynet.image[", "].url"),
    ]
    for graphic_object, before, after in cases:
        js = graphic_object.js_init[-1]
        start = js.index(before) + len(before)

        assert "</script>" not in js
        assert json.loads(js[start : js.index(after, start)]) == value


def test_browser_detect_script_json_encodes_translations(app, monkeypatch):
    from psynet import utils

    translation = "\"'`${x}</script>"
    monkeypatch.setattr(utils, "get_translator", lambda **_: lambda *_: translation)
    monkeypatch.setitem(app.extensions, utils._PSYNET_JINJA_LOCALES_KEY, {})
    html = render(
        app,
        '{% import "macros/browser-detect.html" as b with context %}{{ b.head() }}',
        experiment=SimpleNamespace(
            psynet_logo=SimpleNamespace(html="<svg></svg>"),
            with_lucid_recruitment=lambda: False,
        ),
    )
    script = html[html.index("var browser = (function") :]
    script = script[: script.index("</script>")]

    assert '"\\"\\u0027`${x}\\u003c/script\\u003e"' in script
    assert "escapeBrowserWarningHtml(browser.name)" in script


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


def test_status_card_chart_container_is_html_but_body_is_escaped(app):
    with app.test_request_context("/"):
        html = app.jinja_env.from_string(
            '{% from "macros/dashboard.html" import make_status_card %}'
            "{{ make_status_card(card) }}"
        ).render(card={"title": "T", "body": PAYLOAD, "chart_id": "respondents"})

    assert "<script>alert(1)" not in html
    assert '<div id="respondents"></div>' in html


def test_free_text_placeholder_is_attribute_escaped(app):
    from psynet.modular_page import RadioButtonControl

    control = RadioButtonControl(
        choices=["a"], show_free_text_option=True, placeholder_text_free_text=PAYLOAD
    )
    html = render(
        app,
        '{% import "macros/control.html" as c %}{{ c.radiobuttons(control) }}',
        control=control,
    )

    assert "<script>alert(1)" not in html
    assert (
        "<input id='free_text_input' placeholder=\"&#34;&#39;&gt;&lt;script&gt;" in html
    )


@pytest.mark.parametrize(
    "control_class",
    ["CheckboxControl", "DropdownControl", "PushButtonControl", "RadioButtonControl"],
)
def test_response_visualizations_keep_markup_labels(control_class):
    from psynet import modular_page

    control = getattr(modular_page, control_class)(
        choices=["a", "b"], labels=[Markup("<b>A</b>"), PAYLOAD]
    )
    html = control.visualize_response(answer="a", response=None, trial=None)

    assert "<b>A</b>" in html
    assert "<script>alert(1)" not in html


def _between(text, start, end):
    text = text[text.index(start) + len(start) :]
    return text[: text.index(end)]


def test_basic_data_dashboard_escapes_data_and_json_encodes_the_url(app):
    from psynet.experiment import get_experiment

    url = "https://x/basic_data?a=1&b='\");alert(1)//"

    class Exp(type(get_experiment())):
        basic_data_url = url

        @classmethod
        def get_basic_data(cls, context=None, **kwargs):
            return [{"answer": PAYLOAD}]

    with app.test_request_context("/"):
        html = Exp.dashboard_data()
    copied = _between(html, "onclick='copyToClipboard(", ")'>Copy data URL")

    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in _between(html, "<pre>", "</pre>")
    assert "'" not in copied
    assert json.loads(copied) == url


def test_timeline_dashboard_module_ids_cannot_close_the_script(app, monkeypatch):
    from psynet.experiment import get_experiment

    experiment = get_experiment()
    module_id = "</script><script>alert(1)//"
    monkeypatch.setattr(experiment.timeline.module_list[0], "id", module_id)
    with app.test_request_context("/"):
        html = experiment.dashboard_timeline()
    modules = _between(html, "window.timelineModules = ", ";\n")

    assert "</script>" not in modules
    assert json.loads(modules)["modules"][0]["id"] == module_id


def test_lucid_dashboard_renders_pandas_data_as_json(app):
    import numpy as np
    import pandas as pd
    from flask import render_template

    from psynet.dashboard.lucid import TEMPLATE_NAME, _json_safe

    data = [
        {
            "rid": "r1",
            "participant_id": np.int64(7),
            "reason": "</script>" + PAYLOAD,
            "value": np.nan,
            "registered_at": pd.Timestamp("2026-01-01"),
            "type": "Terminated",
        }
    ]
    chart = {"data": _json_safe(data), "type2color": {}, "n_bins": np.int64(1)}
    params = {"respondents": {**chart, "x_dict": {}}, "response_per_participant": chart}
    with app.test_request_context("/"):
        html = render_template(TEMPLATE_NAME, title="Lucid", html="", params=params)
    charts = [
        chunk[: chunk.index(";\n")] for chunk in html.split("responseData = ")[1:]
    ]
    response_data = charts[0]

    assert len(charts) == 2 and "</script>" not in "".join(charts)
    assert '"participant_id": 7' in response_data
    assert '"value": NaN' in response_data
    assert '"registered_at": "2026-01-01 00:00:00"' in response_data


def test_participant_dashboard_escapes_the_pseudonym_and_resume_url(app):
    from html import unescape

    from flask import render_template

    participant = SimpleNamespace(
        id=1,
        unique_id="1:a\"'&<b>",
        bonus=None,
        pseudonym=SimpleNamespace(name=PAYLOAD),
    )
    with app.test_request_context("/"):
        html = render_template(
            "dashboard_participant.html",
            participant=participant,
            participants_needing_review=[],
            app_base_url="https://x",
        )
    link = unescape(_between(html, '<a href="', '" target="_blank">'))

    assert json.loads(_between(html, "let url = ", ";\n")) == link
    assert link == "https://x/timeline?unique_id=1%3Aa%22%27%26%3Cb%3E"
    assert f"<td>Pseudonym</td>\n            <td>{escape(PAYLOAD)}</td>" in html
