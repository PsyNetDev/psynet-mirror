"""HTML rendering for experiment audit evidence.

The rendered site is author documentation, not a sandbox. Experiment notebooks,
Markdown reports, and the PsyNet audit templates are trusted. Notebook HTML and
SVG outputs are included as produced, including any scripts they contain, so
viewing an audit in a browser runs that content with the viewer's privileges.
Markdown files are still parsed as Markdown (raw HTML in ``.md`` is not
interpreted). Plotly figures use the notebook MIME bundle plus the vendored
Plotly runtime so interactive plots work offline without depending on a CDN.
"""

from __future__ import annotations

import base64
import binascii
import html
import json
import logging
from collections.abc import Callable, Iterable, Mapping

from markdown_it import MarkdownIt
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound

from psynet.audit.constants import MAX_AUDIT_NOTEBOOK_BYTES
from psynet.audit.model import (
    AuditEvidenceView,
    AuditFile,
    CompletenessItem,
    screenshot_caption,
)

UrlTransform = Callable[[str], str]
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# Rendered notebook cells are larger than their source because syntax
# highlighting and Plotly MIME bundles expand them. Keep notebook previews
# bounded, but do not apply the smaller plain-text artifact limit to them.
_MAX_NOTEBOOK_PREVIEW_BYTES = MAX_AUDIT_NOTEBOOK_BYTES
# Guards against a figure whose authored height would push the rest of the audit
# off the page; taller figures fall back to responsive height.
MAX_PLOTLY_FIGURE_HEIGHT_PX = 4000
MARKDOWN = MarkdownIt(
    "commonmark",
    {
        "html": False,
        "highlight": lambda code, language, attrs="": render_code_block(
            code,
            language,
        ),
    },
).enable(["table", "strikethrough"])

logger = logging.getLogger(__name__)


def safe_section_html(section_id: str, render: Callable[[], str]) -> str:
    """Render section HTML, isolating failures to one section."""

    try:
        return render()
    except Exception:
        logger.exception("Failed to render section %s", section_id)
        return (
            '<p class="section-render-error">'
            f"Failed to render section {html.escape(section_id or 'unknown')}."
            "</p>"
        )


def identity_url(url: str) -> str:
    """Return a URL unchanged."""

    return url


def escape_url(url: str, url_transform: UrlTransform = identity_url) -> str:
    """Escape a transformed URL for use in an HTML attribute."""

    return html.escape(url_transform(url), quote=True)


def render_code_block(code: str, language: str = "") -> str:
    """Render a highlighted code block."""

    try:
        lexer = get_lexer_by_name(language or "text")
    except ClassNotFound:
        lexer = TextLexer()
    formatter = HtmlFormatter(nowrap=True)
    highlighted = highlight(code, lexer, formatter)
    language_class = f" language-{html.escape(language)}" if language else ""
    return f'<pre class="highlight"><code class="{language_class.strip()}">{highlighted}</code></pre>'


def pygments_css() -> str:
    """Return CSS for highlighted code blocks."""

    return HtmlFormatter().get_style_defs(".highlight")


def render_markdown_document(source: str) -> str:
    """Render Markdown to HTML for reports and notebook cells."""

    return MARKDOWN.render(source)


def render_markdown_block(source: str, class_name: str = "attempt-markdown") -> str:
    """Render Markdown wrapped in a dashboard/review content block."""

    return (
        f'<div class="{html.escape(class_name, quote=True)}">'
        f"{render_markdown_document(source)}</div>"
    )


def render_inline_markdown(source: str) -> str:
    """Render Markdown for inline contexts such as timeline descriptions."""

    rendered = render_markdown_document(source).strip()
    if rendered.startswith("<p>") and rendered.endswith("</p>"):
        return rendered[3:-4]
    return rendered


def render_file_grid(
    files: Iterable[AuditFile],
    *,
    empty_message: str,
    grid_class: str = "artifact-grid",
    url_transform: UrlTransform = identity_url,
) -> str:
    """Render audit files as a grid of reusable file cards."""

    file_list = list(files)
    if not file_list:
        return f"<p>{html.escape(empty_message)}</p>"
    cards = "\n".join(
        render_artifact_card(file, url_transform=url_transform) for file in file_list
    )
    return f'<div class="{html.escape(grid_class, quote=True)}">{cards}</div>'


