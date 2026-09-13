import json

from psynet.audit.constants import MAX_AUDIT_NOTEBOOK_BYTES
from psynet.audit.html import (
    render_analysis_notebook,
    render_design_simulation,
    render_evidence_section,
    render_file_grid,
    render_json_block,
    render_markdown_document,
    render_notebook_output,
    render_notebook_panel,
    render_timeline_section,
    safe_section_html,
)
from psynet.audit.model import AuditFile, CompletenessItem, classify_audit_evidence
from psynet.audit.timeline import TimelineEntry


def file(path: str, content: str | None = "") -> AuditFile:
    return AuditFile(
        path=path,
        url=f"artifacts/{path}",
        content=content,
        size_bytes=len(content or ""),
        kind=path.rsplit(".", 1)[-1] if "." in path else "file",
    )


def unpublished_file(path: str) -> AuditFile:
    return AuditFile(
        path=path,
        url="",
        content=None,
        size_bytes=10,
        kind=path.rsplit(".", 1)[-1] if "." in path else "file",
        published=False,
        publication_note="Excluded from publication.",
    )


def test_safe_section_html_returns_body_on_success() -> None:
    html = safe_section_html("plan", lambda: "<p>Plan body</p>")

    assert html == "<p>Plan body</p>"


def test_safe_section_html_returns_fallback_on_failure() -> None:
    def boom() -> str:
        raise RuntimeError("secret internals")

    html = safe_section_html("plan", boom)

    assert 'class="section-render-error"' in html
    assert "Failed to render section plan." in html
    assert "secret internals" not in html


def test_render_evidence_section_uses_shared_dashboard_markup() -> None:
    view = classify_audit_evidence(
        [
            file("participant.mp4", None),
            file("screenshots/01-intro.png", None),
            file(
                "screenshots/manifest.json",
                json.dumps(
                    {"captions": {"screenshots/01-intro.png": "Intro <screen>"}}
                ),
            ),
            file(
                "performance.json",
                json.dumps(
                    {
                        "options": {
                            "n_bots_sweep": [2, 4],
                            "duration_minutes": 1.5,
                            "stagger_interval_s": 0.2,
                            "time_factor": 2,
                        },
                        "results": [
                            {
                                "n_bots": 4,
                                "total_bots_started": 5,
                                "bots_succeeded": 4,
                                "total_requests": 12,
                                "median_response_time": 0.1234,
                                "request_errors": 1,
                                "bot_errors": 2,
                            },
                        ],
                    }
                ),
            ),
            file("monitor.html", "<html></html>"),
            file("data.zip", None),
            file("simulate/analysis/simulated_export/trials.csv", None),
            file(
                "simulate/analysis/analysis.ipynb",
                json.dumps(
                    {
                        "cells": [
                            {
                                "cell_type": "markdown",
                                "source": ["# Analysis\n\nReady."],
                            },
                            {
                                "cell_type": "code",
                                "source": ["print('ok')"],
                                "outputs": [{"text": ["ok\n"]}],
                            },
                        ],
                    }
                ),
            ),
        ]
    )

    html = render_evidence_section(
        view,
        extra_completeness=[CompletenessItem("plan", "PLAN.md", True, "present")],
        include_heading=False,
        section_id=None,
        url_transform=lambda url: f"/{url}",
    )

    assert "<section>" in html
    assert 'src="/artifacts/participant.mp4"' in html
    assert "data-screenshot-gallery" in html
    assert "Intro &lt;screen&gt;" in html
    assert "simulated_export/trials.csv" in html
    assert 'id="analysis-notebook"' in html
    assert "<h1>Analysis</h1>" in html
    assert "<td>0.123</td>" in html
    assert "<td>3</td>" in html
    assert "PLAN.md <span>present</span>" in html


