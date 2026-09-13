"""
Structural guards for the participant-facing templates.

Both invariants here protect against silent rendering failures that are easy to
reintroduce and hard to spot by eye:

* Jinja emits a child template's top-level output *before* the parent's
  ``<!doctype html>``. Anything emitted that way puts the document into quirks
  mode, which changes percentage heights and the box model across every page.
* Overriding ``{% block stylesheets %}`` without calling ``super()`` silently
  drops the participant theme for that page.
"""

import re
from importlib import resources
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader

TEMPLATES = sorted(Path(str(resources.files("psynet") / "templates")).rglob("*.html"))

# Dashboard pages are experimenter-facing and inherit a different layout.
PARTICIPANT_TEMPLATES = [p for p in TEMPLATES if not p.name.startswith("dashboard")]

EXTENDS = re.compile(r"\{%-?\s*extends\s")
STYLESHEETS_BLOCK = re.compile(
    r"\{%-?\s*block\s+stylesheets\s*-?%\}(.*?)\{%-?\s*endblock", re.S
)


def _top_level_includes(source):
    """Return includes that sit outside any block, i.e. outside the document."""
    depth = 0
    found = []
    for tag in re.finditer(r"\{%-?\s*(\w+)[^%]*?-?%\}", source):
        keyword = tag.group(1)
        if keyword in {"block", "macro", "if", "for", "call", "filter", "with"}:
            depth += 1
        elif keyword.startswith("end"):
            depth = max(depth - 1, 0)
        elif keyword == "include" and depth == 0:
            found.append(tag.group(0))
    return found


@pytest.mark.parametrize("template", PARTICIPANT_TEMPLATES, ids=lambda p: p.name)
def test_no_output_before_doctype(template):
    source = template.read_text(encoding="utf-8")
    if not EXTENDS.search(source):
        return

    includes = _top_level_includes(source)
    assert not includes, (
        f"{template.name} includes {includes} outside a block. Jinja emits this "
        "before the parent's <!doctype html>, which triggers quirks mode. "
        "Move the include inside a block, or import it as a macro."
    )


@pytest.mark.parametrize("template", PARTICIPANT_TEMPLATES, ids=lambda p: p.name)
def test_stylesheets_block_preserves_theme(template):
    source = template.read_text(encoding="utf-8")
    if not EXTENDS.search(source):
        return

    for block in STYLESHEETS_BLOCK.findall(source):
        if "theme.html" in block:
            # The template supplies the theme itself.
            continue
        assert "super()" in block, (
            f"{template.name} overrides the stylesheets block without calling "
            "super(), which drops participant.css for that page."
        )


def test_focus_ring_follows_accent_token():
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    assert "--psynet-focus-ring: 3px solid var(--psynet-accent)" in css


def test_status_colour_tokens_are_defined():
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    for token in (
        "--psynet-danger:",
        "--psynet-danger-hover:",
        "--psynet-danger-active:",
        "--psynet-success:",
        "--psynet-warning:",
    ):
        assert token in css


def test_graphic_vertical_chrome_token_is_defined():
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    assert "--psynet-graphic-vertical-chrome:" in css
    assert "--psynet-graphic-min-size:" in css


def test_theme_loads_layout_script():
    source = (resources.files("psynet") / "templates" / "theme.html").read_text(
        encoding="utf-8"
    )
    assert "scripts/psynet.layout.js" in source


def test_psynet_js_attaches_layout_api():
    js = (resources.files("psynet") / "resources/scripts/psynet.js").read_text(
        encoding="utf-8"
    )
    assert "window.psynet = psynet" in js
    assert "psynet.layout = window.psynetLayout" in js


def test_inline_code_follows_the_theme():
    """Bootstrap's default code colour is pink, which reads as an error."""
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    start = css.index("\ncode {")
    end = css.index("}", start)
    block = css[start:end]
    assert "color: var(--psynet-text)" in block


def test_transient_pages_style_their_spinner():
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    start = css.index(".psynet-activity .spinner-border {")
    end = css.index("}", start)
    block = css[start:end]
    assert "color: var(--psynet-accent)" in block
    assert "width: 2.5rem" in block


