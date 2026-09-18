import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from markupsafe import Markup

from psynet.end import UnsuccessfulEndLogic
from psynet.experiment import Experiment
from psynet.page import InfoPage, SuccessfulEndPage, UnsuccessfulEndPage
from psynet.timeline import (
    AsyncCodeBlock,
    CodeBlock,
    CreditEstimate,
    Elt,
    MediaSpec,
    Page,
    PageMaker,
    Timeline,
    join,
    switch,
    while_loop,
)
from psynet.trial.chain import ChainNode, ChainTrial, ChainTrialMaker
from psynet.utils import DuplicateKeyError


def test_merge_media_spec():
    x = MediaSpec(audio={"stim-0": "stim-0.wav"})
    y = MediaSpec(audio={"stim-1": "stim-1.wav", "stim-2": "stim-2.wav"})
    z = MediaSpec(audio={"stim-1": "stim-1.wav", "stim-2": "stim-2b.wav"})
    q = MediaSpec(audio={"stim-3": "stim-3.wav"})

    with pytest.raises(DuplicateKeyError):
        MediaSpec.merge(x, y, z).data == MediaSpec(
            audio={
                "stim-0": "stim-0.wav",
                "stim-1": "stim-1.wav",
                "stim-2": "stim-2b.wav",
            }
        )

    assert (
        MediaSpec.merge(x, y).data
        == MediaSpec(
            audio={
                "stim-0": "stim-0.wav",
                "stim-1": "stim-1.wav",
                "stim-2": "stim-2.wav",
            }
        ).data
    )

    assert (
        MediaSpec.merge(x, y, q).data
        == MediaSpec(
            audio={
                "stim-0": "stim-0.wav",
                "stim-1": "stim-1.wav",
                "stim-2": "stim-2.wav",
                "stim-3": "stim-3.wav",
            }
        ).data
    )


def test_partial_render_makes_embedded_scripts_inert():
    html = """
    <div id="psynet-timeline-fragment">
      <script src="/static/example.js" data-example="1"></script>
      <script type="application/json">{"example": true}</script>
      <script type="text/html"><div>template</div></script>
      <script type="text/psynet-script">window.deferred = true;</script>
    </div>
    """
    inert_html = Page._make_embedded_scripts_inert(html)

    assert inert_html.count('type="text/psynet-script"') == 2
    assert 'data-example="1"' in inert_html
    assert 'type="application/json"' in inert_html
    assert 'type="text/html"' in inert_html


def test_timeline_template_emits_js_dependencies_as_blocking_head_scripts():
    from psynet import __file__ as psynet_file

    template = (
        Path(psynet_file).parent / "templates" / "timeline-page.html"
    ).read_text()
    assert "{% for src in js_dependencies %}" in template
    assert "data-psynet-load-failed" in template


def test_automatic_trial_waits_for_page_ready():
    page = InfoPage("Automatic trial")

    triggers = {
        event_id: [trigger["triggering_event"] for trigger in event["is_triggered_by"]]
        for event_id, event in page.events.items()
    }

    assert "pageReady" in page.events
    assert triggers["pageReady"] == []
    assert triggers["trialPrepare"] == ["pageReady"]
    assert triggers["trialStart"] == ["trialPrepare"]


def test_manual_trial_waits_for_request_and_page_ready():
    page = InfoPage("Manual trial", start_trial_automatically=False)

    triggers = [
        trigger["triggering_event"]
        for trigger in page.events["trialPrepare"]["is_triggered_by"]
    ]

    assert triggers == ["trialManualRequest", "pageReady"]
    assert page.events["trialPrepare"]["trigger_condition"] == "all"


@pytest.mark.parametrize(
    "html",
    [
        '<script type="module">export const value = 1;</script>',
        '<script type="module" src="/static/widget.js"></script>',
    ],
)
def test_embedded_module_is_rejected(html):
    with pytest.raises(
        ValueError,
        match=r"(?s)error codes: embedded_module.*upgrade-to-psynet-14",
    ):
        Page._check_embedded_script_contract(html)


