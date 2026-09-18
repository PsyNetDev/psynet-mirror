"""Audit artifact publication, HTML rendering, and local site server."""

from __future__ import annotations

import html
import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

from psynet.audit.artifacts import (
    HASHED_ARTIFACTS_DIR,
    MONITOR_STATIC_ARTIFACTS_DIR,
    published_blob_path,
    write_hashed_artifact,
    write_shared_monitor_static_assets,
)
from psynet.audit.constants import AUDIT_CSS_OUTPUT, AuditValidationError
from psynet.audit.content import (
    read_audit_artifact_content,
    section_text,
    strip_redundant_section_heading,
)
from psynet.audit.html import (
    pygments_css,
    render_analysis_notebook,
    render_completeness,
    render_data_exports,
    render_evidence_section,
    render_file_grid,
    render_json_block,
    render_markdown_block,
    render_monitor_snapshot,
    render_participant_video,
    render_performance_result,
    render_screenshot_gallery,
    render_visible_artifacts,
    safe_section_html,
)
from psynet.audit.html import (
    render_timeline_section as render_shared_timeline_section,
)
from psynet.audit.manifest import (
    audit_css_path,
    audit_display_title,
    display_implementation_summary,
    read_audit_manifest,
    starter_section,
)
from psynet.audit.model import (
    SCREENSHOT_FILE_SUFFIXES,
    AuditFile,
    classify_audit_evidence,
    file_kind,
)
from psynet.audit.paths import (
    experiment_source_root,
    relative_audit_path,
    validate_audit_site_dir,
)
from psynet.audit.timeline import parse_timeline_entries
from psynet.audit.validate import validate_audit
from psynet.audit.video import is_git_lfs_pointer


def artifact_output_url(relative_url: str) -> str:
    """Return a browser path from a rendered audit page to a published artifact."""

    return f"static/{relative_url}"


def publish_audit_artifacts(
    audit_dir: Path,
    site_dir: Path,
    manifest: dict[str, Any],
) -> list[AuditFile]:
    """Publish present artifacts and return render metadata."""

    target_root = site_dir / "static" / HASHED_ARTIFACTS_DIR
    shared_static_root = site_dir / "static" / MONITOR_STATIC_ARTIFACTS_DIR
    shutil.rmtree(target_root, ignore_errors=True)
    shutil.rmtree(shared_static_root, ignore_errors=True)
    target_root.mkdir(parents=True, exist_ok=True)
    write_shared_monitor_static_assets(shared_static_root)

    rendered: list[AuditFile] = []
    published_paths: set[str] = set()
    for artifact in manifest.get("artifacts", []):
        if not isinstance(artifact, dict):
            continue
        relative_path = str(artifact.get("path") or "")
        status = str(artifact.get("status") or "missing")
        if not relative_path or status != "present":
            continue
        source_file, path_problems = relative_audit_path(
            audit_dir,
            relative_path,
            f"artifact {artifact.get('id')!r}",
        )
        if path_problems or source_file is None or not source_file.is_file():
            continue
        if (
            artifact.get("kind") == "video" or source_file.suffix.lower() == ".mp4"
        ) and is_git_lfs_pointer(source_file):
            continue
        published_url = write_hashed_artifact(
            source_file,
            target_root,
            HASHED_ARTIFACTS_DIR,
        )
        artifact_url = artifact_output_url(published_url)
        published_path = published_blob_path(site_dir, published_url)
        content, truncated = read_audit_artifact_content(source_file)
        rendered.append(
            AuditFile(
                path=relative_path,
                url=artifact_url,
                content=content,
                size_bytes=(
                    published_path.stat().st_size
                    if published_path.is_file()
                    else source_file.stat().st_size
                ),
                kind=file_kind(relative_path),
                truncated=truncated,
            )
        )
        published_paths.add(relative_path)
        if relative_path.endswith("screenshots/manifest.json"):
            rendered.extend(
                publish_screenshot_manifest_files(
                    audit_dir,
                    target_root,
                    source_file,
                    published_paths,
                )
            )
    return rendered