def _opening_tag_with_id(source, element_id):
    marker = f'id="{element_id}"'
    start = source.rindex("<", 0, source.index(marker))
    return source[start : source.index(">", source.index(marker)) + 1]


def test_error_recovery_shows_copy_before_javascript():
    source = (resources.files("psynet") / "templates" / "psynet_error.html").read_text(
        encoding="utf-8"
    )

    ready = _opening_tag_with_id(source, "automatic-early-exit-ready")
    pending = _opening_tag_with_id(source, "automatic-early-exit-pending")
    continue_button = _opening_tag_with_id(source, "automatic-early-exit-continue")

    assert "hidden" not in ready
    assert "hidden" in pending
    assert "hidden" in continue_button
    assert 'class="spinner-border"' in source
    assert "Please wait." in source
    assert "saving your responses" not in source.lower()


def test_error_message_is_not_italicized():
    source = (resources.files("psynet") / "templates" / "psynet_error.html").read_text(
        encoding="utf-8"
    )

    assert '<p id="error-text">{{ error_text }}</p>' in source


def test_error_recovery_uses_one_researcher_reference_code():
    source = (resources.files("psynet") / "templates" / "psynet_error.html").read_text(
        encoding="utf-8"
    )

    assert "error_page_presentation.researcher_contact_message" in source
    assert "experiment.error_page_content" not in source
    assert 'href="mailto:' not in source
    assert "quote reference code" not in source
    assert 'data-action="' not in source
    assert "data-preparation-post-url" in source
    assert "data-action-post-url" in source
    assert "data-destination-url" in source
    assert "data-done-message" not in source
    assert "Error type" not in source
    assert "Study ID" not in source
    assert "Worker ID" not in source


def test_generic_exit_calls_its_reference_a_reference_code():
    source = (
        resources.files("psynet") / "templates" / "psynet_exit_recruiter.html"
    ).read_text(encoding="utf-8")

    assert 'pgettext("exit", "Reference code")' in source
    assert "You chose to leave." in source
    assert "{% block title %}" in source
    exit_text = source[
        source.index('id="exit-text"') : source.index("participant_reference")
    ]
    assert 'pgettext("exit", "You may close this page.")' in exit_text
    assert (
        'pgettext("exit", "Your responses have been saved. You may close this page.")'
        in exit_text
    )
    assert exit_text.index("You may close this page.") < exit_text.index(
        "Your responses have been saved"
    )


def test_lucid_exit_page_uses_the_themed_surface():
    source = (
        resources.files("psynet") / "templates" / "exit_recruiter_lucid.html"
    ).read_text(encoding="utf-8")

    assert "{% block title %}" in source
    assert "Returning you to your panel" in source
    assert "psynet-surface" in source
    assert 'class="well"' not in source


def test_media_loading_survives_a_missing_progress_bar():
    """The bar is optional in the DOM, so media loading must not need it.

    A custom template, a page without media, or an in-place swap that has not
    yet reconciled can omit it entirely.
    """
    js = (resources.files("psynet") / "resources/scripts/psynet.js").read_text(
        encoding="utf-8"
    )
    start = js.index("psynet.media.init = async function")
    end = js.index("let initMediaType", start)
    assert "downloadProgress.bar()" not in js[start:end]

    # Everywhere else the element is looked up, the result is checked.
    for use in re.findall(r"bar\.(?:classList|style)\.[^\n]*", js):
        index = js.index(use)
        assert "if (bar !== null)" in js[max(0, index - 250) : index], (
            f"unguarded use: {use}"
        )


def test_media_bar_does_not_animate_through_colours():
    """The gradient splash animation belongs to the wait page, not a 6px bar."""
    js = (resources.files("psynet") / "resources/scripts/psynet.js").read_text(
        encoding="utf-8"
    )
    assert "colorfadeanim" not in js

    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    start = css.index("#media-download-progress-bar {")
    end = css.index("}", start)
    block = css[start:end]
    assert "background-color: var(--psynet-rail-fill)" in block
    assert "background-image" not in block


