import pytest
from flask import Flask
from jinja2 import DictLoader
from markupsafe import Markup

from psynet.modular_page import (  # AudioPrompt,; VideoSliderControl,
    Control,
    ModularPage,
    MusicNotationPrompt,
    Prompt,
    PushButtonControl,
    RatingScale,
)

# from importlib import resources


def test_import_templates():
    page_1 = ModularPage("test", Prompt("Hi!"))
    assert page_1.import_external_templates == ""

    class CustomPrompt(Prompt):
        external_template = "my-prompt.html"
        macro = "prompt"

    class CustomControl(Control):
        external_template = "my-control.html"
        macro = "control"

    page_2 = ModularPage("test", CustomPrompt("Hi!"), CustomControl())
    assert (
        page_2.import_external_templates
        == '{% import "my-prompt.html" as custom_prompt with context %} {% import "my-control.html" as custom_control with context %}'
    )


def test_inplace_transitions_reject_forbidden_external_control_template():
    app = Flask(__name__)
    app.jinja_loader = DictLoader(
        {
            "custom-control.html": """
            {% macro control(config) %}
                <button>Continue</button>
                <script>psynet.nextPage();</script>
            {% endmacro %}
            """,
        }
    )

    class CustomControl(Control):
        external_template = "custom-control.html"
        macro = "control"

    page = ModularPage("test", Prompt("Hi!"), CustomControl())

    with app.app_context():
        with pytest.raises(ValueError, match=r"error codes: embedded_script"):
            page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_modular_page_requires_full_page_reload_skips_external_template_errors():
    app = Flask(__name__)
    app.jinja_loader = DictLoader(
        {
            "custom-control.html": """
            {% macro control(config) %}
                <button>Continue</button>
                <script>psynet.nextPage();</script>
            {% endmacro %}
            """,
        }
    )

    class CustomControl(Control):
        external_template = "custom-control.html"
        macro = "control"

    page = ModularPage(
        "test",
        Prompt("Hi!"),
        CustomControl(),
        requires_full_page_reload=True,
    )

    assert page.requires_full_page_reload
    assert page._spa_contract_opt_out
    with app.app_context():
        page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_legacy_transitions_warn_on_forbidden_external_control_template():
    app = Flask(__name__)
    app.jinja_loader = DictLoader(
        {
            "custom-control.html": """
            {% macro control(config) %}
                <style>.control { color: red; }</style>
            {% endmacro %}
            """,
        }
    )

    class CustomControl(Control):
        external_template = "custom-control.html"
        macro = "control"

    page = ModularPage("test", Prompt("Hi!"), CustomControl())

    with app.app_context():
        with pytest.warns(UserWarning, match=r"error codes: style_tag"):
            page._check_spa_template_contract(inplace_timeline_transitions=False)


def test_inplace_transitions_allow_clean_external_templates():
    app = Flask(__name__)
    app.jinja_loader = DictLoader(
        {
            "custom-prompt.html": """
            {% macro prompt(config) %}
                <p>Hello</p>
            {% endmacro %}
            """,
            "custom-control.html": """
            {% macro control(config) %}
                <button>Continue</button>
            {% endmacro %}
            """,
        }
    )

    class CustomPrompt(Prompt):
        external_template = "custom-prompt.html"
        macro = "prompt"

    class CustomControl(Control):
        external_template = "custom-control.html"
        macro = "control"

    page = ModularPage("test", CustomPrompt("Hi!"), CustomControl())

    with app.app_context():
        page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_inplace_transitions_allow_scripts_in_page_content():
    # Page content/prompt Markup may embed <script> tags: PsyNet defers and
    # replays them across in-place transitions (see deferred_page_scripts test
    # experiment). The raw-<script> prohibition applies to author templates, not
    # to page content.
    page = ModularPage(
        "test",
        Prompt(
            Markup(
                "<p>Hi</p>"
                '<script src="/static/example.js"></script>'
                "<script>window.__x = 1;</script>"
            )
        ),
    )

    page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_inplace_transitions_still_reject_style_in_page_content():
    # <style>/<link> in content are still forbidden: unlike scripts, they are
    # not managed by the deferral machinery.
    page = ModularPage("test", Prompt(Markup("<style>.x { color: red; }</style>")))

    with pytest.raises(ValueError, match=r"error codes: style_tag"):
        page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_components_contribute_javascript_assets_and_variables_to_page():
    # Reusable components ship lifecycle-managed modules through component
    # hooks rather than inlining <script> in a template.
    class ScriptedPrompt(Prompt):
        def get_js_page_modules(self):
            return ["/static/prompt-page.js"]

        def get_js_page_code(self):
            return ["window.promptReady = true;"]

        def get_js_vars(self):
            return {"prompt_config": {"colour": "blue"}}

    class ScriptedControl(Control):
        macro = "control"

        def get_js_page_modules(self):
            return ["/static/control-page.js"]

        def get_js_page_code(self):
            return ["window.controlReady = true;"]

        def get_js_vars(self):
            return {"control_config": {"maximum": 10}}

    page = ModularPage(
        "test",
        ScriptedPrompt("Hi!"),
        ScriptedControl(),
        js_vars={"page_config": {"enabled": True}},
    )

    assert page.js_page_modules == [
        "/static/prompt-page.js",
        "/static/control-page.js",
    ]
    assert page.js_page_code == [
        "window.promptReady = true;",
        "window.controlReady = true;",
    ]
    assert page.js_vars["prompt_config"] == {"colour": "blue"}
    assert page.js_vars["control_config"] == {"maximum": 10}
    assert page.js_vars["page_config"] == {"enabled": True}