def publish_screenshot_manifest_files(
    audit_dir: Path,
    target_root: Path,
    manifest_file: Path,
    published_paths: set[str],
) -> list[AuditFile]:
    """Publish screenshot files referenced by a screenshot caption manifest."""

    try:
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    captions = data.get("captions") if isinstance(data, dict) else None
    if not isinstance(captions, dict):
        return []

    rendered: list[AuditFile] = []
    for caption_path in captions:
        if not isinstance(caption_path, str):
            continue
        relative_path = (
            caption_path
            if caption_path.startswith("artifacts/")
            else f"artifacts/{caption_path}"
        )
        if relative_path in published_paths:
            continue
        source_file, problems = relative_audit_path(
            audit_dir,
            relative_path,
            f"screenshot manifest path {caption_path!r}",
        )
        if (
            problems
            or source_file is None
            or not source_file.is_file()
            or source_file.suffix.lower() not in SCREENSHOT_FILE_SUFFIXES
        ):
            continue
        published_url = write_hashed_artifact(
            source_file,
            target_root,
            HASHED_ARTIFACTS_DIR,
        )
        artifact_url = artifact_output_url(published_url)
        published_path = target_root.parent.parent / published_url
        rendered.append(
            AuditFile(
                path=relative_path,
                url=artifact_url,
                content=None,
                size_bytes=(
                    published_path.stat().st_size
                    if published_path.is_file()
                    else source_file.stat().st_size
                ),
                kind=file_kind(relative_path),
            )
        )
        published_paths.add(relative_path)
    return rendered


def render_metadata_grid(items: list[tuple[str, str]]) -> str:
    """Render a dashboard-style metadata grid."""

    rows = []
    for label, value in items:
        rows.append(
            f"<div><dt>{html.escape(label)}</dt><dd>{value}</dd></div>",
        )
    return '<dl class="metadata-grid attempt-summary">' + "".join(rows) + "</dl>"


def render_metadata_value(value: object, fallback: str = "-") -> str:
    """Render one metadata value."""

    if value is None or value == "":
        return html.escape(fallback)
    return html.escape(str(value))


def render_metadata_code(value: object, fallback: str = "-") -> str:
    """Render one metadata value as code."""

    return f"<code>{render_metadata_value(value, fallback)}</code>"


def write_audit_static_assets(site_dir: Path) -> str:
    """Write static experiment audit CSS and return its page-relative URL."""

    target = site_dir / "static" / AUDIT_CSS_OUTPUT
    target.parent.mkdir(parents=True, exist_ok=True)
    css = audit_css_path().read_text(encoding="utf-8")
    target.write_text(f"{css}\n\n{pygments_css()}\n", encoding="utf-8")
    return f"static/{AUDIT_CSS_OUTPUT}"


