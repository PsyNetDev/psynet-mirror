import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from psynet.audit.cli import (
    init_audit,
    render_audit_section,
    render_audit_site,
    starter_audit_manifest,
    validate_audit,
)
from psynet.command_line import psynet

LFS_VIDEO_POINTER = (
    b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 1\n"
)


def run_audit_cli(*args: str):
    """Invoke ``psynet audit`` via Click (the supported CLI)."""

    return CliRunner().invoke(psynet, ["audit", *args], catch_exceptions=False)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def audit_manifest() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "created_at": "2026-06-14T13:00:00Z",
        "updated_at": "2026-06-14T13:00:00Z",
        "profile": "psynet.core",
        "extensions": [],
        "experiment": {
            "entry_point": "experiment.py",
        },
        "implementation": {
            "summary": "Compare two tones and report which one is higher.",
        },
        "environment": {
            "os": "linux",
        },
        "sections": [
            {
                "id": "plan",
                "title": "Plan",
                "kind": "markdown",
                "path": "PLAN.md",
            },
            {
                "id": "report",
                "title": "Report",
                "kind": "markdown",
                "path": "REPORT.md",
            },
            {
                "id": "evidence",
                "title": "Evidence",
                "kind": "evidence",
            },
            {
                "id": "files",
                "title": "Additional files",
                "kind": "files",
            },
            {
                "id": "checks",
                "title": "Checks",
                "kind": "checks",
            },
            {
                "id": "blockers",
                "title": "Blockers",
                "kind": "blockers",
            },
        ],
        "artifacts": [
            {
                "id": "debug_log",
                "kind": "log",
                "path": "artifacts/psynet_debug.log",
                "title": "Debug log",
                "description": "Command output from a local PsyNet run.",
                "required": False,
                "status": "present",
                "created_by": "agent",
            },
            {
                "id": "monitor_snapshot",
                "kind": "monitor_snapshot",
                "path": "artifacts/monitor.html",
                "title": "Monitor snapshot",
                "description": "Static monitor snapshot.",
                "required": True,
                "status": "present",
                "created_by": "cli",
            },
            {
                "id": "analysis_notebook",
                "kind": "notebook",
                "path": "analyses/analysis.ipynb",
                "title": "Analysis notebook",
                "description": "Executed analysis notebook.",
                "required": True,
                "status": "blocked",
                "created_by": "agent",
            },
        ],
        "checks": [
            {
                "id": "local_test",
                "title": "PsyNet local test",
                "status": "pass",
                "command": "psynet test local",
            },
        ],
        "blockers": [
            {
                "artifact_id": "analysis_notebook",
                "severity": "warning",
                "reason": "No simulated export has been produced yet.",
                "next_step": "Run psynet simulate and execute the notebook.",
            },
        ],
    }


def write_core_section_files(audit_dir: Path) -> None:
    write(audit_dir / "PLAN.md", "# Plan\n\nUse a chain trial maker.\n")
    write(audit_dir / "REPORT.md", "# Report\n\nReady for review.\n")


def test_render_audit_site_publishes_sanitized_artifacts(tmp_path: Path) -> None:
    audit_dir = tmp_path / "pitch-discrimination-demo" / "audit"
    manifest = audit_manifest()
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")
    write(
        audit_dir / "REPORT.md",
        "# Report\n\n"
        "Experiment **behaves** as expected.\n\n"
        "- Functional check passed\n\n"
        "<script>bad()</script>\n",
    )
    write(audit_dir / "PLAN.md", "# Plan\n\nUse a chain trial maker.\n")
    write(
        audit_dir / "artifacts/psynet_debug.log",
        "Dashboard user: admin password: local-password\n",
    )
    write(
        audit_dir / "artifacts/monitor.html",
        '<!doctype html><html><head><link href="/static/css/dashboard.css"></head>'
        '<body><a href="/dashboard/index">Dashboard</a>'
        '<script src="/static/vis@4.17.0/dist/vis.min.js"></script>'
        '<script src="/static/scripts/network-monitor.js"></script></body></html>',
    )

    site_dir = render_audit_site(audit_dir)

    index = (site_dir / "index.html").read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="static/css/audit.css">' in index
    assert '<body class="attempt-page">' in index
    assert 'class="attempt-layout"' in index
    assert "Pitch Discrimination Demo" in index
    assert "Experiment readiness audit" in index
    assert "Readiness" in index
    assert "<h1>Report</h1>" not in index
    assert "Experiment <strong>behaves</strong> as expected." in index
    assert "<li>Functional check passed</li>" in index
    assert "<script>bad()</script>" not in index
    assert '<details id="plan" class="attempt-panel plan-panel">' in index
    assert '<details id="report" class="attempt-panel report-panel" open>' in index
    assert "<h1>Plan</h1>" not in index
    assert "Use a chain trial maker." in index
    assert "psynet test local" in index
    assert "No simulated export has been produced yet." in index
    assert index.count('class="attempt-file"') >= 1
    assert (
        '<summary class="file-header"><h3><code>artifacts/psynet_debug.log</code></h3>'
        in index
    )
    assert (
        '<pre class="file-preview"><code>Dashboard user: admin password: [REDACTED]'
        in index
    )
    assert "Open monitor snapshot" in index

    published_files = sorted((site_dir / "static/artifacts/blobs/sha256").glob("**/*"))
    published_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in published_files
        if path.is_file() and path.suffix in {".log", ".html"}
    )
    assert "Dashboard user: admin password: [REDACTED]" in published_text
    assert '<base href="./">' in published_text
    assert "/dashboard/index" not in published_text

    assert (
        site_dir / "static/artifacts/monitor-static/vis@4.17.0/dist/vis.min.js"
    ).exists()
    assert (site_dir / "static/css/audit.css").exists()