def render_artifact_card(
    artifact: AuditFile,
    *,
    url_transform: UrlTransform = identity_url,
) -> str:
    """Render one artifact as a dashboard-style file card."""

    path = html.escape(artifact.path)
    kind = html.escape(artifact.kind)
    badges = [
        f"<span>{kind}</span>",
        f"<span>{artifact.size_bytes} bytes</span>",
    ]
    if artifact.truncated:
        badges.append("<span>truncated</span>")

    return (
        '<details class="attempt-file">'
        '<summary class="file-header">'
        f"<h3><code>{path}</code></h3>" + "".join(badges) + "</summary>"
        f"{render_file_preview(artifact, url_transform=url_transform)}"
        "</details>"
    )


def render_file_preview(
    artifact: AuditFile,
    *,
    url_transform: UrlTransform = identity_url,
) -> str:
    """Render a typed preview for one experiment audit file."""

    if artifact.content:
        if artifact.kind == "md":
            return (
                '<div class="file-preview markdown-preview">'
                f"{render_markdown_document(strip_first_markdown_heading(artifact.content))}"
                "</div>"
            )
        if artifact.kind == "py":
            return (
                '<div class="file-preview code-preview">'
                f"{render_code_block(artifact.content, 'python')}"
                "</div>"
            )
        return f'<pre class="file-preview"><code>{html.escape(artifact.content)}</code></pre>'

    if not artifact.published:
        note = (
            artifact.publication_note
            or "This artifact is retained in the bundle but not published."
        )
        return f'<p class="file-preview binary-preview">{html.escape(note)}</p>'

    if artifact.url:
        return (
            '<p class="file-preview binary-preview">'
            "Preview is not available. "
            f'<a href="{escape_url(artifact.url, url_transform)}">Open artifact</a>.'
            "</p>"
        )
    return '<p class="file-preview binary-preview">No artifact file published.</p>'


def strip_first_markdown_heading(markdown: str) -> str:
    """Remove one leading H1 heading from a Markdown preview."""

    lines = markdown.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines)


def timeline_value(entry: object, key: str) -> str:
    """Return one value from a dataclass-like or mapping timeline entry."""

    if isinstance(entry, Mapping):
        return str(entry.get(key) or "")
    return str(getattr(entry, key, "") or "")


def render_timeline_list(entries: Iterable[object]) -> str:
    """Render structured timeline entries."""

    items: list[str] = []
    for entry in entries:
        actor = timeline_value(entry, "actor")
        timestamp = timeline_value(entry, "timestamp")
        description = timeline_value(entry, "description")
        actor_class = html.escape(actor, quote=True)
        items.append(
            f'<li class="timeline-entry timeline-entry-{actor_class}">'
            f'<span class="timeline-time">{html.escape(timestamp)}</span>'
            f'<span class="timeline-actor">{html.escape(actor.replace("-", " "))}</span>'
            f'<span class="timeline-description">{render_inline_markdown(description)}</span>'
            "</li>"
        )
    return '<ol class="timeline-list">' + "\n".join(items) + "</ol>"


def render_timeline_section(
    entries: Iterable[object],
    *,
    fallback_markdown: str = "",
    empty_message: str = "No timeline was found for this attempt.",
) -> str:
    """Render a timeline from structured entries with a Markdown fallback."""

    entry_list = list(entries)
    if entry_list:
        return render_timeline_list(entry_list)
    if fallback_markdown:
        return render_markdown_block(
            fallback_markdown, "attempt-markdown timeline-markdown"
        )
    return f"<p>{html.escape(empty_message)}</p>"


def render_json_block(content: object) -> str:
    """Render escaped JSON or metadata text."""

    return f"<pre><code>{html.escape(str(content or ''))}</code></pre>"