def test_partial_body_extraction_uses_named_fragment_wrapper():
    html = """
    <html>
      <head>
        <style>.global-template-style { color: rgb(1, 2, 3); }</style>
        <style data-psynet-fragment-style="true">.page-api-style { color: rgb(4, 5, 6); }</style>
        <link rel="stylesheet" href="/static/global-template.css">
        <link rel="stylesheet" href="/static/page-api.css" data-psynet-fragment-stylesheet="true">
      </head>
      <body>
        <template><div>outside fragment</div></template>
        <div id="psynet-timeline-fragment">
          <div id="timeline-header"></div>
          <div id="main-body">
            <template><div>inside fragment</div></template>
            <div id="psynet-fragment-assets">
              <div id="psynet-page-css-links">
                <link rel="stylesheet" href="/static/page-api.css">
              </div>
              <div id="psynet-page-css">
                <style>.page-api-style { color: rgb(4, 5, 6); }</style>
              </div>
            </div>
          </div>
          <nav id="footer"></nav>
          <script id="psynet-template-data" type="application/json">{}</script>
        </div>
        <div id="spinner"></div>
      </body>
    </html>
    """

    fragment = Page._extract_partial_body(html)

    assert "timeline-header" in fragment
    assert "inside fragment" in fragment
    assert "psynet-template-data" in fragment
    assert ".page-api-style" in fragment
    assert "/static/page-api.css" in fragment
    assert fragment.count(".page-api-style") == 1
    assert fragment.count("/static/page-api.css") == 1
    assert ".global-template-style" not in fragment
    assert "/static/global-template.css" not in fragment
    assert "outside fragment" not in fragment
    assert "spinner" not in fragment


def test_partial_body_extraction_requires_named_fragment_wrapper():
    with pytest.raises(ValueError, match="could not find fragment root"):
        Page._extract_partial_body("<div id='main-body'></div>")


def test_partial_fragment_rendering_calls_pre_render_before_render():
    # The inplace /response path must run pre_render() before rendering, mirroring
    # the full /timeline path (get_current_page). Otherwise prompt/control
    # pre_render() hooks are skipped when a page is reached via an inplace
    # transition, which is now the default behavior.
    calls = []
    page = MagicMock()
    page.pre_render.side_effect = lambda: calls.append("pre_render")
    page.render.side_effect = lambda *args, **kwargs: calls.append("render") or "<html>"
    participant = SimpleNamespace(page_uuid="uuid-123")

    payload = Experiment.render_partial_timeline_payload(
        page, experiment=MagicMock(), participant=participant
    )

    assert calls == ["pre_render", "render"]
    assert payload == {"html": "<html>", "page_uuid": "uuid-123"}


def test_template_fragment_input_wraps_main_body_content():
    page = Page(template_fragment_str="<p id='fragment-only'>Fragment content</p>")

    assert page.template_kind == "fragment"
    assert '{% extends "timeline-page.html" %}' in page.template_str
    assert "{% block main_body %}" in page.template_str
    assert "fragment-only" in page.template_str


def test_inplace_transitions_reject_complete_custom_templates():
    page = Page(template_str='{% extends "timeline-page.html" %}')

    with pytest.raises(
        ValueError,
        match=r"(?s)uses HTML/JS that needs a full browser reload between pages \(error codes: complete_template\).*Update this page to support in-place loading:.*upgrading_to_psynet_14\.html.*upgrade-to-psynet-14.*requires_full_page_reload=True",
    ):
        page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_requires_full_page_reload_skips_spa_contract_error():
    page = Page(
        template_str='{% extends "timeline-page.html" %}',
        requires_full_page_reload=True,
    )

    assert page.requires_full_page_reload
    assert page._spa_contract_opt_out
    page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_js_vars_window_collisions_warn_at_construction():
    with pytest.warns(UserWarning, match=r"js_vars keys collide.*'status'"):
        page = Page(
            template_fragment_str="<p>ok</p>",
            js_vars={"status": "in-progress", "color": "blue"},
        )

    assert page.js_vars["status"] == "in-progress"