def test_render_evidence_section_marks_unpublished_actions_without_empty_links() -> (
    None
):
    view = classify_audit_evidence(
        [
            unpublished_file("simulate/analysis/simulated_export/trials.csv"),
            unpublished_file("simulate/analysis/summary.html"),
        ]
    )

    html = render_evidence_section(view, include_heading=False, section_id=None)

    assert "trials.csv" in html
    assert "Analysis summary not published" in html
    assert 'href=""' not in html


def test_render_analysis_notebook_lists_supporting_files() -> None:
    view = classify_audit_evidence(
        [
            file("simulate/analysis/analysis.ipynb", "{}"),
            file("simulate/analysis/summary.csv", "metric,value\nrmse,0.2\n"),
            file("simulate/analysis/simulated_export/trials.csv", None),
        ]
    )

    html = render_analysis_notebook(view, standalone=True)

    assert "summary.csv" in html
    assert "simulated_export/trials.csv" in html
    assert html.index("summary.csv") < html.index("simulated_export/trials.csv")


def test_render_design_simulation_reports_absence() -> None:
    view = classify_audit_evidence([file("simulate/analysis/analysis.ipynb", "{}")])

    assert "No design simulation" in render_design_simulation(view)


def test_render_design_simulation_renders_notebook_and_provenance() -> None:
    view = classify_audit_evidence(
        [
            file(
                "simulate/design/simulation.ipynb",
                json.dumps(
                    {
                        "cells": [
                            {
                                "cell_type": "markdown",
                                "source": ["## Precision by design"],
                            }
                        ]
                    }
                ),
            ),
            file(
                "simulate/design/run.json",
                json.dumps(
                    {
                        "method": "precision-estimation",
                        "command": "python -m audit.simulate.design.core",
                        "replicates": 1000,
                    }
                ),
            ),
            file(
                "simulate/design/results.csv",
                "result_id,decision_value\na,0.2\n",
            ),
        ]
    )

    html = render_design_simulation(view)

    assert "precision-estimation" in html
    assert "1000" in html
    assert "Precision by design" in html
    assert "simulate/design/results.csv" in html
    # The notebook is rendered inline, so it should not repeat as a plain file.
    assert not any(
        item.path == "simulate/design/simulation.ipynb" for item in view.visible_files
    )


def test_render_markdown_document_renders_safe_report_markup() -> None:
    html = render_markdown_document(
        "# Report\n\n"
        "Experiment **works** with `psynet test local`.\n\n"
        "- Evidence captured\n"
        "- [Preview](https://example.test/audit)\n\n"
        "```bash\npsynet audit validate\n```\n\n"
        "<script>alert('x')</script>\n"
    )

    assert "<h1>Report</h1>" in html
    assert "<strong>works</strong>" in html
    assert "<code>psynet test local</code>" in html
    assert "<ul>" in html
    assert "<li>Evidence captured</li>" in html
    assert '<a href="https://example.test/audit">Preview</a>' in html
    assert "psynet" in html
    assert "validate" in html
    assert "<script>" not in html
    assert "&lt;script&gt;alert('x')&lt;/script&gt;" in html


def test_shared_section_renderers_cover_files_timeline_and_json() -> None:
    files_html = render_file_grid(
        [file("experiment.py", "print('ok')\n")],
        empty_message="No files.",
        grid_class="file-grid",
    )
    timeline_html = render_timeline_section(
        [
            TimelineEntry("T+00:00:00", "agent-start", "Started **work**.", []),
            {
                "timestamp": "T+00:01:00",
                "actor": "agent-stop",
                "description": "Stopped.",
            },
        ],
    )
    json_html = render_json_block('{"model": "test"}')

    assert 'class="file-grid"' in files_html
    assert "<code>experiment.py</code>" in files_html
    assert "print" in files_html
    assert 'class="timeline-list"' in timeline_html
    assert "Started <strong>work</strong>." in timeline_html
    assert "agent stop" in timeline_html
    assert "{&quot;model&quot;: &quot;test&quot;}" in json_html