def render_participant_video(
    evidence: AuditEvidenceView,
    *,
    url_transform: UrlTransform = identity_url,
) -> str:
    """Render participant video evidence."""

    video = evidence.participant_video
    if video is None:
        return "<p>No participant recording was found.</p>"
    return (
        '<video class="attempt-video" controls preload="metadata">'
        f'<source src="{escape_url(video.url, url_transform)}" type="video/mp4">'
        "Your browser does not support embedded video."
        "</video>"
        f'<p class="artifact-note"><code>{html.escape(video.path)}</code> '
        f"&middot; {video.size_bytes} bytes</p>"
    )


def render_screenshot_gallery(
    evidence: AuditEvidenceView,
    *,
    standalone: bool = False,
    url_transform: UrlTransform = identity_url,
) -> str:
    """Render screenshot evidence.

    Set ``standalone`` when the gallery is its own top-level audit section; the
    enclosing panel then provides the heading.
    """

    if not evidence.screenshots:
        return "<p>No screenshots were found.</p>" if standalone else ""
    figures: list[str] = []
    for index, screenshot in enumerate(evidence.screenshots):
        caption = screenshot_caption(screenshot, evidence.screenshot_captions)
        hidden = " hidden" if index != 0 else ""
        figures.append(
            '<figure class="screenshot-card" data-screenshot-card '
            f'data-screenshot-caption-text="{html.escape(caption, quote=True)}"{hidden}>'
            f'<a href="{escape_url(screenshot.url, url_transform)}" '
            'aria-label="Open full-size screenshot">'
            f'<img src="{escape_url(screenshot.url, url_transform)}" '
            f'alt="{html.escape(caption, quote=True)}">'
            "</a>"
            "</figure>"
        )
    gallery_class = (
        "screenshot-gallery section-standalone" if standalone else "screenshot-gallery"
    )
    header = (
        '<div class="screenshot-gallery-header">'
        '<p class="artifact-note">Targeted participant-facing states captured '
        "with Playwright.</p></div>"
        if standalone
        else '<div class="screenshot-gallery-header">'
        '<h3 id="screenshot-gallery-heading">Screenshot walkthrough</h3>'
        '<p class="artifact-note">Targeted participant-facing states captured '
        "with Playwright.</p></div>"
    )
    labelled_by = "" if standalone else ' aria-labelledby="screenshot-gallery-heading"'
    return (
        f'<section class="{gallery_class}"{labelled_by}>'
        f"{header}"
        '<div class="screenshot-frame">'
        '<div class="screenshot-carousel" data-screenshot-gallery tabindex="0">'
        + "\n".join(figures)
        + "</div>"
        '<div class="screenshot-caption-panel">'
        '<div class="screenshot-controls" aria-label="Screenshot navigation">'
        '<button class="screenshot-nav" type="button" data-screenshot-prev '
        'aria-label="Previous screenshot">&lsaquo;</button>'
        f'<span class="screenshot-counter" data-screenshot-counter>1 / {len(evidence.screenshots)}</span>'
        '<button class="screenshot-nav" type="button" data-screenshot-next '
        'aria-label="Next screenshot">&rsaquo;</button>'
        "</div>"
        '<p class="screenshot-caption" data-screenshot-caption></p>'
        "</div></div></section>"
    )


def first_analysis_file(evidence: AuditEvidenceView) -> AuditFile | None:
    """Return the first available analysis artifact."""

    return evidence.analysis_files[0] if evidence.analysis_files else None


def render_monitor_snapshot(
    evidence: AuditEvidenceView,
    *,
    url_transform: UrlTransform = identity_url,
) -> str:
    """Render a link to the static experimenter dashboard snapshot."""

    monitor = evidence.monitor_file
    if monitor is None:
        return "<p>No monitor snapshot was found.</p>"
    if not monitor.url:
        note = monitor.publication_note or "artifact file is not published"
        return f'<p class="missing-artifact">Monitor snapshot {html.escape(note)}.</p>'
    return (
        '<p><a href="' + escape_url(monitor.url, url_transform) + '">'
        "Open monitor snapshot</a></p>"
        f'<p class="artifact-note"><code>{html.escape(monitor.path)}</code> '
        "&middot; static snapshot of the experimenter dashboard.</p>"
    )