def test_js_vars_without_window_collisions_do_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        Page(
            template_fragment_str="<p>ok</p>",
            js_vars={"color": "blue", "trial_index": 1},
        )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        page = Page(
            template_fragment_str="<p>ok</p>",
            js_links=["/static/helper.js"],
            scripts=["document.addEventListener('DOMContentLoaded', function () {});"],
        )

    assert page.requires_full_page_reload
    assert not page._spa_contract_opt_out
    with pytest.raises(
        ValueError,
        match=r"error codes: legacy_js_links, legacy_scripts, dom_content_loaded",
    ):
        page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_legacy_js_args_with_explicit_opt_out_skip_spa_error():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        page = Page(
            template_fragment_str="<p>ok</p>",
            js_links=["/static/helper.js"],
            requires_full_page_reload=True,
        )

    assert page._spa_contract_opt_out
    page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_js_page_code_allows_arrow_cleanup_and_ignores_html_like_strings():
    page = Page(
        template_fragment_str="<p>ok</p>",
        js_page_code=[
            """
            window.addEventListener('resize', onResize);
            const label = '<script src="/static/x.js"></script>';
            return () => window.removeEventListener('resize', onResize);
            """
        ],
    )

    page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_js_page_code_allows_named_cleanup_function():
    page = Page(
        template_fragment_str="<p>ok</p>",
        js_page_code=[
            """
            window.addEventListener('resize', onResize);
            return function cleanup() {
                window.removeEventListener('resize', onResize);
            };
            """
        ],
    )

    page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_js_page_code_rejects_non_cleanup_arrow_return_as_cleanup_evidence():
    page = Page(
        template_fragment_str="<p>ok</p>",
        js_page_code=[
            """
            window.addEventListener('resize', onResize);
            return (event) => onResize(event);
            """
        ],
    )

    with pytest.raises(ValueError, match=r"error codes: window_listener_no_cleanup"):
        page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_js_page_code_rejects_window_listener_without_cleanup():
    page = Page(
        template_fragment_str="<p>ok</p>",
        js_page_code=["window.addEventListener('resize', onResize);"],
    )

    with pytest.raises(
        ValueError,
        match=r"(?s)error codes: window_listener_no_cleanup.*"
        r"return \(\) => \{ \.\.\. \}.*"
        r"psynet\.addPageCleanupCallback",
    ):
        page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_js_page_code_allows_add_page_cleanup_callback():
    page = Page(
        template_fragment_str="<p>ok</p>",
        js_page_code=[
            """
            window.addEventListener('resize', onResize);
            psynet.addPageCleanupCallback(function () {
                window.removeEventListener('resize', onResize);
            });
            """
        ],
    )

    page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_legacy_transitions_warn_on_complete_custom_templates():
    page = Page(template_str='{% extends "timeline-page.html" %}')

    with pytest.warns(UserWarning, match=r"error codes: complete_template"):
        page._check_spa_template_contract(inplace_timeline_transitions=False)


def test_inplace_transitions_allow_framework_owned_complete_templates():
    page = Page(
        template_str='{% extends "timeline-page.html" %}',
        framework_owned_template=True,
    )

    page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_inplace_transitions_reject_dom_content_loaded_in_custom_templates():
    page = Page(
        template_fragment_str="""
        <div
            data-script="
                document.addEventListener('DOMContentLoaded', function () {});
            "
        ></div>
        """
    )

    with pytest.raises(
        ValueError,
        match=r"error codes: dom_content_loaded",
    ):
        page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_inplace_transitions_allow_dom_content_loaded_text_in_custom_templates():
    page = Page(template_fragment_str='<div data-hook="DOMContentLoaded"></div>')

    page._check_spa_template_contract(inplace_timeline_transitions=True)