def test_footer_reserves_the_progress_bar_strip():
    """The bar is out of flow, so its height has to be reserved explicitly."""
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    start = css.index("#footer {")
    end = css.index("}", start)
    block = css[start:end]
    assert "var(--psynet-media-progress-height)" in block


def test_progress_percentage_is_centred_on_the_track():
    """Bootstrap draws it inside the fill, which is too narrow early on."""
    source = (resources.files("psynet") / "templates" / "timeline-page.html").read_text(
        encoding="utf-8"
    )
    start = source.index("{% macro timeline_header()")
    end = source.index("{% endmacro %}", start)
    macro = source[start:end]
    assert 'id="timeline-progress-label"' in macro
    # The label duplicates aria-valuenow, so it is hidden from screen readers.
    assert 'aria-hidden="true"' in macro
    # The bar itself carries no text.
    assert 'style="width:{{ progress_percentage }}%"></div>' in macro

    js = (resources.files("psynet") / "resources/scripts/psynet.js").read_text(
        encoding="utf-8"
    )
    assert '$("#timeline-progress-label").attr("data-progress"' in js
    assert '$("#timeline-progress-bar").text(' not in js

    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    # One opaque pill, same grey as the track, so a single text colour reads
    # over track and fill alike.
    start = css.index("#timeline-progress-label::before {")
    end = css.index("}", start)
    block = css[start:end]
    assert "tabular-nums" in block
    # The pill matches the rail so it only shows once the fill reaches it.
    assert "background-color: var(--psynet-chrome-bg)" in block
    assert "border-radius: 999px" in block
    assert "line-height: var(--psynet-progress-height)" in block
    # No clip-path trickery left over from drawing the label twice.
    assert ".psynet-progress-fill" not in css


def test_media_bar_is_a_thin_rail_at_the_bottom():
    """Its own height token, and pinned to the bottom of the window when there
    is no footer to ride."""
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    start = css.index("#media-download-progress-bar {")
    end = css.index("}", start)
    # Its own token: it carries no label, so it stays thinner than the rail.
    assert "height: var(--psynet-media-progress-height)" in css[start:end]

    start = css.index("#timeline-root > #media-download-progress-bar {")
    end = css.index("}", start)
    block = css[start:end]
    assert "position: fixed" in block
    assert "bottom: 0" in block
    # An over-constrained fixed box keeps `top`, so it must be released.
    assert "top: auto" in block


def test_body_spacing_is_only_for_a_footerless_media_bar():
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    assert "body:has(#footer)" not in css
    assert (
        "body:has(#timeline-root > #media-download-progress-bar:not([hidden]))" in css
    )


def test_media_bar_position_follows_its_template_parent():
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    assert "#footer > #media-download-progress-bar {" in css
    assert "#timeline-root > #media-download-progress-bar {" in css
    assert "body:not(:has(#footer)) #media-download-progress-bar" not in css


def test_every_participant_page_declares_the_viewport():
    """Without it, phones lay out at ~980px and scale down, so text arrives tiny."""
    templates = resources.files("psynet") / "templates"

    macro = (templates / "macros/head.html").read_text(encoding="utf-8")
    assert 'name="viewport"' in macro
    assert "width=device-width" in macro

    # Timeline, exit, abort, and error pages inherit it from the shared layout.
    layout = (templates / "psynet_layout.html").read_text(encoding="utf-8")
    assert "psynet_head.viewport()" in layout

    # These two extend Dallinger's templates instead, so they declare it directly.
    for name in ("ad.html", "consent.html"):
        source = (templates / name).read_text(encoding="utf-8")
        assert "psynet_head.viewport()" in source, name

    # One definition only: a second copy in browser-detect would give timeline
    # pages two viewport metas.
    browser_detect = (templates / "macros/browser-detect.html").read_text(
        encoding="utf-8"
    )
    assert 'name="viewport"' not in browser_detect