def render_evidence_actions(
    evidence: AuditEvidenceView,
    *,
    url_transform: UrlTransform = identity_url,
) -> str:
    """Render direct evidence artifact links."""

    analysis_file = first_analysis_file(evidence)
    items = [
        evidence_action_item(
            "Monitor snapshot",
            evidence.monitor_file,
            "Open monitor snapshot",
            url_transform,
        ),
        evidence_action_item(
            "Performance result",
            evidence.performance_file,
            "View performance test result",
            url_transform,
        ),
        evidence_action_item(
            "Data export", evidence.data_file, "Download data export", url_transform
        ),
        analysis_action_item(evidence, analysis_file, url_transform),
    ]
    return '<ul class="evidence-actions">' + "\n".join(items) + "</ul>"


def render_data_exports(
    evidence: AuditEvidenceView,
    *,
    url_transform: UrlTransform = identity_url,
) -> str:
    """Render the real-data export download link."""

    items = [
        evidence_action_item(
            "Data export",
            evidence.data_file,
            "Download data export",
            url_transform,
        ),
    ]
    return '<ul class="evidence-actions">' + "\n".join(items) + "</ul>"


def evidence_action_item(
    missing_label: str,
    file: AuditFile | None,
    action: str,
    url_transform: UrlTransform,
) -> str:
    """Render one evidence action item."""

    if file is None:
        return f'<li><span class="missing-artifact">{html.escape(missing_label)} missing</span></li>'
    if not file.url:
        detail = file.publication_note or "artifact file is not published"
        return (
            f'<li><span class="missing-artifact" title="{html.escape(detail, quote=True)}">'
            f"{html.escape(missing_label)} not published</span></li>"
        )
    return f'<li><a href="{escape_url(file.url, url_transform)}">{html.escape(action)}</a></li>'


def analysis_action_item(
    evidence: AuditEvidenceView,
    analysis_file: AuditFile | None,
    url_transform: UrlTransform,
) -> str:
    """Render the analysis evidence action item."""

    if evidence.has_analysis_notebook:
        return '<li><a href="#analysis-notebook">View analysis notebook</a></li>'
    if analysis_file is not None:
        if not analysis_file.url:
            detail = analysis_file.publication_note or "artifact file is not published"
            return (
                '<li><span class="missing-artifact" '
                f'title="{html.escape(detail, quote=True)}">Analysis summary not published</span></li>'
            )
        return (
            f'<li><a href="{escape_url(analysis_file.url, url_transform)}">'
            "View analysis artifact</a></li>"
        )
    return '<li><span class="missing-artifact">Analysis summary missing</span></li>'


def render_notebook_panel(
    notebook_file: AuditFile,
    notebook: dict[str, object],
    *,
    section_id: str,
    heading: str,
    standalone: bool,
    url_transform: UrlTransform = identity_url,
) -> str:
    """Render a bounded preview of one executed notebook."""

    cells = notebook.get("cells") if notebook else []
    if not isinstance(cells, list):
        cells = []
    rendered_cells = []
    preview_bytes = 0
    truncated_preview = bool(notebook_file.truncated)
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        html_cell = render_notebook_cell(cell)
        extra = len(html_cell.encode("utf-8"))
        if rendered_cells and preview_bytes + extra > _MAX_NOTEBOOK_PREVIEW_BYTES:
            truncated_preview = True
            break
        rendered_cells.append(html_cell)
        preview_bytes += extra
    section_class = "analysis-notebook-panel evidence-subsection"
    if standalone:
        section_class += " section-standalone"
    heading_html = "" if standalone else f"<h3>{html.escape(heading)}</h3>"
    truncation_note = (
        '<p class="artifact-note">Notebook preview is truncated; open the raw notebook for the full file.</p>'
        if truncated_preview
        else ""
    )
    preview = (
        "\n".join(rendered_cells)
        if rendered_cells
        else "<p>Notebook preview could not be parsed.</p>"
    )
    return (
        f'<section id="{html.escape(section_id, quote=True)}" class="{section_class}">'
        '<div class="section-heading">'
        f"{heading_html}"
        f'<a href="{escape_url(notebook_file.url, url_transform)}">Open raw notebook</a>'
        "</div>"
        f'<p class="artifact-note">Rendered from <code>{html.escape(notebook_file.path)}</code>.</p>'
        f"{truncation_note}"
        f'<div class="notebook-preview">{preview}</div></section>'
    )