def test_render_audit_site_renders_evidence_view(tmp_path: Path) -> None:
    audit_dir = tmp_path / "pitch-discrimination-demo" / "audit"
    manifest = audit_manifest()
    artifacts = manifest["artifacts"]
    assert isinstance(artifacts, list)
    notebook = artifacts[2]
    assert isinstance(notebook, dict)
    notebook["status"] = "present"
    artifacts.extend(
        [
            {
                "id": "participant_video",
                "kind": "video",
                "path": "artifacts/participant.mp4",
                "title": "Participant walkthrough",
                "description": "Participant video.",
                "required": True,
                "status": "present",
                "created_by": "agent",
            },
            {
                "id": "screenshots",
                "kind": "screenshot",
                "path": "artifacts/screenshots/01-intro.png",
                "title": "Intro screenshot",
                "description": "Intro screen.",
                "required": False,
                "status": "present",
                "created_by": "agent",
            },
            {
                "id": "screenshot_second",
                "kind": "screenshot",
                "path": "artifacts/screenshots/02-trial.png",
                "title": "Trial screenshot",
                "description": "Trial screen.",
                "required": False,
                "status": "present",
                "created_by": "agent",
            },
            {
                "id": "screenshot_manifest",
                "kind": "screenshot",
                "path": "artifacts/screenshots/manifest.json",
                "title": "Screenshot manifest",
                "description": "Screenshot captions.",
                "required": False,
                "status": "present",
                "created_by": "agent",
            },
            {
                "id": "performance_result",
                "kind": "performance",
                "path": "artifacts/performance.json",
                "title": "Performance",
                "description": "Performance result.",
                "required": True,
                "status": "present",
                "created_by": "agent",
            },
            {
                "id": "data_export",
                "kind": "data_export",
                "path": "artifacts/data.zip",
                "title": "Data export",
                "description": "Exported data.",
                "required": True,
                "status": "present",
                "created_by": "agent",
            },
            {
                "id": "simulation_export",
                "kind": "data_export",
                "path": "artifacts/simulated_data.zip",
                "title": "Simulated data",
                "description": "Simulated export.",
                "required": True,
                "status": "present",
                "created_by": "agent",
            },
            {
                "id": "experiment_source",
                "kind": "source",
                "path": "artifacts/source/experiment.py",
                "title": "Experiment source",
                "description": "Main experiment source.",
                "required": False,
                "status": "present",
                "created_by": "agent",
            },
        ]
    )
    manifest["blockers"] = []
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")
    write(audit_dir / "PLAN.md", "# Plan\n\nUse a chain trial maker.\n")
    write(audit_dir / "REPORT.md", "# Report\n")
    write(audit_dir / "artifacts/psynet_debug.log", "debug\n")
    write(
        audit_dir / "artifacts/monitor.html", "<html><head></head><body></body></html>"
    )
    write_bytes(audit_dir / "artifacts/participant.mp4", b"video bytes")
    write_bytes(audit_dir / "artifacts/screenshots/01-intro.png", b"png bytes")
    write_bytes(audit_dir / "artifacts/screenshots/02-trial.png", b"png bytes 2")
    write(
        audit_dir / "artifacts/screenshots/manifest.json",
        json.dumps(
            {
                "captions": {
                    "screenshots/01-intro.png": "Intro screen",
                    "screenshots/02-trial.png": "Trial screen",
                }
            }
        ),
    )
    write(
        audit_dir / "artifacts/performance.json",
        json.dumps(
            {
                "results": [
                    {
                        "n_bots": 4,
                        "total_bots_started": 5,
                        "bots_succeeded": 4,
                        "total_requests": 12,
                        "median_response_time": 0.1234,
                        "p95_response_time": 0.4567,
                        "q_delay_p95": 0.0,
                        "request_errors": 1,
                        "bot_errors": 2,
                    }
                ]
            }
        ),
    )
    write_bytes(audit_dir / "artifacts/data.zip", b"data")
    write_bytes(audit_dir / "artifacts/simulated_data.zip", b"simulated")
    write(audit_dir / "artifacts/source/experiment.py", "print('hello')\n")
    write(audit_dir / "analyses/analysis.ipynb", json.dumps({"cells": []}))

    site_dir = render_audit_site(audit_dir, allow_invalid=True)

    index = (site_dir / "index.html").read_text(encoding="utf-8")
    assert "<video" in index
    assert "Screenshot walkthrough" in index
    assert "Intro screen" in index
    assert "Trial screen" in index
    assert "data-screenshot-counter>1 / 2</span>" in index
    assert "Performance test result" in index
    assert "<td>4</td>" in index
    assert "<td>3</td>" in index
    assert "Download data export" in index
    assert "Download simulated data" in index
    assert "<h3><code>artifacts/data.zip</code></h3>" not in index
    assert "<h3><code>artifacts/source/experiment.py</code></h3>" in index
    assert '<div class="file-preview code-preview">' in index
    assert "print" in index
    assert "Participant walkthrough <span>present</span>" in index
    assert "Intro screenshot <span>present</span>" in index
    assert "Screenshot manifest <span>present</span>" in index


def test_render_audit_site_renders_timeline_and_json_sections(tmp_path: Path) -> None:
    audit_dir = tmp_path / "pitch-discrimination-demo" / "audit"
    manifest = audit_manifest()
    sections = manifest["sections"]
    assert isinstance(sections, list)
    sections.insert(
        1,
        {
            "id": "timeline",
            "title": "Timeline",
            "kind": "timeline",
            "path": "TIMELINE.md",
        },
    )
    sections.insert(
        2,
        {
            "id": "agent_metadata",
            "title": "Agent metadata",
            "kind": "json",
            "path": "agent.json",
        },
    )
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")
    write(audit_dir / "PLAN.md", "# Plan\n\nUse a chain trial maker.\n")
    write(audit_dir / "REPORT.md", "# Report\n\nExperiment works.\n")
    write(
        audit_dir / "TIMELINE.md",
        "# Timeline\n\n"
        "- T+00:00:00 [agent-start] Started.\n"
        "- T+00:02:00 [agent-stop] Finished with **evidence**.\n",
    )
    write(audit_dir / "agent.json", '{"model": "test-model"}\n')
    write(audit_dir / "artifacts/psynet_debug.log", "ok\n")
    write(audit_dir / "artifacts/monitor.html", "<!doctype html><html></html>")

    site_dir = render_audit_site(audit_dir)

    index = (site_dir / "index.html").read_text(encoding="utf-8")
    assert '<details id="timeline" class="attempt-panel">' in index
    assert 'class="timeline-list"' in index
    assert "Finished with <strong>evidence</strong>." in index
    assert '<details id="agent_metadata" class="attempt-panel">' in index
    assert "{&quot;model&quot;: &quot;test-model&quot;}" in index