@pytest.mark.parametrize(
    "template_fragment, code",
    [
        (
            "<script>psynet.trial.onEvent('trialConstruct', function () {});</script>",
            "embedded_script",
        ),
        ('<script src="/static/example.js"></script>', "embedded_script"),
        ("<style>.example { color: red; }</style>", "style_tag"),
        ('<link rel="stylesheet" href="/static/example.css">', "stylesheet_link"),
        (
            "<script>window.addEventListener('resize', function () {});</script>",
            "window_listener_no_cleanup",
        ),
    ],
)
def test_inplace_transitions_reject_forbidden_custom_template_content(
    template_fragment, code
):
    page = Page(template_fragment_str=template_fragment)

    with pytest.raises(ValueError, match=rf"error codes: .*{code}"):
        page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_legacy_transitions_warn_on_forbidden_custom_template_content():
    page = Page(template_fragment_str="<style>.example { color: red; }</style>")

    with pytest.warns(UserWarning, match=r"error codes: style_tag"):
        page._check_spa_template_contract(inplace_timeline_transitions=False)


def test_window_event_listener_with_cleanup_evidence_is_allowed():
    page = Page(
        template_fragment_str="""
        <div
            data-script="
                window.addEventListener('resize', onResize);
                psynet.addPageCleanupCallback(function () {});
            "
        ></div>
        """
    )

    page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_managed_page_asset_arguments_are_not_forbidden_template_content():
    page = Page(
        template_fragment_str="<p>Page content</p>",
        css=[".example { color: red; }"],
        css_links=["/static/example.css"],
        js_dependencies=["/static/example-library.js"],
        js_page_modules=["/static/example-page.js"],
    )

    page._check_spa_template_contract(inplace_timeline_transitions=True)


@pytest.mark.parametrize(
    "content, code",
    [
        (
            "<p>Page content</p><style>.example { color: red; }</style>",
            "style_tag",
        ),
        (
            '<p>Page content</p><link rel="stylesheet" href="/static/example.css">',
            "stylesheet_link",
        ),
    ],
)
def test_inplace_transitions_reject_prompt_markup_stylesheets(content, code):
    page = InfoPage(Markup(content))

    with pytest.raises(ValueError, match=rf"error codes: {code}"):
        page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_legacy_transitions_warn_on_prompt_markup_stylesheets():
    page = InfoPage(
        Markup("<p>Page content</p><style>.example { color: red; }</style>")
    )

    with pytest.warns(UserWarning, match=r"error codes: style_tag"):
        page._check_spa_template_contract(inplace_timeline_transitions=False)


def test_inplace_transitions_allow_safe_prompt_markup():
    page = InfoPage(
        Markup('<p><span style="font-weight: bold;">Page content</span></p>')
    )

    page._check_spa_template_contract(inplace_timeline_transitions=True)


def test_framework_owned_templates_skip_forbidden_content_validation():
    page = Page(
        template_str="""
        {% extends "timeline-page.html" %}
        <script>document.addEventListener("DOMContentLoaded", function () {});</script>
        """,
        framework_owned_template=True,
    )

    page._check_spa_template_contract(inplace_timeline_transitions=True)


class CustomTrial(ChainTrial):
    time_estimate = 5


def new_trial_maker(**kwarg):
    args = dict(
        id_="test_trial_maker",
        node_class=ChainNode,
        trial_class=CustomTrial,
        chain_type="across",
        max_nodes_per_chain=10,
        expected_trials_per_participant=5,
        max_trials_per_participant=5,
        chains_per_participant=None,
        chains_per_experiment=5,
        trials_per_node=1,
        balance_across_chains=True,
        check_performance_at_end=False,
        check_performance_every_trial=False,
        recruit_mode="n_trials",
        target_n_participants=None,
    )
    all_args = {**args, **kwarg}
    return ChainTrialMaker(**all_args)