def render_analysis_notebook(
    evidence: AuditEvidenceView,
    *,
    standalone: bool = False,
    url_transform: UrlTransform = identity_url,
) -> str:
    """Render an analysis notebook.

    Set ``standalone`` when the notebook is its own top-level audit section.
    """

    notebook_file = evidence.analysis_notebook_file
    notebook_html = (
        render_notebook_panel(
            notebook_file,
            evidence.analysis_notebook,
            section_id="analysis-notebook",
            heading="Analysis notebook",
            standalone=standalone,
            url_transform=url_transform,
        )
        if notebook_file is not None
        else ("<p>No analysis notebook was found.</p>" if standalone else "")
    )
    supporting = [
        file
        for file in evidence.analysis_files
        if file is not evidence.analysis_notebook_file
    ]
    supporting_html = (
        render_file_grid(
            supporting,
            empty_message="No supporting analysis files.",
            url_transform=url_transform,
        )
        if supporting
        else ""
    )
    export_html = render_file_grid(
        evidence.simulated_export_files,
        empty_message="No simulated export was found.",
        url_transform=url_transform,
    )
    return f"{notebook_html}{supporting_html}{export_html}"


def render_design_simulation(
    evidence: AuditEvidenceView,
    *,
    standalone: bool = True,
    url_transform: UrlTransform = identity_url,
) -> str:
    """Render the optional design-simulation panel.

    A design simulation may contain power analysis and an optional adaptive
    procedure analysis in one executed notebook.
    """

    if not evidence.has_design_simulation:
        return (
            '<p class="missing">No design simulation was included in this audit.</p>'
            if standalone
            else ""
        )

    run_summary = render_simulation_run_summary(evidence.simulation_run)
    notebook_file = evidence.simulation_notebook_file
    if notebook_file is None:
        notebook_html = (
            '<p class="missing">No executed design-simulation notebook was found.</p>'
        )
    else:
        notebook_html = render_notebook_panel(
            notebook_file,
            evidence.simulation_notebook,
            section_id="simulation-notebook",
            heading="Design simulation notebook",
            standalone=standalone,
            url_transform=url_transform,
        )
    supporting = [
        file
        for file in evidence.simulation_files
        if file is not evidence.simulation_notebook_file
    ]
    files_html = (
        render_file_grid(
            supporting,
            empty_message="No supporting design-simulation files.",
            url_transform=url_transform,
        )
        if supporting
        else ""
    )
    return f"{run_summary}{notebook_html}{files_html}"


def render_simulation_run_summary(run: dict[str, object]) -> str:
    """Render key provenance fields from a design-simulation run record."""

    fields = [
        ("Method", run.get("method")),
        ("Command", run.get("command")),
        ("Replicates", run.get("replicates")),
        ("Result rows", run.get("result_row_count")),
        ("Created at", run.get("created_at")),
    ]
    rows = "".join(
        f"<div><dt>{html.escape(label)}</dt><dd>{html.escape(str(value))}</dd></div>"
        for label, value in fields
        if value not in (None, "")
    )
    if not rows:
        return ""
    note = run.get("note")
    note_html = (
        f'<p class="artifact-note">{html.escape(str(note))}</p>'
        if isinstance(note, str) and note
        else ""
    )
    return f'<dl class="metadata-grid attempt-summary">{rows}</dl>{note_html}'


def render_notebook_cell(cell: dict[str, object]) -> str:
    """Render one notebook cell with source and outputs."""

    cell_type = str(cell.get("cell_type") or "raw")
    safe_type = html.escape(cell_type)

    def render_body() -> str:
        source = notebook_text(cell.get("source"))
        if cell_type == "markdown":
            return render_markdown_block(source)
        if cell_type == "code":
            return (
                '<div class="notebook-code">'
                f"{render_code_block(source, 'python')}"
                "</div>"
                f"{render_notebook_outputs(cell.get('outputs'))}"
            )
        return f"<pre><code>{html.escape(source)}</code></pre>"

    body = safe_section_html(f"notebook-cell-{cell_type}", render_body)
    return f'<section class="notebook-cell notebook-cell-{safe_type}">{body}</section>'