def test_footer_is_in_document_flow_at_every_width():
    """The footer follows content without a responsive layout fork."""
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    root_start = css.index("#timeline-root:has(#footer) {")
    root_rules = css[root_start : css.index("}", root_start)]
    assert "display: flex" in root_rules
    assert "flex-direction: column" in root_rules
    assert "min-height: 100dvh" in root_rules

    footer_start = css.index("#footer {")
    footer_rules = css[footer_start : css.index("}", footer_start)]
    assert "position: relative" in footer_rules
    assert "margin-top: auto" in footer_rules

    js = (resources.files("psynet") / "resources/scripts/psynet.layout.js").read_text(
        encoding="utf-8"
    )
    assert "ResizeObserver" not in js
    assert "MutationObserver" not in js
    assert "--psynet-footer-height" not in js


def test_danger_buttons_follow_the_participant_theme():
    """Stock Bootstrap danger red sits outside the theme tokens."""
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    start = css.index(".btn-danger {")
    end = css.index("}", start)
    block = css[start:end]
    assert "--bs-btn-bg: var(--psynet-danger)" in block
    assert "--bs-btn-hover-bg: var(--psynet-danger-hover)" in block
    assert "color-mix" not in block

    start = css.index(".btn-outline-danger {")
    end = css.index("}", start)
    block = css[start:end]
    assert "--bs-btn-color: var(--psynet-danger)" in block
    assert "--bs-btn-hover-bg: var(--psynet-danger-soft)" in block


def test_solid_buttons_have_their_own_fill_token():
    """A button painted the dark-mode accent was the brightest thing on screen."""
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    start = css.index(".btn-primary {")
    end = css.index("}", start)
    block = css[start:end]
    assert "--bs-btn-bg: var(--psynet-accent-solid)" in block
    assert "--bs-btn-color: var(--psynet-accent-solid-contrast)" in block
    # Follows the accent in light mode, and is set explicitly in dark mode.
    assert "--psynet-accent-solid: var(--psynet-accent)" in css
    assert css.count("--psynet-accent-solid:") == 2


def test_footer_needs_no_measured_clearance():
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    assert "--psynet-footer-height" not in css
    assert "--psynet-footer-clearance" not in css
    assert "--psynet-footer-reserved" not in css


def test_vertical_push_buttons_do_not_wrap():
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    start = css.index(".push-button-container--vertical {")
    end = css.index("}", start)
    block = css[start:end]
    assert "flex-wrap: nowrap" in block


def test_push_button_container_grows_with_its_buttons():
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    start = css.index(".push-button-container {")
    end = css.index(".push-button-container--vertical")
    block = css[start:end]
    assert "max-height" not in block
    assert "overflow-y" not in block
    assert "background-color" not in block
    assert "border:" not in block


def test_option_panel_grows_with_its_rows_but_keeps_its_surface():
    """Option rows are white cards, so the panel behind them stays."""
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    start = css.index(".psynet-options {")
    end = css.index(".psynet-options--horizontal")
    block = css[start:end]
    assert "max-height" not in block
    assert "overflow-y" not in block
    assert "background-color: var(--psynet-surface-sunken)" in block


@pytest.mark.parametrize("num_media_files, expected_bars", [(0, 0), (2, 1)])
def test_footerless_timeline_only_renders_progress_for_media(
    num_media_files,
    expected_bars,
):
    from types import SimpleNamespace

    from jinja2 import Environment

    source = (resources.files("psynet") / "templates" / "timeline-page.html").read_text(
        encoding="utf-8"
    )
    start = source.index("{% macro media_download_bar()")
    footer_start = source.index("{% macro timeline_footer()", start)
    end = source.index("{% endmacro %}", footer_start) + len("{% endmacro %}")
    template = Environment(autoescape=True).from_string(
        source[start:end] + "{{ timeline_footer() }}"
    )

    html = template.render(
        config={"show_footer": False, "leave_comments_on_every_page": False},
        experiment=SimpleNamespace(show_reward=False),
        show_early_exit_button=False,
        page=SimpleNamespace(media=SimpleNamespace(num_files=num_media_files)),
        initial_download_progress=40,
    )

    assert html.count('id="footer"') == 0
    assert html.count('id="media-download-progress-bar"') == expected_bars


