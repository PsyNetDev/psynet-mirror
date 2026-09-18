"""Build PsyNet's developer documentation from a source checkout."""

import re
import shlex
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm
from yaspin import yaspin

from psynet.utils import get_psynet_root

LIVE_PREVIEW_IGNORE_PATTERNS = ("_build", "_build/*", "_build/**/*")
LIVE_PREVIEW_RE_IGNORE_PATTERNS = (r".*/_build($|/.*)",)

LINKCHECK_WARNING_RE = re.compile(
    r"^(?P<path>.*?):(?P<line>\d+): WARNING: broken link: "
    r"(?P<url>\S+)(?: \((?P<reason>.*)\))?$"
)
LINKCHECK_STATUS_RE = re.compile(
    r"^\(\s*(?P<source>.*?): line\s+(?P<line>\d+)\) "
    r"(?P<status>broken|timeout)\s+(?P<url>\S+)"
    r"(?:\s+-\s+(?P<reason>.*))?$"
)
LINKCHECK_PROGRESS_RE = re.compile(
    r"^\(\s*.*?: line\s+\d+\) "
    r"(?:ok|broken|redirected|timeout|ignored|working)\s+"
)
LINKCHECK_READ_PROGRESS_RE = re.compile(
    r"^reading sources\.\.\. \[\s*(?P<percent>\d+)%\]"
)


@dataclass(frozen=True)
class LinkcheckIssue:
    source: str
    line: int
    status: str
    url: str
    reason: str


def make_command(
    target: str = "html",
    *,
    clean: bool = False,
    open_browser: bool = False,
    live_preview: bool = False,
    live_preview_port: int = 8000,
    strict: bool = False,
    jobs: str | None = "1",
    sphinx_options: tuple[str, ...] = (),
) -> int:
    """Run the Sphinx Makefile target for PsyNet's documentation."""
    docs_dir = assert_docs_available()
    build_dir = docs_dir / "_build"

    if clean and build_dir.exists():
        shutil.rmtree(build_dir)

    options = build_sphinx_options(
        strict=strict,
        jobs="1" if live_preview else jobs,
        sphinx_options=sphinx_options,
    )
    if live_preview:
        run_live_preview(
            target=target,
            options=options,
            docs_dir=docs_dir,
            build_dir=build_dir,
            port=live_preview_port,
        )
        return 0

    command = ["make", target]
    if options:
        command.append(f"SPHINXOPTS={shlex.join(options)}")

    try:
        subprocess.run(command, cwd=docs_dir, check=True)
    except subprocess.CalledProcessError as exc:
        raise ValueError(
            f"Docs build failed with exit code {exc.returncode}: "
            f"{shlex.join(str(arg) for arg in command)}"
        ) from exc

    if open_browser:
        open_html_index(target, build_dir)

    return 0


def run_live_preview(
    *,
    target: str,
    options: list[str],
    docs_dir: Path,
    build_dir: Path,
    port: int,
) -> None:
    """Serve the HTML docs with automatic rebuilds and browser reloads."""
    if target != "html":
        raise ValueError("--live-preview is only supported for the html docs target.")

    if shutil.which("sphinx-autobuild") is None:
        raise ValueError(
            "sphinx-autobuild is required for --live-preview. "
            "Install or update the PsyNet dev dependencies, for example with "
            "`uv pip install -e '.[dev,slack]'`."
        )

    assert_live_preview_port_available(port)

    command = [
        "sphinx-autobuild",
        *options,
        "--no-color",
        "--open-browser",
        "--port",
        str(port),
    ]
    for pattern in LIVE_PREVIEW_IGNORE_PATTERNS:
        command.extend(["--ignore", pattern])
        command.extend(["--ignore", str(docs_dir / pattern)])
    for pattern in LIVE_PREVIEW_RE_IGNORE_PATTERNS:
        command.extend(["--re-ignore", pattern])

    run_live_preview_process(
        [*command, ".", str(build_dir / "html")],
        docs_dir,
    )