def notebook_text(value: object) -> str:
    """Return notebook source or output text as a string."""

    if isinstance(value, list):
        return "".join(str(part) for part in value)
    if isinstance(value, str):
        return value
    return ""


def normalized_png_base64(value: object) -> str:
    """Return normalized PNG base64 for embedding, or empty on invalid payload."""

    cleaned = "".join(notebook_text(value).split())
    if not cleaned:
        return ""
    try:
        decoded = base64.b64decode(cleaned, validate=True)
    except binascii.Error:
        return ""
    if not decoded.startswith(PNG_MAGIC):
        return ""
    return base64.b64encode(decoded).decode("ascii")


def render_notebook_outputs(outputs: object) -> str:
    """Render text, HTML, or SVG outputs from a notebook code cell."""

    if not isinstance(outputs, list) or not outputs:
        return ""
    rendered_outputs: list[str] = []
    for index, output in enumerate(outputs):
        if not isinstance(output, dict):
            continue
        rendered = safe_section_html(
            f"notebook-output-{index}",
            lambda output=output: render_notebook_output(output),
        )
        if rendered:
            rendered_outputs.append(rendered)
    if not rendered_outputs:
        return ""
    return '<div class="notebook-outputs">' + "\n".join(rendered_outputs) + "</div>"


def render_notebook_output(output: dict[str, object]) -> str:
    """Render one notebook output."""

    output_type = output.get("output_type")
    if output_type == "error":
        traceback = notebook_text(output.get("traceback"))
        return (
            f'<pre class="notebook-error"><code>{html.escape(traceback)}</code></pre>'
            if traceback
            else ""
        )

    text = notebook_text(output.get("text"))
    if text:
        return f"<pre><code>{html.escape(text)}</code></pre>"

    data = output.get("data")
    if not isinstance(data, dict):
        return ""
    plotly = data.get("application/vnd.plotly.v1+json")
    if isinstance(plotly, str):
        try:
            plotly = json.loads(plotly)
        except json.JSONDecodeError:
            plotly = None
    if isinstance(plotly, dict):
        return render_plotly_output(plotly)
    svg = notebook_text(data.get("image/svg+xml"))
    if svg:
        return f'<div class="notebook-svg">{svg}</div>'
    png_b64 = normalized_png_base64(data.get("image/png"))
    if png_b64:
        return (
            '<div class="notebook-image">'
            f'<img src="data:image/png;base64,{png_b64}" alt="Notebook image output">'
            "</div>"
        )
    html_output = notebook_text(data.get("text/html"))
    if html_output:
        return f'<div class="notebook-html">{html_output}</div>'
    markdown_output = notebook_text(data.get("text/markdown"))
    if markdown_output:
        return (
            '<div class="notebook-markdown">'
            f"{render_markdown_block(markdown_output)}"
            "</div>"
        )
    plain = notebook_text(data.get("text/plain"))
    if plain:
        return f"<pre><code>{html.escape(plain)}</code></pre>"
    return ""