def test_components_contribute_managed_javascript_lifecycle_resources():
    class ManagedPrompt(Prompt):
        def get_js_dependencies(self):
            return ["/static/prompt-library.js"]

        def get_js_page_modules(self):
            return ["/static/prompt-page.js"]

    class ManagedControl(Control):
        macro = "control"

        def get_js_dependencies(self):
            return ["/static/control-library.js"]

        def get_js_page_modules(self):
            return ["/static/control-page.js"]

    page = ModularPage(
        "test",
        ManagedPrompt("Hi!"),
        ManagedControl(),
        js_dependencies=["/static/page-library.js"],
        js_page_modules=["/static/page.js"],
    )

    assert page.js_dependencies == [
        "/static/prompt-library.js",
        "/static/control-library.js",
        "/static/page-library.js",
    ]
    assert page.js_page_modules == [
        "/static/prompt-page.js",
        "/static/control-page.js",
        "/static/page.js",
    ]


def test_modular_page_accepts_tuple_javascript_resources():
    page = ModularPage(
        "test",
        Prompt("Hi!"),
        js_dependencies=("/static/first-library.js", "/static/second-library.js"),
        js_page_modules=("/static/first-page.js", "/static/second-page.js"),
        js_page_code=("window.first = true;", "window.second = true;"),
    )

    assert page.js_dependencies == [
        "/static/first-library.js",
        "/static/second-library.js",
    ]
    assert page.js_page_modules == [
        "/static/first-page.js",
        "/static/second-page.js",
    ]
    assert page.js_page_code == [
        "window.first = true;",
        "window.second = true;",
    ]


def test_duplicate_component_js_vars_raise():
    class CollidingPrompt(Prompt):
        def get_js_vars(self):
            return {"shared_config": "prompt"}

    class CollidingControl(Control):
        macro = "control"

        def get_js_vars(self):
            return {"shared_config": "control"}

    with pytest.raises(
        ValueError,
        match=("shared_config.*prompt CollidingPrompt.*control CollidingControl"),
    ):
        ModularPage("test", CollidingPrompt("Hi!"), CollidingControl())


def test_page_js_vars_cannot_override_component_js_vars():
    class ConfiguredPrompt(Prompt):
        def get_js_vars(self):
            return {"shared_config": "prompt"}

    with pytest.raises(
        ValueError,
        match="shared_config.*prompt ConfiguredPrompt.*ModularPage js_vars",
    ):
        ModularPage(
            "test",
            ConfiguredPrompt("Hi!"),
            js_vars={"shared_config": "page"},
        )