def test_timeline_footer_keeps_labels_compact_and_explanations_accessible():
    source = (resources.files("psynet") / "templates" / "timeline-page.html").read_text(
        encoding="utf-8"
    )
    start = source.index("{% macro timeline_footer()")
    end = source.index("{% endmacro %}", start)
    macro = source[start:end]

    assert 'id="reward-summary"' in macro
    assert 'aria-describedby="reward-tooltip"' in macro
    assert 'id="reward-tooltip"' in macro
    assert 'id="reward-details"' not in macro
    assert 'id="early-exit-button"' in macro
    assert 'aria-describedby="exit-tooltip"' in macro
    assert 'id="exit-tooltip"' in macro
    assert 'pgettext("timeline_problem", "Leave")' in macro
    # The readout has no border, so a glyph carries the affordance instead.
    assert 'class="psynet-info"' in macro
    assert 'aria-hidden="true"' in macro
    # Its typography comes from #reward-summary, which lines it up with the
    # controls; .footer-text would override the size and is for custom footers.
    assert "footer-text" not in macro


def test_progress_fill_is_its_own_token():
    """A fully saturated accent on the dark rail was the most vivid thing there."""
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    for rule in ("#timeline-header .progress-bar {", "#media-download-progress-bar {"):
        start = css.index(rule)
        end = css.index("}", start)
        assert "background-color: var(--psynet-rail-fill)" in css[start:end]
    # Follows the accent in light mode, dimmed explicitly in dark mode.
    assert "--psynet-rail-fill: var(--psynet-accent)" in css
    assert css.count("--psynet-rail-fill:") == 2


def test_footer_is_chrome_rather_than_content():
    """A white footer read as a stray piece of the content surface."""
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    start = css.index("#footer {")
    end = css.index("}", start)
    assert "background-color: var(--psynet-footer-bg)" in css[start:end]
    # Defined for both colour schemes, so dark mode does not fall back to white.
    assert css.count("--psynet-chrome-bg:") == 2
    assert css.count("--psynet-footer-bg: var(--psynet-chrome-bg)") == 2


def test_progress_rail_and_footer_share_the_chrome_tint():
    """The rail above the page and the footer below it frame the content."""
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    start = css.index("#timeline-header .progress {")
    end = css.index("}", start)
    assert "background-color: var(--psynet-chrome-bg)" in css[start:end]

    # Bootstrap's navbar container spreads three items across the whole window;
    # the footer should share the page's column instead.
    start = css.index("#footer > .container {")
    end = css.index("}", start)
    block = css[start:end]
    assert "max-width: var(--psynet-content-width)" in block
    assert "justify-content: flex-end" in block
    # The reward pushes the controls away; targeting the flex item, not the
    # readout nested inside it.
    assert "> .psynet-tooltip:has(#reward-summary) {" in css


def test_footer_controls_carry_a_visible_boundary():
    """A surface fill on the footer tint is 1.07:1, far below WCAG 1.4.11's 3:1."""
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    for button, token in (
        ("#footer #comment-button {", "--psynet-accent"),
        ("#footer #early-exit-button {", "--psynet-danger"),
    ):
        start = css.index(button)
        end = css.index("}", start)
        block = css[start:end]
        assert f"--bs-btn-border-color: var({token})" in block
        # Hover and active states are set too, or Bootstrap fills them solid.
        assert "--bs-btn-hover-bg" in block
        assert "--bs-btn-active-bg" in block


def _audio_meter_macro():
    source = (resources.files("psynet") / "templates/macros/control.html").read_text(
        encoding="utf-8"
    )
    start = source.index("{% macro audio_meter")
    end = source.index("{% macro audio_meter_calibrate")
    return source[start:end]


def test_audio_meter_layout_is_fluid():
    """A 500px table put the coloured status text off the edge of phones."""
    macro = _audio_meter_macro()
    assert "500px" not in macro
    assert "<canvas" not in macro
    assert 'class="audio-meter"' in macro
    assert 'class="audio-meter__track"' in macro
    assert 'class="audio-meter__fill"' in macro
    assert 'id="audio-meter-text"' in macro
    assert 'class="audio-meter__text"' in macro