def test_get_trial_maker():
    tm_1 = new_trial_maker(id_="tm-1")
    tm_2 = new_trial_maker(id_="tm-2")
    timeline = Timeline(
        InfoPage("Hello", time_estimate=5),
        tm_1,
        tm_2,
    )
    assert timeline.get_trial_maker("tm-1") == tm_1
    assert timeline.get_trial_maker("tm-2") == tm_2
    assert tm_1 != tm_2


def test_estimate_credit__simple():
    e = [
        InfoPage("", time_estimate=5),
        InfoPage("", time_estimate=2),
        InfoPage("", time_estimate=1),
    ]
    assert CreditEstimate(e).get_max("time") == 8


def test_estimate_credit__switch__bound_reward_true():
    e = switch(
        "test",
        lambda experiment, participant: participant.var.switch,
        {
            "a": InfoPage("", time_estimate=3),
            "b": InfoPage("", time_estimate=7),
            "c": InfoPage("", time_estimate=4),
        },
    )
    assert CreditEstimate(e).get_max("time") == 7


def test_estimate_credit__switch__bound_reward_false():
    e = switch(
        "test",
        lambda experiment, participant: participant.var.switch,
        {
            "a": InfoPage("", time_estimate=3),
            "b": InfoPage("", time_estimate=10),
            "c": InfoPage("", time_estimate=4),
        },
        fix_time_credit=False,
    )
    assert CreditEstimate(e).get_max("time") == 10


def test_estimate_credit__while_loop__switch__bound_reward_true():
    e = while_loop(
        "loop123",
        lambda experiment, participant: experiment.var.not_ready,
        switch(
            "test",
            lambda experiment, participant: participant.var.switch,
            {
                "a": InfoPage("", time_estimate=3),
                "b": InfoPage("", time_estimate=7),
                "c": InfoPage("", time_estimate=4),
            },
        ),
        expected_repetitions=3,
    )
    assert CreditEstimate(e).get_max("time") == 21


def test_estimate_credit__while_loop__switch__bound_reward_false():
    e = while_loop(
        "loop",
        lambda experiment, participant: experiment.var.not_ready,
        switch(
            "test",
            lambda experiment, participant: participant.var.switch,
            {
                "a": InfoPage("", time_estimate=3),
                "b": InfoPage("", time_estimate=10),
                "c": InfoPage("", time_estimate=4),
            },
            fix_time_credit=False,
        ),
        expected_repetitions=5,
    )
    assert CreditEstimate(e).get_max("time") == 50


def test_while_loop_on_timeout_runs_before_failure():
    def on_timeout(participant):
        participant.var.timeout_callback_ran = True

    e = while_loop(
        "loop_with_timeout_callback",
        lambda: True,
        InfoPage("", time_estimate=1),
        expected_repetitions=1,
        max_loop_time=1,
        fail_on_timeout=True,
        on_timeout=on_timeout,
    )

    assert any(
        isinstance(elt, CodeBlock) and isinstance(next_elt, UnsuccessfulEndPage)
        for elt, next_elt in zip(e, e[1:])
    )


def test_switch_with_trial_maker():
    tm_1 = new_trial_maker(id_="tm-1")
    tm_2 = new_trial_maker(id_="tm-2")
    timeline = Timeline(
        switch(
            "test",
            lambda experiment, participant: participant.var.switch,
            {
                "a": tm_1,
                "b": tm_2,
            },
            fix_time_credit=False,
        ),
    )
    assert timeline.get_trial_maker("tm-1") == tm_1
    assert timeline.get_trial_maker("tm-2") == tm_2


def test_join_1():
    page = InfoPage("Test")
    x = join(None, page, None)
    assert isinstance(x, list)
    assert len(x) == 1
    assert x[0] == page