def render_plotly_output(specification: dict[str, object]) -> str:
    """Render an interactive Plotly notebook MIME bundle.

    Figure JSON is stored as a JSON script and drawn by the vendored Plotly
    runtime. HTML-significant characters are escaped so labels cannot close the
    script element.

    Responsive mode keeps figures as wide as the audit column, but it recomputes
    height from the container as well, which collapses a tall figure to the
    container's minimum height on the first window resize and jams its labels
    together. Pin the container to the authored height so only width responds.
    """

    data = specification.get("data")
    layout = specification.get("layout")
    if not isinstance(data, list) or not isinstance(layout, dict):
        return '<p class="notebook-error">Invalid Plotly figure output.</p>'

    payload = {
        "data": data,
        "layout": layout,
        "config": {
            "displaylogo": False,
            "responsive": True,
        },
    }
    serialized = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    serialized = (
        serialized.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    authored_height = plotly_layout_height(layout)
    height_style = f' style="height:{authored_height}px"' if authored_height else ""
    return (
        '<div class="notebook-plotly">'
        f'<script type="application/json" data-plotly-spec>{serialized}</script>'
        f'<div class="notebook-plotly-target" data-plotly-target{height_style}></div>'
        '<p class="notebook-plotly-error" data-plotly-error hidden>'
        "Interactive plot could not be rendered."
        "</p></div>"
    )


def plotly_layout_height(layout: Mapping[str, object]) -> int | None:
    """Return a figure's authored pixel height, when it declares a usable one."""

    height = layout.get("height")
    if isinstance(height, bool) or not isinstance(height, int | float):
        return None
    if not 0 < height <= MAX_PLOTLY_FIGURE_HEIGHT_PX:
        return None
    return round(height)


def render_performance_result(
    evidence: AuditEvidenceView,
    *,
    standalone: bool = False,
    url_transform: UrlTransform = identity_url,
) -> str:
    """Render performance results when available.

    Set ``standalone`` when the result is its own top-level audit section.
    """

    if evidence.performance_file is None:
        return "<p>No performance test result was found.</p>" if standalone else ""

    section_class = (
        "performance-result section-standalone" if standalone else "performance-result"
    )
    options = render_performance_options(evidence.performance_data.get("options"))
    if not evidence.performance_results:
        return (
            f'<section class="{section_class}">'
            f"{render_performance_header(evidence.performance_file, url_transform, standalone=standalone)}"
            f"{options}"
            '<p class="artifact-note">This performance artifact does not contain '
            "tabular result rows.</p></section>"
        )

    body: list[str] = []
    for row in evidence.performance_results:
        errors = int(row.get("request_errors") or 0) + int(row.get("bot_errors") or 0)
        body.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('n_bots', '')))}</td>"
            f"<td>{html.escape(str(row.get('total_bots_started', '')))}</td>"
            f"<td>{html.escape(str(row.get('bots_succeeded', '')))}</td>"
            f"<td>{html.escape(str(row.get('total_requests', '')))}</td>"
            f"<td>{format_metric(row.get('median_response_time'))}</td>"
            f"<td>{format_metric(row.get('p95_response_time'))}</td>"
            f"<td>{format_metric(row.get('q_delay_p95'))}</td>"
            f"<td>{errors}</td>"
            "</tr>"
        )
    return (
        f'<section class="{section_class}">'
        f"{render_performance_header(evidence.performance_file, url_transform, standalone=standalone)}"
        f"{options}"
        '<div class="performance-table-wrap">'
        '<table class="performance-table"><thead><tr>'
        f"{performance_heading('Concurrent target', 'The target number of bot participants kept active during this load-test run.')}"
        f"{performance_heading('Bots started', 'Total bot participants launched during the run, including replacements started as earlier bots finish.')}"
        f"{performance_heading('Succeeded', 'Bots that completed the experiment successfully during the test window.')}"
        f"{performance_heading('Requests', 'HTTP requests observed for key participant endpoints such as timeline and response routes.')}"
        f"{performance_heading('Resp Med (s)', 'Median HTTP response time, in seconds, for key participant endpoints.')}"
        f"{performance_heading('Resp P95 (s)', '95th percentile HTTP response time, in seconds, for key participant endpoints; higher values show slower tail latency.')}"
        f"{performance_heading('Q P95 all (s)', '95th percentile async-process queue delay across trial makers, when queue metrics are available.')}"
        f"{performance_heading('Errors', 'Request errors plus bot errors recorded during the run.')}"
        "</tr></thead><tbody>" + "\n".join(body) + "</tbody></table></div></section>"
    )


def render_performance_header(
    performance_file: AuditFile,
    url_transform: UrlTransform,
    *,
    standalone: bool = False,
) -> str:
    """Render the performance section header."""

    explanation = (
        '<span class="info-popover-content" role="tooltip">'
        "A performance test starts a local PsyNet server, repeatedly launches automated bot participants, "
        "and records how many complete the experiment, how many requests they make, and how quickly key "
        "pages respond under load."
        "</span>"
    )
    if standalone:
        label = (
            '<div><p class="artifact-note">'
            '<span class="header-popover" tabindex="0">What this measures'
            f"{explanation}</span></p></div>"
        )
    else:
        label = (
            "<div><h3>"
            '<span class="header-popover" tabindex="0">Performance test result'
            f"{explanation}</span></h3></div>"
        )
    return (
        f'<header class="performance-result-header">{label}'
        f'<a href="{escape_url(performance_file.url, url_transform)}">Raw JSON</a></header>'
    )