def test_render_evidence_section_renders_notebook_rich_outputs() -> None:
    view = classify_audit_evidence(
        [
            file(
                "simulate/analysis/analysis.ipynb",
                json.dumps(
                    {
                        "cells": [
                            {
                                "cell_type": "markdown",
                                "source": ["## Results\n\n- passed"],
                            },
                            {
                                "cell_type": "code",
                                "source": ["display_table()"],
                                "outputs": [
                                    {
                                        "output_type": "execute_result",
                                        "data": {
                                            "text/html": (
                                                "<table><tr><th>n</th></tr>"
                                                "<tr><td>4</td></tr></table>"
                                            ),
                                        },
                                    },
                                    {
                                        "output_type": "display_data",
                                        "data": {
                                            "image/svg+xml": (
                                                '<svg viewBox="0 0 10 10">'
                                                '<circle cx="5" cy="5" r="4" />'
                                                "</svg>"
                                            ),
                                        },
                                    },
                                    {
                                        "output_type": "execute_result",
                                        "data": {"text/plain": "plain result"},
                                    },
                                ],
                            },
                        ],
                    }
                ),
            ),
        ]
    )

    html = render_evidence_section(view, include_heading=False, section_id=None)

    assert "<h2>Results</h2>" in html
    assert "<ul>" in html
    assert "<li>passed</li>" in html
    assert '<div class="notebook-code"><pre class="highlight">' in html
    assert '<div class="notebook-html">' in html
    assert "<table>" in html
    assert "<th>n</th>" in html
    assert "<td>4</td>" in html
    assert '<div class="notebook-svg">' in html
    assert '<svg viewBox="0 0 10 10">' in html
    assert '<circle cx="5" cy="5" r="4" />' in html
    assert "plain result" in html


MATPLOTLIB_SVG = (
    '<svg viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">'
    '<defs><path id="glyph-1" d="M 0 0 L 1 1"/>'
    '<clipPath id="clip-1"><rect x="0" y="0" width="20" height="20"/></clipPath>'
    "</defs>"
    '<g id="axes" clip-path="url(#clip-1)" transform="translate(2 3)">'
    '<path d="M 0 0 L 10 10" style="fill:#ffffff;stroke:#1f77b4;stroke-width:1.5"/>'
    '<use xlink:href="#glyph-1" x="4" y="5"/>'
    "</g></svg>"
)


def test_render_notebook_output_keeps_matplotlib_svg_presentation() -> None:
    html = render_notebook_output(
        {"output_type": "display_data", "data": {"image/svg+xml": MATPLOTLIB_SVG}}
    )

    assert "<defs>" in html
    assert "<clipPath" in html
    assert 'transform="translate(2 3)"' in html
    assert 'clip-path="url(#clip-1)"' in html
    assert "stroke:#1f77b4" in html
    assert 'xlink:href="#glyph-1"' in html


def test_render_notebook_output_renders_plotly_mime_bundle() -> None:
    html = render_notebook_output(
        {
            "output_type": "display_data",
            "data": {
                "application/vnd.plotly.v1+json": {
                    "data": [
                        {
                            "type": "scatter",
                            "x": [1, 2],
                            "y": [3, 4],
                            "name": "</script><script>bad()</script>",
                        }
                    ],
                    "layout": {"title": {"text": "Interactive result"}},
                }
            },
        }
    )

    assert 'class="notebook-plotly"' in html
    assert 'type="application/json" data-plotly-spec' in html
    assert '"type":"scatter"' in html
    assert "Interactive result" in html
    assert "</script><script>bad()" not in html
    assert "\\u003c/script\\u003e" in html
    assert '"responsive":true' in html


def test_render_notebook_output_parses_stringified_plotly_mime_bundle() -> None:
    html = render_notebook_output(
        {
            "output_type": "display_data",
            "data": {
                "application/vnd.plotly.v1+json": json.dumps(
                    {
                        "data": [{"type": "scatter", "x": [1], "y": [2]}],
                        "layout": {"title": {"text": "String figure"}},
                    }
                )
            },
        }
    )

    assert 'class="notebook-plotly"' in html
    assert "String figure" in html