def test_join_accepts_list_input_with_collections():
    def background_task(participant):
        return None

    page = InfoPage("Test")
    async_block = AsyncCodeBlock(background_task, wait=False)
    joined = join([page, async_block, background_task, None])
    assert isinstance(joined, list)
    assert all(isinstance(elt, Elt) for elt in joined)
    assert not any(isinstance(elt, AsyncCodeBlock) for elt in joined)
    assert any(isinstance(elt, CodeBlock) for elt in joined)


def test_lambda_compiles_as_code_block_in_timeline():
    def my_function(participant):
        participant.var.apples = 3

    timeline = Timeline(
        my_function,
    )
    found_lambda = None
    for elt in timeline.all_elts:
        if isinstance(elt, CodeBlock):
            found_lambda = elt
            break
    assert found_lambda is not None
    assert found_lambda.function == my_function


# ---------------------------------------------------------------------------
# Timeline branch tests
# ---------------------------------------------------------------------------


def _make_mock_participant(elt_id=None):
    p = SimpleNamespace(
        elt_id=elt_id if elt_id is not None else ["main", -1],
        elt_id_max=[],
        _in_advance_page=False,
    )
    return p


class TestTimelineBranches:
    def test_default_branches_exist(self):
        t = Timeline(InfoPage("hello", time_estimate=5))
        assert "main" in t.elts
        assert "successful_end" in t.elts
        assert "unsuccessful_end" in t.elts
        assert "rejected_consent" in t.elts

    def test_main_branch_ends_with_successful_end_page(self):
        t = Timeline(InfoPage("hello", time_estimate=5))
        assert isinstance(t.elts["main"][-1], SuccessfulEndPage)

    def test_successful_end_branch_has_four_elements(self):
        t = Timeline(InfoPage("hello", time_estimate=5))
        assert len(t.elts["successful_end"]) == 4

    def test_unsuccessful_end_branch_has_four_elements(self):
        t = Timeline(InfoPage("hello", time_estimate=5))
        assert len(t.elts["unsuccessful_end"]) == 4

    def test_successful_end_branch_structure(self):
        t = Timeline(InfoPage("hello", time_estimate=5))
        branch = t.elts["successful_end"]
        assert isinstance(branch[0], CodeBlock)
        assert isinstance(branch[1], PageMaker)
        assert isinstance(branch[2], CodeBlock)
        assert isinstance(branch[3], PageMaker)

    def test_custom_branch_override(self):
        custom = UnsuccessfulEndLogic()
        t = Timeline(
            InfoPage("hello", time_estimate=5),
            unsuccessful_end=custom,
        )
        assert "unsuccessful_end" in t.elts

    def test_get_participant_branch_initial(self):
        t = Timeline(InfoPage("hello", time_estimate=5))
        p = _make_mock_participant(elt_id=["main", -1])
        assert t.get_participant_branch(p) == "main"

    def test_get_participant_branch_main(self):
        t = Timeline(InfoPage("hello", time_estimate=5))
        p = _make_mock_participant(elt_id=["main", 0])
        assert t.get_participant_branch(p) == "main"

    def test_get_participant_branch_successful_end(self):
        t = Timeline(InfoPage("hello", time_estimate=5))
        p = _make_mock_participant(elt_id=["successful_end", 0])
        assert t.get_participant_branch(p) == "successful_end"

    def test_get_participant_branch_unsuccessful_end(self):
        t = Timeline(InfoPage("hello", time_estimate=5))
        p = _make_mock_participant(elt_id=["unsuccessful_end", 0])
        assert t.get_participant_branch(p) == "unsuccessful_end"

    def test_participant_is_in_end_logic_false_for_main(self):
        t = Timeline(InfoPage("hello", time_estimate=5))
        p = _make_mock_participant(elt_id=["main", 0])
        assert not t.participant_is_in_end_logic(p)

    def test_participant_is_in_end_logic_false_for_initial(self):
        t = Timeline(InfoPage("hello", time_estimate=5))
        p = _make_mock_participant(elt_id=["main", -1])
        assert not t.participant_is_in_end_logic(p)

    def test_participant_is_in_end_logic_true_for_successful_end(self):
        t = Timeline(InfoPage("hello", time_estimate=5))
        p = _make_mock_participant(elt_id=["successful_end", 0])
        assert t.participant_is_in_end_logic(p)

    def test_participant_is_in_end_logic_true_for_unsuccessful_end(self):
        t = Timeline(InfoPage("hello", time_estimate=5))
        p = _make_mock_participant(elt_id=["unsuccessful_end", 0])
        assert t.participant_is_in_end_logic(p)

    def test_redirect_to_branch_sets_elt_id(self):
        t = Timeline(InfoPage("hello", time_estimate=5))
        p = _make_mock_participant(elt_id=["main", 0])
        t.redirect_to_branch(None, p, "unsuccessful_end")
        assert p.elt_id == ["unsuccessful_end", -1]

    def test_redirect_to_unknown_branch_raises(self):
        t = Timeline(InfoPage("hello", time_estimate=5))
        p = _make_mock_participant(elt_id=["main", 0])
        with pytest.raises(ValueError, match="Unknown timeline branch"):
            t.redirect_to_branch(None, p, "nonexistent")

    def test_pending_redirect_sets_branch(self):
        t = Timeline(InfoPage("hello", time_estimate=5))
        p = _make_mock_participant(elt_id=["main", 0])
        p.pending_redirect = "unsuccessful_end"
        # Simulate the pending redirect check at the top of advance_page
        # (full advance_page requires a real experiment context).
        pending = p.pending_redirect
        p.pending_redirect = None
        t.redirect_to_branch(None, p, pending)
        assert p.pending_redirect is None
        assert p.elt_id == ["unsuccessful_end", -1]

    def test_getitem_by_branch_name(self):
        t = Timeline(InfoPage("hello", time_estimate=5))
        assert t["main"] is t.elts["main"]
        assert t["successful_end"] is t.elts["successful_end"]

    def test_elt_ids_include_branch_name(self):
        t = Timeline(InfoPage("hello", time_estimate=5))
        first_main = t.elts["main"][0]
        assert first_main.id == ["main", 0]
        first_end = t.elts["successful_end"][0]
        assert first_end.id == ["successful_end", 0]