def test_audio_meter_theme_wraps_inside_the_viewport():
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    start = css.index(".audio-meter {")
    end = css.index(".audio-meter__track")
    block = css[start:end]
    assert "flex-wrap: wrap" in block
    assert "max-width: 100%" in block
    assert "--psynet-audio-meter-height:" in css
    assert ".audio-meter__fill" in css


def test_jspsych_stage_uses_the_graphic_chrome_token():
    template = (
        resources.files("psynet") / "templates" / "jspsych-page.html"
    ).read_text(encoding="utf-8")
    assert "70vh" not in template
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    start = css.index("#js-psych {")
    end = css.index("}", start)
    assert "var(--psynet-graphic-vertical-chrome)" in css[start:end]


def test_wait_page_fills_space_before_the_footer():
    source = (resources.files("psynet") / "templates" / "wait-page.html").read_text(
        encoding="utf-8"
    )
    assert "#timeline-root:not(:has(#footer))" in source
    assert "var(--psynet-media-progress-height)" in source
    assert "min-height: 0" in source
    assert "--psynet-footer-" not in source


def test_reduced_motion_does_not_freeze_every_animation():
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    start = css.index("@media (prefers-reduced-motion: reduce)")
    block = css[start : start + 600]
    assert ".colorfadeanim" in block
    assert "*," not in block
    assert "*::before" not in block
    assert "!important" not in block


def test_media_bar_is_reconciled_after_the_footer_swap():
    js = (resources.files("psynet") / "resources/scripts/psynet.js").read_text(
        encoding="utf-8"
    )
    assert "psynet.reconcileMediaDownloadBar" in js
    assert "insideNextFooter" not in js
    assert 'optionalIds = ["footer", "early-exit-modal"]' in js


def test_scaffold_description_does_not_promise_a_visible_reward():
    source = (
        resources.files("psynet") / "resources" / "experiment_scripts" / "config.txt"
    ).read_text(encoding="utf-8")
    description = next(
        line for line in source.splitlines() if line.startswith("description = ")
    )
    assert "displayed at the bottom" not in description
    assert "how much money you earn" not in description


def test_percentage_height_probe_restores_inline_height():
    source = (
        resources.files("psynet") / "resources/scripts" / "psynet.layout.js"
    ).read_text(encoding="utf-8")
    start = source.index(
        'const savedHeight = element.style.getPropertyValue("height");'
    )
    end = source.index("const scrollWidth", start)
    block = source[start:end]
    assert "try {" in block
    assert "finally {" in block
    assert 'getPropertyPriority("height")' in block
    assert 'setProperty("height", savedHeight, savedPriority)' in block
    assert "finally" in block[block.index("try") :]


def test_consent_actions_sit_in_document_flow():
    """Agree/decline must not sit in a fixed overlay that hides the last paragraphs."""
    macros = (resources.files("psynet") / "templates/macros/consent.html").read_text(
        encoding="utf-8"
    )
    assert "consent-gradient" not in macros
    assert "Scroll up/down" not in macros
    assert "fixed-bottom" not in macros
    # Agree stays the primary action; decline matches the outlined Exit treatment
    # so a solid red control does not outweigh it.
    assert 'class="btn btn-primary btn-lg"' in macros
    assert 'class="btn btn-outline-danger btn-lg"' in macros
    assert "btn-danger btn-lg" not in macros
    # Custom templates may still call fixed_buttons; it now just renders buttons.
    assert "{% macro fixed_buttons(config) %}" in macros
    assert "{{ buttons(config) }}" in macros

    participant_css = (
        resources.files("psynet") / "resources/css/participant.css"
    ).read_text(encoding="utf-8")
    assert ".consent-gradient" not in participant_css

    consent_css = (resources.files("psynet") / "resources/css/consent.css").read_text(
        encoding="utf-8"
    )
    assert ".consent-gradient" not in consent_css
    assert "font-size: smaller" not in consent_css

    consents = resources.files("psynet") / "templates/consents"
    for path in consents.iterdir():
        if path.suffix != ".html":
            continue
        source = path.read_text(encoding="utf-8")
        assert "fixed_buttons" not in source, path.name
        assert "padding-bottom: 200px" not in source, path.name
        assert "padding-bottom: 100px" not in source, path.name
        assert "consent.buttons(config)" in source, path.name