def test_render_audit_site_polishes_core_section_layout(tmp_path: Path) -> None:
    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    manifest["sections"][2]["kind"] = "markdown"  # Legacy packets used this kind.
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")
    write(audit_dir / "PLAN.md", "# Plan\n\nBuild a small experiment.\n")
    write(audit_dir / "REPORT.md", "# Report\n\nThe experiment works.\n")
    write(
        audit_dir / "TIMELINE.md",
        "# Timeline\n\n"
        "2026-08-19T12:53:36Z psynet test local passed\n"
        "2026-08-19T12:54:00Z performance-test smoke --audit\n",
    )

    site_dir = render_audit_site(audit_dir)
    index = (site_dir / "index.html").read_text(encoding="utf-8")

    assert "<h1>Plan</h1>" not in index
    assert "<h1>Report</h1>" not in index
    assert '<details id="timeline"' in index
    assert 'class="timeline-list"' in index
    assert "<h1>Timeline</h1>" not in index
    assert "Audit completeness" in index
    assert index.index("Audit completeness") < index.index("Entry point")
    assert 'href="#checks"' not in index
    assert '<details id="checks"' not in index


def test_render_audit_site_orders_performance_before_analysis(tmp_path: Path) -> None:
    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    for artifact in manifest["artifacts"]:
        if artifact["id"] in {"performance_result", "analysis_notebook"}:
            artifact["status"] = "present"
    manifest["blockers"] = [
        blocker
        for blocker in manifest["blockers"]
        if blocker["artifact_id"] not in {"performance_result", "analysis_notebook"}
    ]
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")
    write(
        audit_dir / "artifacts/performance.json",
        json.dumps({"results": [{"n_bots": 1, "bots_succeeded": 1}]}),
    )
    write(
        audit_dir / "analyses/analysis.ipynb",
        json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {},
                "cells": [
                    {
                        "cell_type": "markdown",
                        "metadata": {},
                        "source": ["Analysis body"],
                    }
                ],
            }
        ),
    )

    site_dir = render_audit_site(audit_dir)
    index = (site_dir / "index.html").read_text(encoding="utf-8")

    assert index.index('class="performance-result') < index.index(
        'id="analysis-notebook"'
    )


def test_render_audit_site_publishes_screenshots_from_manifest(tmp_path: Path) -> None:
    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    screenshots = next(
        artifact
        for artifact in manifest["artifacts"]
        if artifact["id"] == "screenshots"
    )
    screenshots["status"] = "present"
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")
    write_bytes(audit_dir / "artifacts/screenshots/01-intro.png", b"png bytes")
    write_bytes(audit_dir / "artifacts/screenshots/02-trial.png", b"png bytes 2")
    write(
        audit_dir / "artifacts/screenshots/manifest.json",
        json.dumps(
            {
                "captions": {
                    "screenshots/01-intro.png": "Intro screen",
                    "screenshots/02-trial.png": "Trial screen",
                }
            }
        ),
    )

    site_dir = render_audit_site(audit_dir)
    index = (site_dir / "index.html").read_text(encoding="utf-8")

    assert "Screenshot walkthrough" in index
    assert "Intro screen" in index
    assert "Trial screen" in index
    assert "data-screenshot-counter>1 / 2</span>" in index


def test_render_audit_site_publishes_gif_screenshots_from_manifest(
    tmp_path: Path,
) -> None:
    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    screenshots = next(
        artifact
        for artifact in manifest["artifacts"]
        if artifact["id"] == "screenshots"
    )
    screenshots["status"] = "present"
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")
    write_bytes(audit_dir / "artifacts/screenshots/01-intro.gif", b"gif bytes")
    write(
        audit_dir / "artifacts/screenshots/manifest.json",
        json.dumps({"captions": {"screenshots/01-intro.gif": "Animated intro"}}),
    )

    site_dir = render_audit_site(audit_dir)
    index = (site_dir / "index.html").read_text(encoding="utf-8")

    assert "Animated intro" in index
    gif_blob = next(site_dir.rglob("*.gif"), None)
    assert gif_blob is not None


def test_starter_sections_rename_implementation_narrative() -> None:
    manifest = starter_audit_manifest()
    titles = {section["id"]: section["title"] for section in manifest["sections"]}

    assert titles["timeline"] == "Implementation timeline"
    assert titles["report"] == "Implementation notes"
    assert titles["source"] == "Experiment code"
    assert "evidence" not in titles


@pytest.mark.parametrize(
    "entry_point",
    ["experiment.py", "code/primary_color_rating/experiment.py"],
)
def test_render_audit_site_inlines_experiment_entry_point(
    tmp_path: Path,
    entry_point: str,
) -> None:
    audit_dir = tmp_path / "experiment" / "audit"
    init_audit(audit_dir)
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    manifest["experiment"]["entry_point"] = entry_point
    manifest["sections"] = [
        section for section in manifest["sections"] if section["id"] != "source"
    ]
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")
    write(
        audit_dir.parent / entry_point,
        'LABEL = "safe-source-value"\n\nclass Exp:\n    pass\n',
    )

    site_dir = render_audit_site(audit_dir)
    index = (site_dir / "index.html").read_text(encoding="utf-8")

    assert '<details id="source"' in index
    assert "<h2>Experiment code</h2>" in index
    assert f"<code>{entry_point}</code>" in index
    assert "safe-source-value" in index
    assert "Exp" in index
    assert index.index('<details id="source"') < index.index('<details id="blockers"')