def render_performance_options(options: object) -> str:
    """Render performance-test options when available."""

    if not isinstance(options, dict):
        return ""
    n_bots = options.get("n_bots_sweep")
    n_bots_text = (
        ", ".join(str(value) for value in n_bots) if isinstance(n_bots, list) else ""
    )
    rows = [
        ("Target concurrent bots", n_bots_text),
        ("Duration", format_minutes(options.get("duration_minutes"))),
        ("Start stagger", format_seconds(options.get("stagger_interval_s"))),
        ("Time factor", str(options.get("time_factor") or "")),
    ]
    return (
        '<dl class="performance-options">'
        + "".join(
            f"<div><dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd></div>"
            for label, value in rows
            if value
        )
        + "</dl>"
    )


def performance_heading(label: str, tooltip: str) -> str:
    """Render a performance table heading with a tooltip."""

    return (
        '<th><span class="header-popover" tabindex="0">'
        f"{html.escape(label)}"
        f'<span class="info-popover-content" role="tooltip">{html.escape(tooltip)}</span>'
        "</span></th>"
    )


def format_metric(value: object) -> str:
    """Format a numeric performance metric."""

    if isinstance(value, int | float) and not isinstance(value, bool):
        return f"{value:.3f}"
    return "N/A"


def format_minutes(value: object) -> str:
    """Format a minute value."""

    if isinstance(value, int | float) and not isinstance(value, bool):
        return f"{value:.2f} min"
    return ""


def format_seconds(value: object) -> str:
    """Format a second value."""

    if isinstance(value, int | float) and not isinstance(value, bool):
        return f"{value:.1f}s"
    return ""


def render_completeness(
    evidence: AuditEvidenceView,
    *,
    extra_items: Iterable[CompletenessItem] = (),
) -> str:
    """Render audit completeness rows."""

    items = [
        f'<li class="{"present" if item.present else "missing"}">'
        f"{html.escape(item.label)} <span>{html.escape(item.detail)}</span></li>"
        for item in [*extra_items, *evidence.completeness]
    ]
    return (
        '<section class="evidence-subsection">'
        "<h2>Audit completeness</h2>"
        '<ul class="artifact-checklist">' + "\n".join(items) + "</ul></section>"
    )


def render_visible_artifacts(
    evidence: AuditEvidenceView,
    *,
    exclude_paths: set[str] | None = None,
    url_transform: UrlTransform = identity_url,
) -> str:
    """Render remaining evidence files."""

    excluded = exclude_paths or set()
    visible_files = [
        file for file in evidence.visible_files if file.path not in excluded
    ]
    return render_file_grid(
        visible_files,
        empty_message="No additional evidence files were found.",
        url_transform=url_transform,
    )


def render_evidence_section(
    evidence: AuditEvidenceView,
    *,
    extra_completeness: Iterable[CompletenessItem] = (),
    include_heading: bool = True,
    include_completeness: bool = True,
    section_id: str | None = "evidence",
    url_transform: UrlTransform = identity_url,
) -> str:
    """Render the main evidence section."""

    heading = "<h2>Evidence</h2>" if include_heading else ""
    section_attributes = (
        f' id="{html.escape(section_id, quote=True)}"' if section_id else ""
    )
    return (
        f"<section{section_attributes}>"
        f"{heading}"
        f"{render_participant_video(evidence, url_transform=url_transform)}"
        f"{render_screenshot_gallery(evidence, url_transform=url_transform)}"
        f"{render_evidence_actions(evidence, url_transform=url_transform)}"
        f"{render_performance_result(evidence, url_transform=url_transform)}"
        f"{render_analysis_notebook(evidence, url_transform=url_transform)}"
        f"{render_completeness(evidence, extra_items=extra_completeness) if include_completeness else ''}"
        "</section>"
    )