def test_recruiter_handshake_replaces_history():
    """Back from the timeline should leave PsyNet, not return to Begin or Next."""
    templates = resources.files("psynet") / "templates"
    ad = (templates / "ad.html").read_text(encoding="utf-8")
    consent = (templates / "consent.html").read_text(encoding="utf-8")
    start = (templates / "start.html").read_text(encoding="utf-8")

    assert "window.location.replace(url)" in ad
    assert "window.location = url" not in ad
    assert "window.location.replace('/start?" in consent
    assert "window.location='/start" not in consent
    assert start.count('window.location.replace("/timeline?unique_id="') == 2
    assert 'window.location = "/timeline' not in start


def test_exit_navigation_replaces_the_finished_timeline_in_history():
    """Back from exit must not revive a completed timeline page from history/bfcache."""
    js = (resources.files("psynet") / "resources/scripts/psynet.js").read_text(
        encoding="utf-8"
    )
    assert "psynet.finishAndGoToExit" in js
    assert "window.location.replace(exitRoute)" in js
    assert 'addEventListener("pageshow"' in js
    assert "event.persisted" in js

    experiment_source = (resources.files("psynet") / "experiment.py").read_text(
        encoding="utf-8"
    )
    assert 'path == "/timeline"' in experiment_source
    assert 'response.headers["Cache-Control"] = "no-store"' in experiment_source


def test_footer_exit_uses_an_in_page_confirmation():
    templates = resources.files("psynet") / "templates"
    timeline = (templates / "timeline-page.html").read_text(encoding="utf-8")
    early_exit_macro = (templates / "macros/early_exit.html").read_text(
        encoding="utf-8"
    )
    assert 'from "macros/early_exit.html" import early_exit_modal' in timeline
    assert "early_exit_modal(" in timeline
    # Page.early_exit_available decides whether Leave is on offer, so the
    # modal is only rendered alongside an offer the server will honour.
    assert "{% if early_exit_offer_id %}" in timeline
    assert "{% if show_early_exit_button %}" in timeline
    assert 'id="early-exit-modal"' in early_exit_macro
    assert 'id="early-exit-cancel"' in early_exit_macro
    assert 'id="early-exit-confirm"' in early_exit_macro
    assert early_exit_macro.index('id="early-exit-confirm"') < early_exit_macro.index(
        'id="early-exit-cancel"'
    )
    cancel_button = early_exit_macro[early_exit_macro.index('id="early-exit-cancel"') :]
    assert "btn-passive" in cancel_button.split("</button>", 1)[0]
    assert "btn-primary" not in cancel_button.split("</button>", 1)[0]
    css = (resources.files("psynet") / "resources/css/participant.css").read_text(
        encoding="utf-8"
    )
    start = css.index(".btn-passive {")
    end = css.index("}", start)
    passive_button = css[start:end]
    assert "--bs-btn-bg: var(--psynet-surface)" in passive_button
    assert "--bs-btn-hover-bg: var(--psynet-surface)" in passive_button

    js = (resources.files("psynet") / "resources/scripts/psynet.js").read_text(
        encoding="utf-8"
    )
    early_exit_js = (
        resources.files("psynet") / "resources/scripts/psynet.early-exit.js"
    ).read_text(encoding="utf-8")
    assert "psynet.initEarlyExitButton" in js
    assert "result.release_url" in early_exit_js
    assert '"/execute_early_exit_plan/"' in early_exit_js
    assert 'method: "POST"' in early_exit_js
    assert "plan_id: planId" in early_exit_js
    # Recovery copy is already in the HTML; JS must not hide it on load.
    assert "ready.hidden" not in early_exit_js
    assert "prepared = true" not in early_exit_js
    # A stale offer is refused by the server; retrying it cannot help.
    assert 'result.error_code === "stale_early_exit_offer"' in early_exit_js
    assert "global.location.reload()" in early_exit_js
    assert "data-offer-id=" in early_exit_macro

    experiment_source = (resources.files("psynet") / "experiment.py").read_text(
        encoding="utf-8"
    )
    assert "exit_domain.ExitPlan.from_dict" in experiment_source
    assert 'methods=["POST"]' in experiment_source