def test_render_audit_site_elevates_evidence_subsections(tmp_path: Path) -> None:
    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    for artifact in manifest["artifacts"]:
        artifact["status"] = "present"
    manifest["blockers"] = []
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")
    write_bytes(audit_dir / "artifacts/participant.mp4", b"video bytes")
    write_bytes(audit_dir / "artifacts/screenshots/01-intro.png", b"png bytes")
    write(
        audit_dir / "artifacts/screenshots/manifest.json",
        json.dumps({"captions": {"screenshots/01-intro.png": "Intro screen"}}),
    )
    write(
        audit_dir / "artifacts/monitor.html", "<html><head></head><body></body></html>"
    )
    write_bytes(audit_dir / "artifacts/simulated_data.zip", b"zip bytes")
    write(
        audit_dir / "artifacts/performance.json",
        json.dumps({"results": [{"n_bots": 2, "bots_succeeded": 2}]}),
    )
    write(
        audit_dir / "analyses/analysis.ipynb",
        json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {},
                "cells": [
                    {
                        "cell_type": "markdown",
                        "metadata": {},
                        "source": ["Analysis body"],
                    }
                ],
            }
        ),
    )

    site_dir = render_audit_site(audit_dir, allow_invalid=True)
    index = (site_dir / "index.html").read_text(encoding="utf-8")

    assert "<h2>Evidence</h2>" not in index
    assert '<details id="evidence"' not in index
    for section_id in (
        "screenshots",
        "participant_video",
        "monitor",
        "performance",
        "data_exports",
    ):
        assert f'<details id="{section_id}"' in index
    assert index.index('id="screenshots"') < index.index('id="participant_video"')
    assert index.index('id="participant_video"') < index.index('id="performance"')
    assert index.index('id="performance"') < index.index('id="analysis"')
    # Panel titles already name each section, so inner duplicates are dropped.
    assert 'id="screenshot-gallery-heading"' not in index
    assert "<h3>Analysis notebook</h3>" not in index
    assert "Intro screen" in index
    assert "Open monitor snapshot" in index
    assert "Raw JSON" in index


def test_render_audit_site_keeps_blockers_collapsed_and_explained(
    tmp_path: Path,
) -> None:
    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)

    site_dir = render_audit_site(audit_dir)
    index = (site_dir / "index.html").read_text(encoding="utf-8")

    assert '<details id="blockers" class="attempt-panel">' in index
    assert "required evidence" in index
    assert index.index('id="files"') < index.index('id="blockers"')


def test_render_audit_site_reports_missing_elevated_evidence(tmp_path: Path) -> None:
    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)

    site_dir = render_audit_site(audit_dir)
    index = (site_dir / "index.html").read_text(encoding="utf-8")

    assert "No screenshots were found." in index
    assert "No participant recording was found." in index
    assert "No performance test result was found." in index
    assert "No analysis notebook was found." in index
    assert "No monitor snapshot was found." in index


def test_render_audit_section_isolates_render_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_dir = tmp_path / "audit"
    manifest = audit_manifest()
    section = {
        "id": "report",
        "title": "Report",
        "kind": "markdown",
        "path": "REPORT.md",
    }
    write(audit_dir / "REPORT.md", "# Report\n\nWorks.\n")

    def boom_markdown(audit_dir: Path, section: dict[str, object]) -> str:
        raise RuntimeError("markdown render failed")

    monkeypatch.setattr("psynet.audit.site.render_markdown_section", boom_markdown)

    html = render_audit_section(audit_dir, manifest, section, [])

    assert '<details id="report" class="attempt-panel report-panel" open>' in html
    assert 'class="section-render-error"' in html
    assert "Failed to render section report." in html
    assert "markdown render failed" not in html


def write_valid_review(audit_dir: Path) -> None:
    write(audit_dir / "audit.json", json.dumps(audit_manifest()) + "\n")
    write(audit_dir / "PLAN.md", "# Plan\n\nUse a chain trial maker.\n")
    write(audit_dir / "REPORT.md", "# Report\n\nExperiment behaves as expected.\n")
    write(
        audit_dir / "artifacts/psynet_debug.log",
        "Dashboard user: admin password: local-password\n",
    )
    write(
        audit_dir / "artifacts/monitor.html",
        '<!doctype html><html><head><link href="/static/css/dashboard.css"></head>'
        '<body><a href="/dashboard/index">Dashboard</a>'
        '<script src="/static/vis@4.17.0/dist/vis.min.js"></script>'
        '<script src="/static/scripts/network-monitor.js"></script></body></html>',
    )


def test_validate_audit_accepts_blocked_required_artifact_with_blocker(
    tmp_path: Path,
) -> None:
    audit_dir = tmp_path / "audit"
    write_valid_review(audit_dir)

    assert validate_audit(audit_dir) == []


def test_validate_audit_fails_when_present_artifact_file_is_missing(
    tmp_path: Path,
) -> None:
    audit_dir = tmp_path / "audit"
    write_valid_review(audit_dir)
    (audit_dir / "artifacts/psynet_debug.log").unlink()

    problems = validate_audit(audit_dir)

    assert any(
        "artifact marked present but file is missing" in problem for problem in problems
    )


def test_validate_audit_fails_when_required_artifact_lacks_blocker(
    tmp_path: Path,
) -> None:
    audit_dir = tmp_path / "audit"
    manifest = audit_manifest()
    manifest["blockers"] = []
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")
    write(audit_dir / "PLAN.md", "# Plan\n")
    write(audit_dir / "REPORT.md", "# Report\n")
    write(audit_dir / "artifacts/psynet_debug.log", "ok\n")
    write(
        audit_dir / "artifacts/monitor.html", "<html><head></head><body></body></html>"
    )

    problems = validate_audit(audit_dir)

    assert any("required artifact must be present" in problem for problem in problems)


def test_validate_audit_fails_when_markdown_section_path_is_missing(
    tmp_path: Path,
) -> None:
    audit_dir = tmp_path / "audit"
    write(audit_dir / "audit.json", json.dumps(audit_manifest()) + "\n")
    write(audit_dir / "REPORT.md", "# Report\n")
    write(audit_dir / "artifacts/psynet_debug.log", "ok\n")
    write(
        audit_dir / "artifacts/monitor.html", "<html><head></head><body></body></html>"
    )

    problems = validate_audit(audit_dir)

    assert any("section file is missing" in problem for problem in problems)


def test_validate_audit_accepts_missing_plan_section(tmp_path: Path) -> None:
    audit_dir = tmp_path / "audit"
    write_valid_review(audit_dir)
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    manifest["sections"] = [
        section for section in manifest["sections"] if section["id"] != "plan"
    ]
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")

    assert validate_audit(audit_dir) == []


def test_collect_audit_warnings_when_plan_section_missing(tmp_path: Path) -> None:
    from psynet.audit.cli import collect_audit_warnings

    audit_dir = tmp_path / "audit"
    write_valid_review(audit_dir)
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    manifest["sections"] = [
        section for section in manifest["sections"] if section["id"] != "plan"
    ]
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")

    warnings = collect_audit_warnings(audit_dir)

    assert any("no plan section" in warning for warning in warnings)