def test_chatroom_contributes_managed_resources_not_inline_markup():
    from psynet.chatroom import ChatRoom

    page = ModularPage(
        "test",
        Prompt("Hi!"),
        chatroom=ChatRoom(room_id="room-42", show_history=True),
    )

    assert any("#chatroom-widget" in str(c) for c in page.css)
    assert page.js_vars["chatroom_config"] == {
        "room_id": "room-42",
        "channel": "modular_page_chat",
        "show_participants": False,
        "show_history": True,
    }
    assert page.js_page_modules == [
        "/static/packages/psynet/scripts/chatroom-widget.js"
    ]
    # The macro itself must be markup-only (no inline <script>/<style>) so it
    # stays contract-compliant.
    from importlib import resources

    macro = (
        resources.files("psynet")
        .joinpath("templates/macros/chatroom.html")
        .read_text(encoding="utf-8")
    )
    assert "<script" not in macro
    assert "<style" not in macro


def test_omitted_chatroom_does_not_contribute_managed_resources():
    from psynet.chatroom import ChatRoom

    page = ModularPage(
        "test",
        Prompt("Hi!"),
        chatroom=ChatRoom(room_id="room-42"),
        layout=["prompt"],
    )

    assert not any("#chatroom-widget" in str(c) for c in page.css)
    assert "chatroom_config" not in page.js_vars
    assert (
        "/static/packages/psynet/scripts/chatroom-widget.js" not in page.js_page_modules
    )


def test_omitted_prompt_does_not_contribute_managed_resources():
    page = ModularPage(
        "test",
        MusicNotationPrompt("C D E F"),
        layout=["control", "buttons"],
    )

    assert page.js_dependencies == []
    assert page.js_page_modules == []
    assert "music_notation_prompt" not in page.js_vars
    assert page.js_vars["modular_page_components"]["prompt"] is None


def test_omitted_prompt_skips_prompt_spa_markup_codes():
    page = ModularPage(
        "test",
        Prompt(Markup("<style>.hidden { color: red; }</style>")),
        layout=["control", "buttons"],
    )

    page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_music_notation_prompt_uses_managed_javascript():
    page = ModularPage(
        "test",
        MusicNotationPrompt("C D E F"),
    )

    assert page.js_dependencies == [
        "/static/packages/psynet/libraries/abc-js/abcjs-basic.js"
    ]
    assert page.js_page_modules == [
        "/static/packages/psynet/scripts/music-notation-prompt.js"
    ]
    assert page.js_vars["music_notation_prompt"] == {"content": "C D E F"}


def test_modular_page_text():
    page = ModularPage("test", Prompt("Hi!"))
    assert page.plain_text == "Hi!"

    # User has provided unescaped HTML, this should be returned as is.
    page = ModularPage("test", Prompt("<strong>Hi!</strong>"))
    assert page.plain_text == "<strong>Hi!</strong>"

    page = ModularPage("test", Prompt(Markup("<strong>Hi!</strong>")))
    assert page.plain_text == "**Hi!**"

    page = ModularPage(
        "test",
        Prompt("Do you want to continue?"),
        PushButtonControl(
            choices=["Yes", "No"],
        ),
    )
    assert page.plain_text == "Do you want to continue?\n- Yes\n- No"


def test_modular_page_metadata():
    page = ModularPage(
        "test",
        Prompt("Hi!"),
        PushButtonControl(
            choices=["Yes", "No"],
        ),
    )
    metadata = page.metadata()
    assert metadata["prompt"] == page.prompt.metadata
    assert metadata["control"] == page.control.metadata


def test_modular_page_accepts_page_css_list():
    page = ModularPage(
        "test",
        Prompt("Hi!"),
        css=[
            "#first-marker { color: rgb(1, 2, 3); }",
            "#second-marker { color: rgb(4, 5, 6); }",
        ],
    )

    assert page.css == [
        "#first-marker { color: rgb(1, 2, 3); }",
        "#second-marker { color: rgb(4, 5, 6); }",
    ]


def test_modular_page_collects_component_css_links():
    class LinkedPrompt(Prompt):
        def get_css_links(self):
            return ["/static/prompt.css"]

    class LinkedControl(PushButtonControl):
        def get_css_links(self):
            return ["/static/control.css"]

    page = ModularPage(
        "test",
        LinkedPrompt("Hi!"),
        LinkedControl(choices=["Yes", "No"]),
        css_links=["/static/page.css"],
    )

    assert page.css_links == [
        "/static/prompt.css",
        "/static/control.css",
        "/static/page.css",
    ]