def test_shared_early_exit_modal_renders_server_offer_and_actions():
    templates = Path(str(resources.files("psynet") / "templates"))
    environment = Environment(loader=FileSystemLoader(templates))
    template = environment.from_string(
        """
        {% from "macros/early_exit.html" import early_exit_modal %}
        {{ early_exit_modal("assignment-1", "offer-1", confirmation) }}
        """
    )
    confirmation = SimpleNamespace(
        title="Leave without finishing?",
        message="Your responses are saved.",
        confirm_label="Leave",
        cancel_label="Cancel",
    )

    rendered = template.render(confirmation=confirmation)

    assert 'data-offer-id="offer-1"' in rendered
    confirm_start = rendered.index('id="early-exit-confirm"')
    cancel_start = rendered.index('id="early-exit-cancel"')
    assert confirm_start < cancel_start
    assert "Leave" in rendered[confirm_start:cancel_start]
    assert "Cancel" in rendered[cancel_start:]


def test_the_error_page_is_reached_by_get_so_that_it_can_be_reloaded():
    """Tracked failures navigate to /timeline; untracked ones use /error-page."""
    root = resources.files("psynet")

    early_exit = (root / "resources/scripts/psynet.early-exit.js").read_text(
        encoding="utf-8"
    )
    assert "global.psynetErrorPage = { go: goToErrorPage }" in early_exit
    assert '"/timeline?unique_id="' in early_exit
    assert '"/error-page"' in early_exit
    assert 'params.set("participant_id"' not in early_exit
    assert "rejection.html" not in early_exit

    # Known-participant failures all take the reloadable PsyNet path.
    js = (root / "resources/scripts/psynet.js").read_text(encoding="utf-8")
    assert "psynetErrorPage.go" in js
    assert "dallinger.error" not in js

    # Starting a participant is the sole intentional exception until
    # Dallinger returns structured participant-creation error codes.
    start = (root / "templates/start.html").read_text(encoding="utf-8")
    assert "dallinger.error(resp)" in start
    assert not re.search(r"^\s*psynetErrorPage\.go\(", start, re.MULTILINE)
    assert "TODO(Dallinger structured participant errors)" in start


def test_no_page_paints_a_placeholder_logo_before_the_theme_swap():
    """theme.html replaces #adlogo on DOMContentLoaded, so a real src flashes first."""
    templates = resources.files("psynet") / "templates"
    for name in ("ad.html", "consent.html", "psynet_error.html"):
        source = (templates / name).read_text(encoding="utf-8")
        tag = source[source.index('id="adlogo"') :].split(">", 1)[0]
        assert "display: none" in tag, name
        assert "src=" not in tag, name


def test_error_page_automatically_executes_its_server_owned_exit_plan():
    templates = resources.files("psynet") / "templates"
    ad = (templates / "ad.html").read_text(encoding="utf-8")
    error = (templates / "psynet_error.html").read_text(encoding="utf-8")

    assert 'id="abort-button"' not in ad
    assert 'id="automatic-early-exit"' in error
    assert 'id="automatic-early-exit-retry"' in error
    assert 'id="automatic-early-exit-continue"' in error
    assert "An error occurred" in error
    assert "{% block title %}" in error
    assert "error_page_presentation.button_label" in error
    assert "<h2>{{ error_page_presentation.button_label }}</h2>" not in error
    assert 'id="automatic-early-exit-ready"' in error
    assert '<div id="automatic-early-exit-ready"' in error
    assert "error_page_presentation.action_instruction" in error
    assert "Finish session" not in error
    assert 'id="early-exit-modal"' not in error
    # Generic recruitment keeps one useful reference for researcher support,
    # without exposing a block of internal identifiers to every participant.
    assert 'id="error-contact"' in error
    assert 'id="error-identifiers"' not in error
    assert "error_page_presentation.researcher_contact_message" in error
    assert "experiment.error_page_content" not in error