def test_render_notebook_output_preserves_notebook_html_scripts() -> None:
    html = render_notebook_output(
        {
            "output_type": "display_data",
            "data": {
                "text/html": "<div>ok</div><script>window.auditProbe = true</script>"
            },
        }
    )

    assert "<script>window.auditProbe = true</script>" in html


def test_render_plotly_output_pins_an_authored_figure_height() -> None:
    def render(height: object) -> str:
        return render_notebook_output(
            {
                "output_type": "display_data",
                "data": {
                    "application/vnd.plotly.v1+json": {
                        "data": [{"type": "scatter", "x": [1], "y": [2]}],
                        "layout": {"height": height},
                    }
                },
            }
        )

    assert 'data-plotly-target style="height:950px"' in render(950)
    assert "style=" not in render(None)
    assert "style=" not in render("tall")
    assert "style=" not in render(50_000)


def test_render_notebook_output_rejects_invalid_plotly_mime_bundle() -> None:
    html = render_notebook_output(
        {
            "output_type": "display_data",
            "data": {
                "application/vnd.plotly.v1+json": {
                    "data": "not a list",
                    "layout": {},
                }
            },
        }
    )

    assert "Invalid Plotly figure output" in html


def test_render_notebook_output_renders_markdown() -> None:
    html = render_notebook_output(
        {
            "output_type": "display_data",
            "data": {
                "text/markdown": "## Conclusion\n\n**16-item cap** <script>bad()</script>",
                "text/plain": "<IPython.core.display.Markdown object>",
            },
        }
    )

    assert "<h2>Conclusion</h2>" in html
    assert "<strong>16-item cap</strong>" in html
    assert "<script>bad()</script>" not in html
    assert "IPython.core.display.Markdown" not in html


def test_notebook_preview_uses_full_notebook_size_allowance() -> None:
    notebook = {
        "cells": [
            {"cell_type": "code", "source": "", "outputs": [{"text": "x" * 300_000}]},
            {"cell_type": "code", "source": "", "outputs": [{"text": "y" * 100_000}]},
        ]
    }

    rendered = render_notebook_panel(
        file("simulate/design/simulation.ipynb"),
        notebook,
        section_id="power-notebook",
        heading="Power analysis",
        standalone=True,
    )

    assert "x" * 1_000 in rendered
    assert "y" * 1_000 in rendered
    assert "Notebook preview is truncated" not in rendered
    assert MAX_AUDIT_NOTEBOOK_BYTES == 10_000_000


PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def test_render_notebook_output_renders_valid_png() -> None:
    html = render_notebook_output(
        {
            "output_type": "display_data",
            "data": {"image/png": PNG_B64},
        }
    )

    assert '<div class="notebook-image">' in html
    assert 'src="data:image/png;base64,' in html
    assert PNG_B64 in html
    assert 'alt="Notebook image output"' in html


def test_render_notebook_output_renders_valid_png_from_list() -> None:
    html = render_notebook_output(
        {
            "output_type": "display_data",
            "data": {"image/png": [PNG_B64]},
        }
    )

    assert '<div class="notebook-image">' in html
    assert 'src="data:image/png;base64,' in html
    assert PNG_B64 in html


def test_render_notebook_output_rejects_invalid_png_payload() -> None:
    malformed = render_notebook_output(
        {
            "output_type": "display_data",
            "data": {"image/png": "not-valid-base64!!!"},
        }
    )
    non_png = render_notebook_output(
        {
            "output_type": "display_data",
            "data": {"image/png": "aGVsbG8="},
        }
    )
    empty = render_notebook_output(
        {
            "output_type": "display_data",
            "data": {"image/png": "   "},
        }
    )

    assert "notebook-image" not in malformed
    assert "data:image/png;base64," not in malformed
    assert "notebook-image" not in non_png
    assert "data:image/png;base64," not in non_png
    assert empty == ""