def test_unparsed_timeline_entry_lines_skips_headings_and_examples() -> None:
    from psynet.audit.cli import STARTER_TIMELINE
    from psynet.audit.timeline import (
        parse_timeline_entries,
        unparsed_timeline_entry_lines,
    )

    markdown = (
        "# Timeline\n\n"
        "- T+00:00:00 [agent-start] Started.\n"
        "- T+00:00:22 [evidence] This actor is not allowed.\n"
        "- T+00:01:00 [agent] [evidence] Ran simulate.\n"
        "`- T+00:00:00 [agent-start] Started implementation.`\n"
    )
    entries = parse_timeline_entries(markdown)
    skipped = unparsed_timeline_entry_lines(markdown)

    assert [entry.description for entry in entries] == [
        "Started.",
        "Ran simulate.",
    ]
    assert skipped == [
        (4, "- T+00:00:22 [evidence] This actor is not allowed."),
    ]
    assert unparsed_timeline_entry_lines(STARTER_TIMELINE) == []


def test_collect_audit_warnings_for_unparsed_timeline_lines(tmp_path: Path) -> None:
    from psynet.audit.cli import collect_audit_warnings

    audit_dir = tmp_path / "audit"
    write_valid_review(audit_dir)
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    manifest["sections"].insert(
        1,
        {
            "id": "timeline",
            "title": "Implementation timeline",
            "kind": "timeline",
            "path": "TIMELINE.md",
        },
    )
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")
    write(
        audit_dir / "TIMELINE.md",
        "# Timeline\n\n"
        "- T+00:00:00 [agent-start] Started.\n"
        "- T+00:00:22 [evidence] Dropped.\n",
    )

    warnings = collect_audit_warnings(audit_dir)

    assert any(
        "line 4 looks like a timeline entry but was ignored" in warning
        for warning in warnings
    )


def test_init_audit_warns_about_placeholder_summary(tmp_path: Path) -> None:
    from psynet.audit.cli import (
        PLACEHOLDER_IMPLEMENTATION_SUMMARY,
        collect_audit_warnings,
        init_audit,
    )

    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)

    warnings = collect_audit_warnings(audit_dir)
    assert any("TODO placeholder" in warning for warning in warnings)
    assert validate_audit(audit_dir) == []

    site_dir = render_audit_site(audit_dir)
    index = (site_dir / "index.html").read_text(encoding="utf-8")
    assert PLACEHOLDER_IMPLEMENTATION_SUMMARY not in index
    assert "TODO:" not in index


def test_render_audit_site_includes_rewritten_summary(tmp_path: Path) -> None:
    audit_dir = tmp_path / "pitch-discrimination-demo" / "audit"
    write_valid_review(audit_dir)

    index = (render_audit_site(audit_dir) / "index.html").read_text(encoding="utf-8")
    assert "Compare two tones and report which one is higher." in index


def test_validate_audit_rejects_orphan_blocker(tmp_path: Path) -> None:
    audit_dir = tmp_path / "audit"
    write_valid_review(audit_dir)
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    manifest["blockers"].append(
        {
            "artifact_id": "missing_artifact",
            "severity": "error",
            "reason": "Not declared.",
            "next_step": "Remove blocker.",
        },
    )
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")

    problems = validate_audit(audit_dir)

    assert any("not declared in artifacts" in problem for problem in problems)


def test_validate_audit_rejects_large_section_file(tmp_path: Path) -> None:
    from psynet.audit.cli import MAX_AUDIT_SECTION_BYTES

    audit_dir = tmp_path / "audit"
    write_valid_review(audit_dir)
    write(audit_dir / "REPORT.md", "x" * (MAX_AUDIT_SECTION_BYTES + 1))

    problems = validate_audit(audit_dir)

    assert any("section file exceeds" in problem for problem in problems)


def test_relative_audit_path_rejects_escape(tmp_path: Path) -> None:
    from psynet.audit.cli import relative_audit_path

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    _, problems = relative_audit_path(
        audit_dir,
        "../../etc/passwd",
        "artifact participant_video",
    )

    assert problems
    assert any("stay inside" in problem for problem in problems)


@pytest.mark.parametrize("entry_point", ["/etc/passwd", "../secret.env", "", None, 1])
def test_experiment_entry_point_must_stay_inside_source(
    tmp_path: Path,
    entry_point: object,
) -> None:
    audit_dir = tmp_path / "experiment" / "audit"
    init_audit(audit_dir)
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    manifest["experiment"]["entry_point"] = entry_point
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")

    problems = validate_audit(audit_dir)

    assert any("experiment.entry_point" in problem for problem in problems)


def test_mark_artifact_present_rejects_invalid_notebook(tmp_path: Path) -> None:
    from psynet.audit.cli import mark_artifact_present

    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    write(audit_dir / "analyses/analysis.ipynb", "{not json")

    with pytest.raises(ValueError, match="invalid notebook JSON"):
        mark_artifact_present(audit_dir, "analysis_notebook")


def test_mark_artifact_present_rejects_git_lfs_video_pointer(tmp_path: Path) -> None:
    from psynet.audit.cli import mark_artifact_present

    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    write_bytes(audit_dir / "artifacts/participant.mp4", LFS_VIDEO_POINTER)

    with pytest.raises(ValueError, match="Git LFS pointer"):
        mark_artifact_present(audit_dir, "participant_video")


def test_allow_invalid_render_does_not_publish_git_lfs_video_pointer(
    tmp_path: Path,
) -> None:
    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    video = next(
        artifact
        for artifact in manifest["artifacts"]
        if artifact["id"] == "participant_video"
    )
    video["status"] = "present"
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")
    write_bytes(audit_dir / "artifacts/participant.mp4", LFS_VIDEO_POINTER)

    site_dir = render_audit_site(audit_dir, allow_invalid=True)
    index = (site_dir / "index.html").read_text(encoding="utf-8")

    assert "<video" not in index
    assert "Participant walkthrough <span>unavailable</span>" in index
    assert "0/5 required present" in index


def test_mark_artifact_present_accepts_notebook_larger_than_preview(
    tmp_path: Path,
) -> None:
    from psynet.audit.cli import MAX_AUDIT_TEXT_BYTES, mark_artifact_present

    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": ["Unique large-notebook marker"],
            }
        ],
        "embedded_output": "x" * (MAX_AUDIT_TEXT_BYTES + 1),
    }
    write(audit_dir / "analyses/analysis.ipynb", json.dumps(notebook))

    mark_artifact_present(audit_dir, "analysis_notebook")
    site_dir = render_audit_site(audit_dir)
    index = (site_dir / "index.html").read_text(encoding="utf-8")

    assert not any(
        "audit notebooks must be at most" in p for p in validate_audit(audit_dir)
    )
    assert 'id="analysis-notebook"' in index
    assert "Unique large-notebook marker" in index
    assert "Open raw notebook" in index