def assert_live_preview_port_available(port: int, host: str = "127.0.0.1") -> None:
    """Fail before building docs if the live-preview server port is occupied."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        is_in_use = sock.connect_ex((host, port)) == 0

    if is_in_use:
        raise ValueError(
            f"Port {port} is already in use. Stop the existing docs preview server "
            f"or choose another port with `--port {port + 1}`."
        )


def run_live_preview_process(
    command: list[str],
    docs_dir: Path,
) -> None:
    """Run sphinx-autobuild."""
    with subprocess.Popen(
        command,
        cwd=docs_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    ) as process:
        assert process.stdout is not None
        try:
            for line in process.stdout:
                print(line, end="")

            return_code = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            process.wait()
            raise

    if return_code:
        raise subprocess.CalledProcessError(return_code, command)


def linkcheck_command(
    *,
    clean: bool = True,
    jobs: str | None = "1",
    sphinx_options: tuple[str, ...] = (),
    show_progress: bool = True,
) -> int:
    """Run Sphinx's linkcheck builder and print a structured summary.

    This is a wrapper around `make linkcheck` in docs/. After Sphinx
    finishes, broken links are reprinted grouped by failure category.
    """
    docs_dir = assert_docs_available()
    build_dir = docs_dir / "_build"

    if clean and build_dir.exists():
        shutil.rmtree(build_dir)

    options = build_sphinx_options(
        strict=False,
        jobs=jobs,
        sphinx_options=sphinx_options,
    )
    command = ["make", "linkcheck"]
    if options:
        command.append(f"SPHINXOPTS={shlex.join(options)}")

    result = run_linkcheck_process(
        command,
        docs_dir=docs_dir,
        show_progress=show_progress,
    )
    output = "\n".join(part for part in [result.stdout, result.stderr] if part)
    issues = parse_linkcheck_issues(output, docs_dir)

    print(format_linkcheck_summary(issues))

    if result.returncode != 0:
        if issues:
            raise ValueError(
                f"Linkcheck found {len(issues)} broken link(s); see summary above."
            )
        raise ValueError(
            f"Linkcheck failed with exit code {result.returncode}: "
            f"{shlex.join(str(arg) for arg in command)}"
        )

    return 0


def run_linkcheck_process(
    command: list[str],
    *,
    docs_dir: Path,
    show_progress: bool,
) -> subprocess.CompletedProcess:
    """Run linkcheck, optionally showing progress as links are checked."""
    if not show_progress:
        return subprocess.run(
            command,
            cwd=docs_dir,
            check=False,
            capture_output=True,
            text=True,
        )

    output = []
    with subprocess.Popen(
        command,
        cwd=docs_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    ) as process:
        assert process.stdout is not None
        try:
            checked_links = 0
            last_read_percent = -1
            with yaspin(text="Starting linkcheck...", color="green") as spinner:
                with tqdm(
                    desc="Linkcheck",
                    total=100,
                    unit="%",
                    dynamic_ncols=True,
                    leave=True,
                    bar_format="{desc}: {percentage:3.0f}%|{bar}|{postfix}",
                ) as progress:
                    for line in process.stdout:
                        output.append(line)
                        read_match = LINKCHECK_READ_PROGRESS_RE.match(line)
                        if read_match is not None:
                            read_percent = int(read_match.group("percent"))
                            if read_percent != last_read_percent:
                                progress.update(read_percent - progress.n)
                                spinner.text = f"Reading docs ({read_percent}%)"
                                last_read_percent = read_percent
                        elif LINKCHECK_PROGRESS_RE.match(line):
                            checked_links += 1
                            if progress.n < 100:
                                progress.update(100 - progress.n)
                            spinner.text = f"Checked {checked_links} links"

            return_code = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            process.wait()
            raise

    return subprocess.CompletedProcess(
        command,
        return_code,
        stdout="".join(output),
        stderr="",
    )


def parse_linkcheck_issues(output: str, docs_dir: Path) -> list[LinkcheckIssue]:
    """Parse broken links from Sphinx linkcheck output."""
    issues = []
    for line in output.splitlines():
        issue = parse_linkcheck_warning(line, docs_dir) or parse_linkcheck_status(line)
        if issue is not None:
            issues.append(issue)
    return issues


def parse_linkcheck_warning(line: str, docs_dir: Path) -> LinkcheckIssue | None:
    match = LINKCHECK_WARNING_RE.match(line)
    if match is None:
        return None

    source = match.group("path")
    try:
        source = str(Path(source).resolve().relative_to(docs_dir.resolve()))
    except ValueError:
        pass

    return LinkcheckIssue(
        source=source,
        line=int(match.group("line")),
        status="broken",
        url=match.group("url"),
        reason=match.group("reason") or "",
    )


def parse_linkcheck_status(line: str) -> LinkcheckIssue | None:
    match = LINKCHECK_STATUS_RE.match(line)
    if match is None:
        return None

    return LinkcheckIssue(
        source=match.group("source").strip(),
        line=int(match.group("line")),
        status=match.group("status"),
        url=match.group("url"),
        reason=match.group("reason") or "",
    )


LINKCHECK_CATEGORIES = (
    "Internal documentation links",
    "Missing anchors",
    "Pages not found (404)",
    "Access denied (403), possibly bot-blocked",
    "SSL/TLS errors",
    "Connection errors",
    "Timeouts",
    "Other",
)


def _categorize_linkcheck_issue(issue: LinkcheckIssue) -> str:
    """Assign a broken link to a category based on its URL, status, and reason."""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", issue.url):
        return "Internal documentation links"
    if issue.status == "timeout":
        return "Timeouts"
    reason = issue.reason
    if re.search(r"\bAnchor\b.*not found", reason):
        return "Missing anchors"
    if "404" in reason:
        return "Pages not found (404)"
    if "403" in reason:
        return "Access denied (403), possibly bot-blocked"
    if "SSL" in reason or "certificate" in reason.lower():
        return "SSL/TLS errors"
    if re.search(r"Connection refused|NewConnectionError|Max retries", reason):
        return "Connection errors"
    return "Other"


def format_linkcheck_summary(issues: list[LinkcheckIssue]) -> str:
    """Format linkcheck issues for terminal output, grouped by failure category."""
    if not issues:
        return "Linkcheck found no broken links."

    grouped: dict[str, list[LinkcheckIssue]] = {}
    for issue in issues:
        grouped.setdefault(_categorize_linkcheck_issue(issue), []).append(issue)

    # Safety net: append any categories not listed in LINKCHECK_CATEGORIES
    # (e.g. after a partial rename) so no issue is silently dropped.
    extra_categories = [c for c in grouped if c not in LINKCHECK_CATEGORIES]

    lines = [f"Linkcheck found {len(issues)} broken link(s):"]
    for category in (*LINKCHECK_CATEGORIES, *sorted(extra_categories)):
        category_issues = grouped.get(category)
        if not category_issues:
            continue
        lines.append("")
        lines.append(f"{category} ({len(category_issues)}):")
        for issue in sorted(category_issues, key=lambda i: (i.source, i.line)):
            lines.append(f"- {issue.source}:{issue.line} [{issue.status}] {issue.url}")
            if issue.reason:
                lines.append(f"  {issue.reason}")
    return "\n".join(lines)


def assert_docs_available() -> Path:
    """Return the docs directory, or fail if not in the source checkout root."""
    root = get_psynet_root().resolve()
    docs_dir = root / "docs"
    if Path.cwd().resolve() != root or not (docs_dir / "Makefile").exists():
        raise ValueError(
            "This command must be run from the PsyNet source checkout root directory "
            "with docs/Makefile present."
        )
    return docs_dir


def build_sphinx_options(
    *,
    strict: bool,
    jobs: str | None,
    sphinx_options: tuple[str, ...],
) -> list[str]:
    """Compose Sphinx options to pass through the docs Makefile."""
    options = list(sphinx_options)
    if strict:
        options.extend(["-W", "--keep-going"])
    if jobs:
        options.extend(["-j", jobs])
    return options


def open_html_index(target: str, build_dir: Path) -> None:
    """Open the built HTML documentation index in the default browser."""
    if target != "html":
        raise ValueError("--open is only supported for the html docs target.")

    open_command = shutil.which("xdg-open") or shutil.which("open")
    if open_command is None:
        raise ValueError("Could not find xdg-open or open to display the HTML docs.")

    command = [open_command, str(build_dir / "html" / "index.html")]
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError as exc:
        raise ValueError(
            f"Could not open the HTML docs; command failed with exit code "
            f"{exc.returncode}: {shlex.join(str(arg) for arg in command)}"
        ) from exc