def _async_target(participant):
    return None


def _other_async_target(participant):
    return None


def _make_participant(stale_process=None):
    participant = MagicMock()
    participant.id = 42
    participant.awaited_async_code_block_process = stale_process
    return participant


def test_async_code_block_initiate__no_stale_process():
    block = AsyncCodeBlock(_async_target, wait=False)
    code_block = MagicMock(id=["main", 3])
    participant = _make_participant(stale_process=None)
    new_process = MagicMock(name="new_process")

    with patch("psynet.process.WorkerAsyncProcess", return_value=new_process) as ctor:
        block.initiate(participant, code_block=code_block)

    ctor.assert_called_once()
    assert ctor.call_args.kwargs["arguments"]["code_block_id"] == ["main", 3]
    assert participant.awaited_async_code_block_process is new_process


def test_async_code_block_initiate__stores_generated_code_block_id_from_timeline():
    timeline = Timeline(AsyncCodeBlock(_async_target, wait=False))
    code_block = timeline.elts["main"][0]
    participant = _make_participant(stale_process=None)
    new_process = MagicMock(name="new_process")

    assert isinstance(code_block, CodeBlock)
    assert code_block.id == ["main", 0]

    with patch("psynet.process.WorkerAsyncProcess", return_value=new_process) as ctor:
        code_block.consume(MagicMock(), participant)

    ctor.assert_called_once()
    assert ctor.call_args.kwargs["arguments"]["code_block_id"] == code_block.id
    assert participant.awaited_async_code_block_process is new_process