def display_sections(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Return displayable section records, adding source for older packets."""

    sections = manifest.get("sections")
    if not isinstance(sections, list):
        return []
    checks = manifest.get("checks")

    def is_displayable(section: object) -> bool:
        return (
            isinstance(section, dict)
            and section.get("display") is not False
            and not (
                section.get("kind") == "checks"
                and (not isinstance(checks, list) or not checks)
            )
        )

    displayable = [section for section in sections if is_displayable(section)]
    has_source = any(
        isinstance(section, dict)
        and (section.get("id") == "source" or section.get("kind") == "source")
        for section in sections
    )
    if not has_source:
        source_section = starter_section("source", "Experiment code", "source")
        report_position = next(
            (
                index
                for index, section in enumerate(sections)
                if isinstance(section, dict)
                if section.get("id") == "report"
            ),
            None,
        )
        insert_at = (
            sum(is_displayable(section) for section in sections[: report_position + 1])
            if report_position is not None
            else len(displayable)
        )
        displayable.insert(insert_at, source_section)
    return displayable


def section_panel_class(section: dict[str, Any]) -> str:
    """Return the section-specific panel class."""

    section_id = str(section.get("id") or "")
    kind = str(section.get("kind") or "")
    if section_id == "report":
        return "report-panel"
    if section_id == "plan":
        return "plan-panel"
    if kind == "evidence":
        return "evidence-panel"
    return ""


def render_markdown_section(audit_dir: Path, section: dict[str, Any]) -> str:
    """Render one markdown section."""

    content = section.get("content")
    if isinstance(content, str):
        return render_markdown_block(strip_redundant_section_heading(content, section))
    section_path, problems = relative_audit_path(
        audit_dir,
        section.get("path"),
        f"{audit_dir / 'audit.json'}: sections[{section.get('id', '')}].path",
    )
    if problems or section_path is None:
        return '<p class="missing">Section path is invalid.</p>'
    if not section_path.is_file():
        return '<p class="missing">Section file missing.</p>'
    content = section_path.read_text(encoding="utf-8")
    return render_markdown_block(strip_redundant_section_heading(content, section))


def render_timeline_section(audit_dir: Path, section: dict[str, Any]) -> str:
    """Render one timeline section."""

    text = section_text(audit_dir, section)
    if text is None:
        return '<p class="missing">Timeline section file missing.</p>'
    entries = parse_timeline_entries(text)
    return render_shared_timeline_section(
        entries,
        fallback_markdown=strip_redundant_section_heading(text, section),
    )


def render_json_section(audit_dir: Path, section: dict[str, Any]) -> str:
    """Render one JSON or metadata section."""

    text = section_text(audit_dir, section)
    if text is None:
        return '<p class="missing">JSON section file missing.</p>'
    return render_json_block(text)


def experiment_entry_point(
    audit_dir: Path,
    manifest: dict[str, Any],
) -> tuple[Path | None, str]:
    """Resolve the experiment entry point declared by an audit packet."""

    experiment = manifest.get("experiment")
    if not isinstance(experiment, dict):
        return None, "experiment.py"
    source_root = experiment_source_root(audit_dir)
    entry_point = experiment.get("entry_point", "experiment.py")
    if not isinstance(entry_point, str):
        return None, "experiment.py"

    entry_relative = Path(entry_point)
    if entry_relative.is_absolute():
        return None, entry_point
    source_file = (source_root / entry_relative).resolve()
    if not source_file.is_relative_to(source_root):
        return None, entry_point
    return source_file, entry_point


def render_source_section(audit_dir: Path, manifest: dict[str, Any]) -> str:
    """Render the experiment entry point from the experiment directory."""

    source_file, entry_point = experiment_entry_point(audit_dir, manifest)
    if source_file is None or not source_file.is_file():
        return (
            '<p class="missing">Experiment entry point missing: '
            f"<code>{html.escape(entry_point)}</code>.</p>"
        )
    content, truncated = read_audit_artifact_content(source_file)
    if content is None:
        return (
            '<p class="missing">Experiment entry point could not be read: '
            f"<code>{html.escape(entry_point)}</code>.</p>"
        )
    return render_file_grid(
        [
            AuditFile(
                path=entry_point,
                url="",
                content=content,
                size_bytes=source_file.stat().st_size,
                kind=file_kind(entry_point),
                truncated=truncated,
            )
        ],
        empty_message="Experiment entry point was not found.",
    )


def section_paths(manifest: dict[str, Any]) -> set[str]:
    """Return paths rendered by markdown sections."""

    paths: set[str] = set()
    for section in display_sections(manifest):
        if section.get("kind") == "markdown" and isinstance(section.get("path"), str):
            paths.add(section["path"])
    return paths


def render_audit_section(
    audit_dir: Path,
    manifest: dict[str, Any],
    section: dict[str, Any],
    evidence: Any,
) -> str:
    """Render one experiment audit section."""

    section_id_raw = str(section.get("id") or "section")
    section_id = html.escape(section_id_raw, quote=True)
    title = html.escape(str(section.get("title") or section_id_raw))
    kind = section.get("kind")

    def render_body() -> str:
        if section_id_raw == "timeline" or kind == "timeline":
            return render_timeline_section(audit_dir, section)
        if kind == "markdown":
            return render_markdown_section(audit_dir, section)
        if kind == "evidence":
            return render_evidence_section(
                evidence,
                include_heading=False,
                include_completeness=False,
                section_id=None,
            )
        if kind == "screenshots":
            return render_screenshot_gallery(evidence, standalone=True)
        if kind == "participant_video":
            return render_participant_video(evidence)
        if kind == "monitor":
            return render_monitor_snapshot(evidence)
        if kind == "performance":
            return render_performance_result(evidence, standalone=True)
        if kind == "data":
            return render_data_exports(evidence)
        if kind == "analysis":
            return render_analysis_notebook(evidence, standalone=True)
        if kind == "source":
            return render_source_section(audit_dir, manifest)
        if kind == "files":
            return render_visible_artifacts(
                evidence, exclude_paths=section_paths(manifest)
            )
        if kind == "json":
            return render_json_section(audit_dir, section)
        if kind == "checks":
            return render_check_list(manifest)
        if kind == "blockers":
            return render_blockers(manifest)
        return '<p class="missing">Section kind is not supported.</p>'

    body = safe_section_html(section_id_raw, render_body)

    panel_class = section_panel_class(section)
    class_attr = f"attempt-panel {panel_class}".strip()
    open_attr = " open" if section_open_by_default(section) else ""
    return (
        f'<details id="{section_id}" class="{html.escape(class_attr, quote=True)}"{open_attr}>'
        f"<summary><h2>{title}</h2></summary>"
        f"{body}"
        "</details>"
    )


def render_check_list(manifest: dict[str, Any]) -> str:
    """Render validation checks from the manifest."""

    checks = manifest.get("checks", [])
    if not isinstance(checks, list) or not checks:
        return "<p>No checks recorded.</p>"

    items: list[str] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        title = html.escape(str(check.get("title") or check.get("id") or "Check"))
        status = html.escape(str(check.get("status") or "unknown"))
        command = check.get("command")
        command_html = (
            f" <code>{html.escape(str(command))}</code>"
            if isinstance(command, str) and command
            else ""
        )
        items.append(f"<li><strong>{status}</strong> {title}{command_html}</li>")
    return f"<ul>{''.join(items)}</ul>"


def render_blockers(manifest: dict[str, Any]) -> str:
    """Render blockers from the manifest."""

    explanation = (
        '<p class="artifact-note">Blockers record required evidence that is not '
        "ready yet, with the next step for resolving each one.</p>"
    )
    blockers = manifest.get("blockers", [])
    if not isinstance(blockers, list) or not blockers:
        return f"{explanation}<p>No blockers recorded.</p>"

    items: list[str] = []
    for blocker in blockers:
        if not isinstance(blocker, dict):
            continue
        reason = html.escape(str(blocker.get("reason") or "Blocker"))
        next_step = html.escape(str(blocker.get("next_step") or ""))
        severity = html.escape(str(blocker.get("severity") or "warning"))
        artifact_id = html.escape(str(blocker.get("artifact_id") or ""))
        items.append(
            f"<li><code>{artifact_id}</code>: {reason} "
            f'<span class="blocker-severity">{severity}</span>'
            f"<br>Next step: {next_step}</li>"
        )
    return f'{explanation}<ul class="blocker-list">{"".join(items)}</ul>'


def section_open_by_default(section: dict[str, Any]) -> bool:
    """Return whether a section panel should start expanded."""

    return str(section.get("id") or "") == "report"


def readiness_score_card(
    manifest: dict[str, Any],
    published_paths: set[str] | None = None,
) -> str:
    """Render a compact readiness summary for the audit hero."""

    artifacts = manifest.get("artifacts")
    blockers = manifest.get("blockers")
    artifact_rows = (
        [a for a in artifacts if isinstance(a, dict)]
        if isinstance(artifacts, list)
        else []
    )
    required = [a for a in artifact_rows if a.get("required") is True]

    def is_present(artifact: dict[str, Any]) -> bool:
        if artifact.get("status") != "present":
            return False
        return published_paths is None or artifact.get("path") in published_paths

    present_required = [a for a in required if is_present(a)]
    present_all = [a for a in artifact_rows if is_present(a)]
    blocker_count = len(blockers) if isinstance(blockers, list) else 0
    if required:
        headline = f"{len(present_required)}/{len(required)} required present"
    else:
        headline = f"{len(present_all)} present"
    detail = f"{blocker_count} blocker{'s' if blocker_count != 1 else ''}"
    return (
        '<div class="score-card">'
        '<span class="score-label">Readiness</span>'
        f"<strong>{html.escape(headline)}</strong>"
        f'<span class="score-detail">{html.escape(detail)}</span>'
        "</div>"
    )


def completeness_from_manifest(
    manifest: dict[str, Any],
    published_paths: set[str] | None = None,
) -> list[Any]:
    """Build completeness rows from declared manifest artifacts."""

    from psynet.audit.model import CompletenessItem

    items: list[CompletenessItem] = []
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return items
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        path = str(artifact.get("path") or "")
        title = str(artifact.get("title") or artifact.get("id") or path)
        status = str(artifact.get("status") or "missing")
        if status == "present" and (published_paths is None or path in published_paths):
            present = True
            detail = "present"
        elif status == "present":
            present = False
            detail = "unavailable"
        elif status == "not_applicable":
            present = False
            detail = "n/a"
        elif status == "blocked":
            present = False
            detail = "blocked"
        else:
            present = False
            detail = "missing"
        items.append(
            CompletenessItem(
                str(artifact.get("id") or path),
                title if title else path,
                present,
                detail,
            )
        )
    return items


def render_audit_site(
    audit_dir: Path,
    site_dir: Path | None = None,
    *,
    allow_invalid: bool = False,
) -> Path:
    """Render a standalone static experiment audit site.

    By default, validation must pass first. Pass ``allow_invalid=True`` to render
    a structurally broken manifest for debugging.
    """

    if not allow_invalid:
        problems = validate_audit(audit_dir)
        if problems:
            raise AuditValidationError(problems)

    try:
        manifest = read_audit_manifest(audit_dir)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{audit_dir / 'audit.json'}: invalid JSON: {exc}",
        ) from exc
    if site_dir is None:
        configured_site = manifest.get("render", {})
        if isinstance(configured_site, dict) and configured_site.get("site_path"):
            resolved_site, site_problems = relative_audit_path(
                audit_dir,
                configured_site.get("site_path"),
                f"{audit_dir / 'audit.json'}: render.site_path",
            )
            if site_problems or resolved_site is None:
                raise ValueError("; ".join(site_problems) or "invalid render.site_path")
            site_dir = resolved_site
        else:
            site_dir = audit_dir / "site"

    site_problems = validate_audit_site_dir(
        audit_dir,
        site_dir,
        "audit site output",
    )
    if site_problems:
        raise ValueError("; ".join(site_problems))
    site_dir.mkdir(parents=True, exist_ok=True)
    rendered_artifacts = publish_audit_artifacts(audit_dir, site_dir, manifest)
    published_paths = {artifact.path for artifact in rendered_artifacts}

    title = audit_display_title(audit_dir, manifest)
    summary = display_implementation_summary(manifest)

    evidence = classify_audit_evidence(rendered_artifacts)
    evidence = replace(
        evidence,
        completeness=completeness_from_manifest(manifest, published_paths),
    )
    css_url = write_audit_static_assets(site_dir)
    sections = display_sections(manifest)
    experiment = manifest.get("experiment", {})
    environment = manifest.get("environment", {})
    checks = manifest.get("checks", [])
    blockers = manifest.get("blockers", [])
    experiment = experiment if isinstance(experiment, dict) else {}
    environment = environment if isinstance(environment, dict) else {}
    check_count = len(checks) if isinstance(checks, list) else 0
    blocker_count = len(blockers) if isinstance(blockers, list) else 0
    metadata = render_metadata_grid(
        [
            ("Entry point", render_metadata_code(experiment.get("entry_point"))),
            ("PsyNet version", render_metadata_value(experiment.get("psynet_version"))),
            ("Git commit", render_metadata_code(experiment.get("git_commit"))),
            ("OS", render_metadata_value(environment.get("os"))),
            ("Python", render_metadata_value(environment.get("python_version"))),
            ("Sections", render_metadata_value(len(sections))),
            ("Checks", render_metadata_value(check_count)),
            ("Blockers", render_metadata_value(blocker_count)),
        ],
    )
    section_nav = "".join(
        f'<li><a href="#{html.escape(str(section.get("id")), quote=True)}">'
        f"{html.escape(str(section.get('title') or section.get('id')))}</a></li>"
        for section in sections
    )
    section_panels = "\n".join(
        render_audit_section(audit_dir, manifest, section, evidence)
        for section in sections
    )

    summary_html = f"<p>{html.escape(summary)}</p>" if summary else ""
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" href="{html.escape(css_url)}">
</head>
<body class="attempt-page">
  <article class="prose attempt-detail">
    <header class="attempt-hero">
      <div>
        <p class="eyebrow">Experiment readiness audit</p>
        <h1>{html.escape(title)}</h1>
        {summary_html}
      </div>
      {readiness_score_card(manifest, published_paths)}
    </header>
    <section class="audit-completeness">
      {render_completeness(evidence)}
    </section>
    {metadata}
    <div class="attempt-layout">
      <aside class="attempt-sidebar" aria-label="Experiment audit sections">
        <nav class="attempt-section-nav">
          <ol>
            {section_nav}
          </ol>
        </nav>
      </aside>
      <div class="attempt-main">
        {section_panels}
      </div>
    </div>
  </article>
  <script>
    document.querySelectorAll("[data-screenshot-gallery]").forEach((gallery) => {{
      const cards = Array.from(gallery.querySelectorAll("[data-screenshot-card]"));
      const panel = gallery.closest(".screenshot-gallery");
      const counter = panel.querySelector("[data-screenshot-counter]");
      const previous = panel.querySelector("[data-screenshot-prev]");
      const next = panel.querySelector("[data-screenshot-next]");
      const caption = panel.querySelector("[data-screenshot-caption]");
      const show = (index) => {{
        cards.forEach((card, cardIndex) => {{ card.hidden = cardIndex !== index; }});
        caption.textContent = cards[index]?.dataset.screenshotCaptionText || "";
        counter.textContent = `${{index + 1}} / ${{cards.length}}`;
        gallery.dataset.screenshotIndex = String(index);
      }};
      const step = (offset) => {{
        const current = Number(gallery.dataset.screenshotIndex || 0);
        show((current + offset + cards.length) % cards.length);
      }};
      if (cards.length > 0) {{
        show(0);
        previous.addEventListener("click", () => step(-1));
        next.addEventListener("click", () => step(1));
      }}
    }});
  </script>
</body>
</html>
"""
    (site_dir / "index.html").write_text(html_text, encoding="utf-8")
    return site_dir


def resolve_audit_site_dir(audit_dir: Path) -> Path:
    """Return the configured rendered-site directory for an audit packet."""

    try:
        manifest = read_audit_manifest(audit_dir)
    except (OSError, ValueError, json.JSONDecodeError):
        return audit_dir / "site"

    configured = manifest.get("render", {})
    if isinstance(configured, dict) and configured.get("site_path"):
        resolved_site, site_problems = relative_audit_path(
            audit_dir,
            configured.get("site_path"),
            f"{audit_dir / 'audit.json'}: render.site_path",
        )
        if site_problems or resolved_site is None:
            raise ValueError("; ".join(site_problems) or "invalid render.site_path")
        site_problems = validate_audit_site_dir(
            audit_dir,
            resolved_site,
            f"{audit_dir / 'audit.json'}: render.site_path",
        )
        if site_problems:
            raise ValueError("; ".join(site_problems))
        return resolved_site
    return audit_dir / "site"


def make_audit_site_server(
    site_dir: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
):
    """Create an HTTP server that serves a rendered audit site directory."""

    import http.server
    from functools import partial

    site_dir = site_dir.resolve()
    if not (site_dir / "index.html").is_file():
        raise FileNotFoundError(
            f"No rendered audit site at {site_dir / 'index.html'}. "
            "Run `psynet audit render` first, or pass `--render`."
        )

    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(site_dir))
    return http.server.ThreadingHTTPServer((host, port), handler)


def serve_audit_site(
    site_dir: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Serve a rendered audit site until interrupted."""

    server = make_audit_site_server(site_dir, host=host, port=port)
    bound_host, bound_port = server.server_address[:2]
    display_host = "127.0.0.1" if bound_host in {"0.0.0.0", "::"} else bound_host
    print(f"Serving experiment audit site at http://{display_host}:{bound_port}/")
    print(f"Root: {site_dir.resolve()}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


__all__ = [
    "artifact_output_url",
    "completeness_from_manifest",
    "experiment_entry_point",
    "make_audit_site_server",
    "publish_audit_artifacts",
    "publish_screenshot_manifest_files",
    "readiness_score_card",
    "render_audit_section",
    "render_audit_site",
    "render_blockers",
    "render_check_list",
    "render_json_section",
    "render_markdown_section",
    "render_metadata_code",
    "render_metadata_grid",
    "render_metadata_value",
    "render_source_section",
    "render_timeline_section",
    "resolve_audit_site_dir",
    "section_open_by_default",
    "section_panel_class",
    "section_paths",
    "serve_audit_site",
    "write_audit_static_assets",
]