def test_init_from_inside_audit_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_dir = tmp_path / "experiment"
    experiment_dir.mkdir()
    monkeypatch.chdir(experiment_dir)
    assert run_audit_cli("init").exit_code == 0
    monkeypatch.chdir(experiment_dir / "audit")

    result = run_audit_cli("init", "--force")

    assert result.exit_code != 0
    assert "not from audit/" in result.output
    assert not (experiment_dir / "audit" / "audit" / "audit.json").exists()


def test_init_from_empty_audit_directory_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty_audit = tmp_path / "audit"
    empty_audit.mkdir()
    monkeypatch.chdir(empty_audit)

    result = run_audit_cli("init")

    assert result.exit_code != 0
    assert "not from audit/" in result.output
    assert not (empty_audit / "audit" / "audit.json").exists()


def test_audit_cli_rejects_positional_packet_path() -> None:
    result = run_audit_cli("init", ".")
    assert result.exit_code != 0
    combined = f"{result.output}{result.stderr}"
    assert "unexpected extra argument" in combined.lower()


def test_init_creates_nested_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = run_audit_cli("init")

    assert result.exit_code == 0
    manifest = json.loads(
        (tmp_path / "audit" / "audit.json").read_text(encoding="utf-8")
    )
    assert "source_path" not in manifest["experiment"]
    assert not (tmp_path / "audit.json").exists()


def test_validate_audit_notebook_skips_read_when_oversized() -> None:
    from unittest.mock import MagicMock

    from psynet.audit.cli import MAX_AUDIT_NOTEBOOK_BYTES, validate_audit_notebook

    notebook = MagicMock()
    notebook.stat.return_value.st_size = MAX_AUDIT_NOTEBOOK_BYTES + 1
    notebook.read_text.side_effect = AssertionError(
        "oversized notebooks must not be read",
    )
    notebook.__str__.return_value = "analysis.ipynb"

    problems = validate_audit_notebook(notebook)

    assert any("audit notebooks must be at most" in problem for problem in problems)
    notebook.read_text.assert_not_called()


def test_read_audit_artifact_content_marks_truncation(tmp_path: Path) -> None:
    from psynet.audit.cli import read_audit_artifact_content

    source = tmp_path / "long.log"
    source.write_text("x" * 120_000, encoding="utf-8")

    content, truncated = read_audit_artifact_content(source, max_bytes=100_000)

    assert truncated is True
    assert content is not None
    assert len(content) == 100_000


def test_read_audit_artifact_content_truncates_multibyte_utf8(tmp_path: Path) -> None:
    from psynet.audit.cli import read_audit_artifact_content

    source = tmp_path / "long.log"
    source.write_bytes(b"x" * 99_999 + "é".encode() + b"y" * 100)

    content, truncated = read_audit_artifact_content(source, max_bytes=100_000)

    assert truncated is True
    assert content is not None
    assert len(content) <= 100_000


def test_validate_audit_reports_null_artifacts_instead_of_crashing(
    tmp_path: Path,
) -> None:
    audit_dir = tmp_path / "audit"
    write(
        audit_dir / "audit.json",
        json.dumps(audit_manifest() | {"artifacts": None}) + "\n",
    )
    write_core_section_files(audit_dir)

    problems = validate_audit(audit_dir)

    assert any("artifacts must be a list" in problem for problem in problems)


def test_render_audit_site_allow_invalid_reports_malformed_json(
    tmp_path: Path,
) -> None:
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    write(audit_dir / "audit.json", "{not json")

    with pytest.raises(ValueError, match="invalid JSON"):
        render_audit_site(audit_dir, allow_invalid=True)


def test_starter_audit_manifest_matches_schema_section_kinds() -> None:
    from psynet.audit.cli import audit_css_path, starter_audit_manifest

    schema_path = audit_css_path().parent / "audit.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    allowed = set(schema["$defs"]["section"]["properties"]["kind"]["enum"])
    manifest = starter_audit_manifest()
    for section in manifest["sections"]:
        assert section["kind"] in allowed


def test_collect_audit_warnings_when_ffprobe_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from psynet.audit.cli import collect_audit_warnings
    from psynet.audit.video import VideoProbeResult

    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    write_bytes(audit_dir / "artifacts/participant.mp4", b"video bytes")
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    for artifact in manifest["artifacts"]:
        if artifact["id"] == "participant_video":
            artifact["status"] = "present"
    manifest["blockers"] = [
        blocker
        for blocker in manifest["blockers"]
        if blocker["artifact_id"] != "participant_video"
    ]
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")

    monkeypatch.setattr(
        "psynet.audit.validate.probe_video_metadata",
        lambda _path: VideoProbeResult(None, "unavailable"),
    )
    monkeypatch.setattr(
        "psynet.audit.video.probe_video_metadata",
        lambda _path: VideoProbeResult(None, "unavailable"),
    )

    warnings = collect_audit_warnings(audit_dir)

    assert any("ffprobe is not available" in warning for warning in warnings)
    assert validate_audit(audit_dir) == []


def test_resolve_audit_dir_requires_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from psynet.audit.cli import resolve_audit_dir

    missing = tmp_path / "nowhere"
    missing.mkdir()
    monkeypatch.chdir(missing)
    with pytest.raises(ValueError, match="No audit packet found"):
        resolve_audit_dir(require_manifest=True)


def test_validate_audit_accepts_unknown_extension_ids_with_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from psynet.audit.cli import collect_audit_warnings

    audit_dir = tmp_path / "audit"
    write_valid_review(audit_dir)
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    manifest["extensions"] = ["psynetskills.challenge", "example.unknown"]
    manifest["sections"].append(
        {
            "id": "evaluation",
            "title": "Evaluation",
            "kind": "markdown",
            "path": "EVALUATION.md",
        },
    )
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")
    write(audit_dir / "EVALUATION.md", "# Evaluation\n\nScore pending.\n")

    assert validate_audit(audit_dir) == []
    warnings = collect_audit_warnings(audit_dir)
    assert not any("psynetskills.challenge" in warning for warning in warnings)
    assert any("example.unknown" in warning for warning in warnings)

    monkeypatch.chdir(tmp_path)
    result = run_audit_cli("validate")
    assert result.exit_code == 0
    assert "Warning:" in result.stderr
    assert "example.unknown" in result.stderr
    assert "psynetskills.challenge" not in result.stderr
    assert "Audit packet coherent" in result.output