def test_async_code_block_initiate__raises_when_previous_process_still_pending():
    block = AsyncCodeBlock(_async_target, wait=False)
    code_block = MagicMock(id=["main", 3])
    stale = MagicMock(name="stale_process")
    stale.pending = True
    stale.failed = False
    stale.finished = False
    participant = _make_participant(stale_process=stale)

    with patch("psynet.process.WorkerAsyncProcess") as ctor:
        with pytest.raises(RuntimeError, match="already has an async code block"):
            block.initiate(participant, code_block=code_block)

    ctor.assert_not_called()
    assert participant.awaited_async_code_block_process is stale


def test_async_code_block_initiate__waits_for_pending_process_when_waiting(caplog):
    block = AsyncCodeBlock(_async_target, wait=True, expected_wait=1)
    code_block = MagicMock(id=["main", 3])
    stale = MagicMock(name="stale_process")
    stale.id = 99
    stale.pending = True
    stale.failed = False
    stale.finished = False
    stale.arguments = {
        "function": _async_target,
        "code_block_id": ["main", 3],
    }
    participant = _make_participant(stale_process=stale)

    with patch("psynet.process.WorkerAsyncProcess") as ctor:
        with caplog.at_level("WARNING"):
            block.initiate(participant, code_block=code_block)

    ctor.assert_not_called()
    assert participant.awaited_async_code_block_process is stale
    assert any(
        "waiting for the existing process" in record.message
        for record in caplog.records
    ), (
        f"Expected a duplicate-process warning, got: {[r.message for r in caplog.records]}"
    )


def test_async_code_block_initiate__raises_for_different_pending_waited_process():
    block = AsyncCodeBlock(_async_target, wait=True, expected_wait=1)
    code_block = MagicMock(id=["main", 3])
    stale = MagicMock(name="stale_process")
    stale.pending = True
    stale.failed = False
    stale.finished = False
    stale.arguments = {
        "function": _other_async_target,
        "code_block_id": ["main", 3],
    }
    participant = _make_participant(stale_process=stale)

    with patch("psynet.process.WorkerAsyncProcess") as ctor:
        with pytest.raises(RuntimeError, match="already has an async code block"):
            block.initiate(participant, code_block=code_block)

    ctor.assert_not_called()
    assert participant.awaited_async_code_block_process is stale


def test_async_code_block_initiate__raises_for_same_function_different_waited_process():
    block = AsyncCodeBlock(_async_target, wait=True, expected_wait=1)
    code_block = MagicMock(id=["main", 3])
    stale = MagicMock(name="stale_process")
    stale.pending = True
    stale.failed = False
    stale.finished = False
    stale.arguments = {
        "function": _async_target,
        "code_block_id": ["main", 4],
    }
    participant = _make_participant(stale_process=stale)

    with patch("psynet.process.WorkerAsyncProcess") as ctor:
        with pytest.raises(RuntimeError, match="already has an async code block"):
            block.initiate(participant, code_block=code_block)

    ctor.assert_not_called()
    assert participant.awaited_async_code_block_process is stale


@pytest.mark.parametrize(
    "stale_state",
    [
        {"pending": False, "finished": True, "failed": False},
        {"pending": False, "finished": False, "failed": True},
    ],
    ids=["finished", "failed"],
)
def test_async_code_block_initiate__clears_stale_finished_or_failed_process(
    stale_state, caplog
):
    block = AsyncCodeBlock(_async_target, wait=False)
    code_block = MagicMock(id=["main", 3])
    stale = MagicMock(name="stale_process", id=99, **stale_state)
    participant = _make_participant(stale_process=stale)
    new_process = MagicMock(name="new_process")

    with patch("psynet.process.WorkerAsyncProcess", return_value=new_process) as ctor:
        with caplog.at_level("WARNING"):
            block.initiate(participant, code_block=code_block)

    ctor.assert_called_once()
    assert participant.awaited_async_code_block_process is new_process
    assert any("stale reference" in record.message for record in caplog.records), (
        f"Expected a stale-reference warning, got: {[r.message for r in caplog.records]}"
    )