def test_get_values_and_labels():
    # int input
    values, labels = RatingScale.get_values_and_labels(5)
    assert values == [1, 2, 3, 4, 5]
    assert labels == ["1", "2", "3", "4", "5"]

    # list of floats
    values, labels = RatingScale.get_values_and_labels([0.1, 0.5, 0.9])
    assert values == [0.1, 0.5, 0.9]
    assert labels == ["0.1", "0.5", "0.9"]

    # list of strings
    values, labels = RatingScale.get_values_and_labels(["bad", "neutral", "good"])
    assert values == [1, 2, 3]
    assert labels == ["bad", "neutral", "good"]

    # dict input
    values, labels = RatingScale.get_values_and_labels({"bad": 1, "good": 2})
    assert list(values) == [1, 2]
    assert list(labels) == ["bad", "good"]


def test_prompt_metadata_excludes_text():
    prompt = Prompt("Hi!")
    assert "text" not in prompt.metadata


# The following tests have been disabled because they rely on the iterated singing demo,
# but it has proved tricky to maintain compatibility between the tests and the demo.
# Long-term we should rewrite these.

# @pytest.mark.parametrize("experiment_directory", [path_to_demo("singing_iterated")], indirect=True)
# @pytest.mark.usefixtures("in_experiment_directory")
# def test_visualize_audio_prompt(trial):
#     prompt = AudioPrompt("test.url", "This is the prompt.", play_window=[1, 10])
#     assert (
#         prompt.visualize(trial)
#         == '<p>This is the prompt.</p>\n<audio controls="controls" id="visualize-audio-prompt">\n  <source src="test.url#t=1,10">\n</audio>'
#     )
#
#
# @pytest.mark.parametrize("experiment_directory", [path_to_demo("singing_iterated")], indirect=True)
# @pytest.mark.usefixtures("in_experiment_directory")
# def test_visualize_trial(trial):
#     import psynet.media
#
#     psynet.media.upload_to_local_s3(
#         local_path=resources.files("psynet") / "resources/logo.png",
#         bucket_name="s3-bucket",
#         key="key.png",
#         public_read=True,
#         create_new_bucket=True,
#     )
#     trial.origin.target_url = "target_url"
#     trial.answer = {"s3_bucket": "s3-bucket", "key": "key", "url": "url"}
#     assert (
#         trial.visualization_html
#         == '<div id="trial-visualization">\n  <h3>Prompt</h3>\n  <div id="prompt-visualization" style="background-color: white; padding: 10px; margin-top: 10px; margin-bottom: 10px; border-style: solid; border-width: 1px;"><p>Please sing back the melody to the syllable \'Ta\'.</p>\n<audio controls="controls" id="visualize-audio-prompt">\n  <source src="target_url#t=,">\n</audio></div><br>\n  <h3>Response</h3>\n  <div id="response-visualization" style="background-color: white; padding: 10px; margin-top: 10px; margin-bottom: 10px; border-style: solid; border-width: 1px;"><audio controls="controls" id="visualize-audio-response">\n  <source src="url">\n</audio></div>\n</div><div style="border-style: solid; border-width: 1px;">\n  <img src="/static/s3/s3-bucket/key.png" style="max-width: 100%;">\n</div>'
#     )
#
#     trial.answer = 0.5
#     video_slider_page = ModularPage(
#         "video_slider",
#         prompt="This is an example of a video slider page.",
#         control=VideoSliderControl(
#             url="https://psynet.s3.amazonaws.com/video-slider.mp4",
#             file_type="mp4",
#             width="400px",
#             height="400px",
#             reverse_scale=True,
#             directional=False,
#         ),
#         time_estimate=5,
#     )
#
#     assert (
#         video_slider_page.visualize(trial)
#         == '<div id="trial-visualization">\n  <h3>Prompt</h3>\n  <div id="prompt-visualization" style="background-color: white; padding: 10px; margin-top: 10px; margin-bottom: 10px; border-style: solid; border-width: 1px;"><p>This is an example of a video slider page.</p></div><br>\n  <h3>Response</h3>\n  <div id="response-visualization" style="background-color: white; padding: 10px; margin-top: 10px; margin-bottom: 10px; border-style: solid; border-width: 1px;">\n<div>\n  <p>Answer = 0.5</p>\n  <video controls="controls" id="visualize-video-slider" style="max-width: 400px;">\n    <source src="https://psynet.s3.amazonaws.com/video-slider.mp4">\n  </video>\n</div></div>\n</div>'
#     )