def test_validate_audit_fails_for_invalid_notebook_json(tmp_path: Path) -> None:
    audit_dir = tmp_path / "audit"
    manifest = audit_manifest()
    artifacts = manifest["artifacts"]
    assert isinstance(artifacts, list)
    notebook = artifacts[2]
    assert isinstance(notebook, dict)
    notebook["status"] = "present"
    manifest["blockers"] = []
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")
    write(audit_dir / "PLAN.md", "# Plan\n")
    write(audit_dir / "REPORT.md", "# Report\n")
    write(audit_dir / "artifacts/psynet_debug.log", "ok\n")
    write(
        audit_dir / "artifacts/monitor.html", "<html><head></head><body></body></html>"
    )
    write(audit_dir / "analyses/analysis.ipynb", "{not json")

    problems = validate_audit(audit_dir)

    assert any("invalid notebook JSON" in problem for problem in problems)


def test_validate_audit_cli_exits_nonzero_on_problems(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_dir = tmp_path / "audit"
    write(audit_dir / "audit.json", json.dumps(audit_manifest()) + "\n")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(psynet, ["audit", "validate"])

    assert result.exit_code == 1
    combined = f"{result.output}{result.stderr}"
    assert "section file is missing" in combined


def test_init_audit_creates_starter_structure_and_manifest(tmp_path: Path) -> None:
    audit_dir = tmp_path / "pitch-discrimination-demo" / "audit"

    init_audit(audit_dir)

    assert (audit_dir / "audit.json").exists()
    assert (audit_dir / "REPORT.md").exists()
    assert (audit_dir / "PROMPT.md").exists()
    assert (audit_dir / "PLAN.md").exists()
    assert (audit_dir / "TIMELINE.md").exists()
    assert (audit_dir / "artifacts/screenshots").is_dir()
    assert (audit_dir / "analyses").is_dir()
    assert (audit_dir / "logs").is_dir()
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    assert "title" not in manifest["experiment"]
    assert "source_base" not in manifest["experiment"]
    assert "source_path" not in manifest["experiment"]
    assert manifest["profile"] == "psynet.core"
    assert manifest["extensions"] == []
    assert [section["id"] for section in manifest["sections"]] == [
        "prompt",
        "plan",
        "timeline",
        "report",
        "source",
        "screenshots",
        "participant_video",
        "monitor",
        "performance",
        "data_exports",
        "analysis",
        "files",
        "blockers",
        "checks",
    ]
    assert manifest["artifacts"][0]["id"] == "participant_video"
    assert manifest["artifacts"][0]["status"] == "blocked"
    assert manifest["blockers"][0]["severity"] == "error"
    assert {blocker["artifact_id"] for blocker in manifest["blockers"]} == {
        "participant_video",
        "performance_result",
        "monitor_snapshot",
        "simulation_export",
        "analysis_notebook",
    }
    assert validate_audit(audit_dir) == []


def test_init_audit_cli_prints_next_steps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_dir = tmp_path / "experiment"
    experiment_dir.mkdir()
    monkeypatch.chdir(experiment_dir)

    result = run_audit_cli("init")

    assert result.exit_code == 0
    assert "Initialized experiment audit directory" in result.output
    assert "starter packet" in result.output
    assert "psynet audit validate" in result.output
    assert "packet coherent ≠ experiment ready" in result.output
    manifest = json.loads(
        (experiment_dir / "audit" / "audit.json").read_text(encoding="utf-8")
    )
    assert "source_path" not in manifest["experiment"]


def test_init_audit_refuses_to_overwrite_by_default(tmp_path: Path) -> None:
    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    original = (audit_dir / "audit.json").read_text(encoding="utf-8")

    with pytest.raises(FileExistsError):
        init_audit(audit_dir)

    assert (audit_dir / "audit.json").read_text(encoding="utf-8") == original


def test_init_audit_force_replaces_starter_files(tmp_path: Path) -> None:
    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    (audit_dir / "audit.json").write_text("custom\n", encoding="utf-8")
    (audit_dir / "REPORT.md").write_text("custom\n", encoding="utf-8")

    init_audit(audit_dir, force=True)

    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    assert "source_path" not in manifest["experiment"]
    assert "Summarize the implementation" in (audit_dir / "REPORT.md").read_text(
        encoding="utf-8",
    )


def test_render_audit_site_uses_experiment_directory_title(tmp_path: Path) -> None:
    audit_dir = tmp_path / "tone-comparison" / "audit"
    init_audit(audit_dir)
    site_dir = render_audit_site(audit_dir)
    index = (site_dir / "index.html").read_text(encoding="utf-8")
    assert "Tone Comparison" in index
    assert "Experiment readiness audit" in index
    assert "0/5 required present" in index


def test_validate_ignores_legacy_source_base_with_warning(tmp_path: Path) -> None:
    from psynet.audit.cli import collect_audit_warnings

    audit_dir = tmp_path / "tone-comparison" / "audit"
    init_audit(audit_dir)
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    manifest["experiment"]["source_base"] = "packet"
    manifest["experiment"]["source_path"] = "code/old"
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")
    write(audit_dir.parent / "experiment.py", 'LABEL = "from parent"\n')

    assert validate_audit(audit_dir) == []
    warnings = collect_audit_warnings(audit_dir)
    assert any("source_base is ignored" in warning for warning in warnings)
    assert any("source_path is ignored" in warning for warning in warnings)
    site_dir = render_audit_site(audit_dir)
    assert "from parent" in (site_dir / "index.html").read_text(encoding="utf-8")


def test_render_refuses_invalid_manifest_unless_allowed(tmp_path: Path) -> None:
    from psynet.audit.cli import AuditValidationError

    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    manifest["artifacts"][0]["status"] = "done"
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")

    with pytest.raises(AuditValidationError) as exc_info:
        render_audit_site(audit_dir)
    assert any(
        "status is not recognized" in problem for problem in exc_info.value.problems
    )
    assert any("allowed:" in problem for problem in exc_info.value.problems)

    site_dir = render_audit_site(audit_dir, allow_invalid=True)
    assert (site_dir / "index.html").is_file()


def test_mark_artifact_present_updates_manifest_and_drops_blocker(
    tmp_path: Path,
) -> None:
    from psynet.audit.cli import mark_artifact_present

    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    write(audit_dir / "artifacts/monitor.html", "<html></html>")

    mark_artifact_present(audit_dir, "monitor_snapshot")

    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    monitor = next(a for a in manifest["artifacts"] if a["id"] == "monitor_snapshot")
    assert monitor["status"] == "present"
    assert all(b["artifact_id"] != "monitor_snapshot" for b in manifest["blockers"])
    assert validate_audit(audit_dir) == []


def test_validate_success_message_mentions_blockers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    monkeypatch.chdir(tmp_path)

    result = run_audit_cli("validate")

    assert result.exit_code == 0
    assert "Audit packet coherent" in result.output
    assert "blocker" in result.output
    assert "readiness incomplete" in result.output


def test_resolve_audit_dir_nested_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from psynet.audit.cli import resolve_audit_dir

    experiment = tmp_path / "exp"
    nested = experiment / "audit"
    nested.mkdir(parents=True)
    write(nested / "audit.json", "{}\n")
    monkeypatch.chdir(experiment)

    assert resolve_audit_dir() == Path("audit")
    assert resolve_audit_dir(require_manifest=True) == Path("audit")

    monkeypatch.chdir(nested)
    with pytest.raises(ValueError, match="not from audit/"):
        resolve_audit_dir()

    empty_audit = tmp_path / "empty" / "audit"
    empty_audit.mkdir(parents=True)
    monkeypatch.chdir(empty_audit)
    with pytest.raises(ValueError, match="not from audit/"):
        resolve_audit_dir()

    leftover = tmp_path / "legacy"
    leftover.mkdir()
    write(leftover / "audit.json", "{}\n")
    monkeypatch.chdir(leftover)
    with pytest.raises(ValueError, match="Audits must live in ./audit/"):
        resolve_audit_dir()


def test_validate_cli_accepts_experiment_root_dot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment = tmp_path / "exp"
    experiment.mkdir()
    monkeypatch.chdir(experiment)
    result = run_audit_cli("init")
    assert result.exit_code == 0
    assert (experiment / "audit" / "audit.json").is_file()

    result = run_audit_cli("validate")

    assert result.exit_code == 0
    assert "Audit packet coherent" in result.output
    assert "readiness incomplete" in result.output


def test_render_cli_blocked_by_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    manifest["artifacts"][0]["status"] = "done"
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(psynet, ["audit", "render"])

    assert result.exit_code != 0
    combined = f"{result.output}{result.stderr}"
    assert "Render blocked by validation errors" in combined


def test_validate_rejects_escaping_render_site_path(tmp_path: Path) -> None:
    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    manifest["render"] = {
        "site_path": "../../outside-site",
        "generator": "psynet audit",
    }
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")

    problems = validate_audit(audit_dir)
    assert any("render.site_path" in problem for problem in problems)
    assert any("must stay inside" in problem for problem in problems)


@pytest.mark.parametrize(
    "site_path", [".", "artifacts/site", "analyses/site", "logs/site"]
)
def test_validate_rejects_render_site_path_overlapping_packet_content(
    tmp_path: Path,
    site_path: str,
) -> None:
    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    manifest["render"]["site_path"] = site_path
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")

    problems = validate_audit(audit_dir)

    assert any("render.site_path" in problem for problem in problems)
    assert any("dedicated output directory" in problem for problem in problems)


def test_render_refuses_escaping_site_path_even_with_allow_invalid(
    tmp_path: Path,
) -> None:
    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    manifest["render"] = {
        "site_path": "../../outside-site",
        "generator": "psynet audit",
    }
    write(audit_dir / "audit.json", json.dumps(manifest) + "\n")

    with pytest.raises(ValueError, match="render.site_path|must stay inside"):
        render_audit_site(audit_dir, allow_invalid=True)
    assert not (tmp_path / "outside-site").exists()


def test_make_audit_site_server_serves_index(tmp_path: Path) -> None:
    import threading
    import urllib.request

    from psynet.audit.cli import make_audit_site_server

    site_dir = tmp_path / "site"
    write(site_dir / "index.html", "<!doctype html><title>audit</title>hello-audit")

    server = make_audit_site_server(site_dir, host="127.0.0.1", port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
            assert response.status == 200
            body = response.read()
        assert b"hello-audit" in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_make_audit_site_server_requires_index(tmp_path: Path) -> None:
    from psynet.audit.cli import make_audit_site_server

    site_dir = tmp_path / "site"
    site_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="psynet audit render"):
        make_audit_site_server(site_dir, host="127.0.0.1", port=0)


def test_audit_serve_cli_errors_when_site_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(psynet, ["audit", "serve", "--port", "0"])

    assert result.exit_code != 0
    combined = f"{result.output}{result.stderr}"
    assert "No rendered audit site" in combined
    assert "psynet audit render" in combined


def test_audit_serve_cli_allow_invalid_requires_render() -> None:
    result = CliRunner().invoke(psynet, ["audit", "serve", "--allow-invalid"])

    assert result.exit_code != 0
    combined = f"{result.output}{result.stderr}"
    assert "--allow-invalid is only valid together with --render" in combined


def test_audit_serve_cli_render_then_serve(tmp_path: Path, monkeypatch) -> None:
    from psynet.audit import cli as audit_cli

    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    # Provide enough present artifacts for validate/render if needed via allow_invalid
    calls = []

    def fake_serve(site_dir, *, host="127.0.0.1", port=8765):
        calls.append((Path(site_dir), host, port))
        assert (Path(site_dir) / "index.html").is_file()

    monkeypatch.setattr(audit_cli, "serve_audit_site", fake_serve)

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        psynet,
        [
            "audit",
            "serve",
            "--render",
            "--allow-invalid",
            "--host",
            "127.0.0.1",
            "--port",
            "9123",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Rendered experiment audit site" in result.output
    assert calls == [(audit_dir / "site", "127.0.0.1", 9123)]
