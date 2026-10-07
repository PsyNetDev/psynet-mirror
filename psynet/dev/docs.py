"""Build PsyNet's developer documentation from a source checkout."""

import json
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm
from yaspin import yaspin

from psynet.utils import get_psynet_root

LIVE_PREVIEW_IGNORE_PATTERNS = ("_build", "_build/*", "_build/**/*")
LIVE_PREVIEW_RE_IGNORE_PATTERNS = (r".*/_build($|/.*)",)

# Sphinx colours its linkcheck console output, so strip escapes before
# matching progress lines.
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
LINKCHECK_PROGRESS_RE = re.compile(r"^\(\s*.*?: line\s+\d+\)")
LINKCHECK_READ_PROGRESS_RE = re.compile(
    r"^reading sources\.\.\. \[\s*(?P<percent>\d+)%\]"
)
# Statuses that Sphinx counts as linkcheck failures.
LINKCHECK_FAILURE_STATUSES = frozenset({"broken", "timeout"})
# Demo files bundled for ``psynet docs demos``: authored text only. The size
# cap leaves out vendored libraries such as jsPsych and Unity builds.
DEMO_CODE_SUFFIXES = frozenset(
    {".py", ".txt", ".toml", ".md", ".html", ".js", ".css", ".json", ".ini", ".cfg"}
)
DEMO_CODE_MAX_BYTES = 64 * 1024


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
    """Run a Sphinx builder target for PsyNet's documentation."""
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

    command = sphinx_build_command(target, options)

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


def bundle_command() -> Path:
    """Build the plain-text docs that release wheels ship for ``psynet docs``."""
    from psynet import __version__
    from psynet.local_docs import BUNDLED_DOCS_DIR

    docs_dir = assert_docs_available()
    with tempfile.TemporaryDirectory() as tmp:
        text_dir = Path(tmp) / "text"
        command = [
            sys.executable,
            "-m",
            "sphinx",
            "-b",
            "text",
            "-q",
            "-W",
            "--keep-going",
            "-d",
            str(Path(tmp) / "doctrees"),
            ".",
            str(text_dir),
        ]
        try:
            subprocess.run(command, cwd=docs_dir, check=True)
        except subprocess.CalledProcessError as exc:
            raise ValueError(
                f"Text docs build failed with exit code {exc.returncode}: "
                f"{shlex.join(command)}"
            ) from exc

        shutil.rmtree(BUNDLED_DOCS_DIR, ignore_errors=True)
        for source in text_dir.rglob("*.txt"):
            target = BUNDLED_DOCS_DIR / source.relative_to(text_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    _bundle_demo_code(docs_dir.parent, BUNDLED_DOCS_DIR / "demos")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=docs_dir,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    (BUNDLED_DOCS_DIR / "VERSION").write_text(f"{__version__}\n{commit}\n")
    return BUNDLED_DOCS_DIR


def _bundle_demo_code(source_root: Path, target_dir: Path) -> None:
    """Copy the demos' tracked text files, without media or vendored libraries."""
    tracked = subprocess.run(
        ["git", "ls-files", "demos"],
        cwd=source_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    for name in tracked:
        source = source_root / name
        if (
            source.suffix not in DEMO_CODE_SUFFIXES
            or source.name == "constraints.txt"
            or not source.is_file()
            or source.stat().st_size > DEMO_CODE_MAX_BYTES
        ):
            continue
        target = target_dir / Path(name).relative_to("demos")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


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
    strict: bool = False,
) -> int:
    """Run Sphinx's linkcheck builder and print a structured summary.

    This is a wrapper around Sphinx's ``linkcheck`` builder. After Sphinx
    finishes, broken links are reprinted grouped by failure category.

    By default only :data:`LINKCHECK_BLOCKING_CATEGORIES` fail the check;
    other failures usually come from the remote site or the network and are
    only reported. ``strict=True`` fails on every broken link.
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
    command = sphinx_build_command("linkcheck", options)

    result = run_linkcheck_process(
        command,
        docs_dir=docs_dir,
        show_progress=show_progress,
    )
    issues = parse_linkcheck_issues(build_dir)

    print(format_linkcheck_summary(issues))

    if result.returncode != 0:
        if issues:
            blocking = [
                issue
                for issue in issues
                if _categorize_linkcheck_issue(issue) in LINKCHECK_BLOCKING_CATEGORIES
            ]
            if strict:
                raise ValueError(
                    f"Linkcheck found {len(issues)} broken link(s); see summary above."
                )
            if blocking:
                raise ValueError(
                    f"Linkcheck found {len(blocking)} broken link(s) to fix: "
                    "internal links, missing anchors, or pages not found. "
                    "See summary above."
                )
            print(
                f"\nNot failing on these {len(issues)} link(s): they usually "
                "come from the remote site or the network. Pass --strict to "
                "fail on them."
            )
            return 0
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
                    for raw_line in process.stdout:
                        output.append(raw_line)
                        line = ANSI_ESCAPE_RE.sub("", raw_line)
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


def parse_linkcheck_issues(build_dir: Path) -> list[LinkcheckIssue]:
    """Read failed links from Sphinx's ``linkcheck/output.json``.

    Sphinx writes one JSON object per checked link. Reading that file keeps
    the summary independent of the console format, which is coloured and
    changes between Sphinx releases.
    """
    output_json = build_dir / "linkcheck" / "output.json"
    if not output_json.exists():
        return []

    issues = []
    for line in output_json.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("status") not in LINKCHECK_FAILURE_STATUSES:
            continue
        issues.append(
            LinkcheckIssue(
                source=entry.get("filename", ""),
                line=int(entry.get("lineno") or 0),
                status=entry["status"],
                url=entry.get("uri", ""),
                reason=entry.get("info") or "",
            )
        )
    return issues


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

# Categories that mean the docs themselves are wrong, so they fail
# linkcheck even without ``strict``.
LINKCHECK_BLOCKING_CATEGORIES = frozenset(
    {
        "Internal documentation links",
        "Missing anchors",
        "Pages not found (404)",
    }
)


def _categorize_linkcheck_issue(issue: LinkcheckIssue) -> str:
    """Assign a broken link to a category based on its URL, status, and reason."""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", issue.url):
        return "Internal documentation links"
    reason = issue.reason
    # Sphinx labels timeouts "broken" when linkcheck_report_timeouts_as_broken
    # is set, so the reason is the reliable signal.
    if issue.status == "timeout" or "timed out" in reason.lower():
        return "Timeouts"
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
    if Path.cwd().resolve() != root or not (docs_dir / "conf.py").exists():
        raise ValueError(
            "This command must be run from the PsyNet source checkout root directory "
            "with docs/conf.py present."
        )
    return docs_dir


def sphinx_build_command(target: str, options: list[str]) -> list[str]:
    """Build a ``python -m sphinx -M`` command for a docs/ working directory."""
    return [
        sys.executable,
        "-m",
        "sphinx",
        "-M",
        target,
        ".",
        "_build",
        *options,
    ]


def build_sphinx_options(
    *,
    strict: bool,
    jobs: str | None,
    sphinx_options: tuple[str, ...],
) -> list[str]:
    """Compose extra flags for ``python -m sphinx -M``."""
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
