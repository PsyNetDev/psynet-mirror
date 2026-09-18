import re
import subprocess

import pytest

from psynet.dev import docs as docs_module
from psynet.utils import working_directory


@pytest.fixture
def source_checkout(tmp_path, monkeypatch):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "Makefile").write_text("html:\n", encoding="utf-8")
    monkeypatch.setattr(docs_module, "get_psynet_root", lambda: tmp_path)
    return tmp_path


def test_make_command_runs_docs_make_target_with_options(source_checkout, monkeypatch):
    build_dir = source_checkout / "docs" / "_build"
    build_dir.mkdir()
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(docs_module.subprocess, "run", fake_run)

    with working_directory(source_checkout):
        assert (
            docs_module.make_command(
                target="dirhtml",
                clean=True,
                strict=True,
                jobs="auto",
                sphinx_options=("--nitpicky",),
            )
            == 0
        )

    assert not build_dir.exists()
    assert calls == [
        (
            [
                "make",
                "dirhtml",
                "SPHINXOPTS=--nitpicky -W --keep-going -j auto",
            ],
            {
                "cwd": source_checkout / "docs",
                "check": True,
            },
        )
    ]


def test_make_command_defaults_to_html_with_serial_jobs(source_checkout, monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(docs_module.subprocess, "run", fake_run)

    with working_directory(source_checkout):
        assert docs_module.make_command() == 0

    assert calls == [
        (
            ["make", "html", "SPHINXOPTS=-j 1"],
            {
                "cwd": source_checkout / "docs",
                "check": True,
            },
        )
    ]


def test_make_command_live_preview_runs_sphinx_autobuild(source_checkout, monkeypatch):
    calls = []

    def fake_run_live_preview_process(command, docs_dir):
        calls.append((command, docs_dir))

    monkeypatch.setattr(
        docs_module,
        "run_live_preview_process",
        fake_run_live_preview_process,
    )
    monkeypatch.setattr(docs_module.shutil, "which", lambda command: command)
    monkeypatch.setattr(
        docs_module,
        "assert_live_preview_port_available",
        lambda port: None,
    )

    with working_directory(source_checkout):
        assert (
            docs_module.make_command(
                live_preview=True,
                live_preview_port=8001,
                strict=True,
                jobs="auto",
                sphinx_options=("--nitpicky",),
            )
            == 0
        )

    assert calls == [
        (
            [
                "sphinx-autobuild",
                "--nitpicky",
                "-W",
                "--keep-going",
                "-j",
                "1",
                "--no-color",
                "--open-browser",
                "--port",
                "8001",
                "--ignore",
                "_build",
                "--ignore",
                str(source_checkout / "docs" / "_build"),
                "--ignore",
                "_build/*",
                "--ignore",
                str(source_checkout / "docs" / "_build" / "*"),
                "--ignore",
                "_build/**/*",
                "--ignore",
                str(source_checkout / "docs" / "_build" / "**" / "*"),
                "--re-ignore",
                r".*/_build($|/.*)",
                ".",
                str(source_checkout / "docs" / "_build" / "html"),
            ],
            source_checkout / "docs",
        )
    ]


def test_live_preview_requires_available_port(monkeypatch):
    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def settimeout(self, timeout):
            pass

        def connect_ex(self, address):
            return 0

    monkeypatch.setattr(docs_module.socket, "socket", lambda *args: FakeSocket())

    with pytest.raises(ValueError, match="Port 8000 is already in use"):
        docs_module.assert_live_preview_port_available(8000)


def test_live_preview_process_streams_output(monkeypatch, tmp_path, capsys):
    class FakeProcess:
        stdout = [
            "[sphinx-autobuild] Starting initial build\n",
            "[sphinx-autobuild] Waiting to detect changes...\n",
        ]

        def wait(self):
            return 0

        def terminate(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_popen(command, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(docs_module.subprocess, "Popen", fake_popen)

    docs_module.run_live_preview_process(
        ["sphinx-autobuild"],
        tmp_path,
    )

    assert "Starting initial build" in capsys.readouterr().out


def test_live_preview_requires_sphinx_autobuild(source_checkout, monkeypatch):
    monkeypatch.setattr(docs_module.shutil, "which", lambda command: None)

    with working_directory(source_checkout):
        with pytest.raises(ValueError, match="sphinx-autobuild is required"):
            docs_module.make_command(live_preview=True)


def test_make_command_requires_source_checkout_root(source_checkout, tmp_path):
    other_dir = tmp_path / "elsewhere"
    other_dir.mkdir()

    with working_directory(other_dir):
        with pytest.raises(ValueError, match="source checkout root"):
            docs_module.make_command()


def test_make_command_reports_failed_make_command(source_checkout, monkeypatch):
    def fake_run(command, **kwargs):
        raise subprocess.CalledProcessError(2, command)

    monkeypatch.setattr(docs_module.subprocess, "run", fake_run)

    with working_directory(source_checkout):
        with pytest.raises(ValueError, match="Docs build failed with exit code 2"):
            docs_module.make_command(target="linkcheck")


def test_linkcheck_command_prints_structured_summary(
    source_checkout, monkeypatch, capsys
):
    output = (
        "/tmp/project/docs/api/utils.rst:3: WARNING: broken link: "
        "http://localhost:5000 (connection refused)\n"
        "(deploy/ssh_server: line 205) broken "
        "https://your-app-name.example.com - certificate mismatch\n"
    )

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout=output, stderr="")

    monkeypatch.setattr(docs_module.subprocess, "run", fake_run)

    with working_directory(source_checkout):
        with pytest.raises(ValueError, match="Linkcheck found 2 broken link"):
            docs_module.linkcheck_command(clean=False, show_progress=False)

    summary = capsys.readouterr().out
    assert "Linkcheck found 2 broken link(s):" in summary
    assert (
        "- /tmp/project/docs/api/utils.rst:3 [broken] http://localhost:5000" in summary
    )
    assert (
        "- deploy/ssh_server:205 [broken] https://your-app-name.example.com" in summary
    )
    assert "certificate mismatch" in summary


def test_linkcheck_command_updates_progress(source_checkout, monkeypatch, capsys):
    updates = []
    postfixes = []
    spinner_texts = []

    class FakeProcess:
        stdout = [
            "reading sources... [ 42%] tutorials/assets\n",
            "(api/graphics: line    3) ok        https://www.w3.org/TR/SVG/\n",
            "(api/utils: line    3) broken    http://localhost:5000 - refused\n",
        ]

        def wait(self):
            return 1

        def terminate(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    class FakeProgress:
        def __init__(self, **kwargs):
            self.n = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def update(self, n=1):
            updates.append(n)
            self.n += n

        def set_postfix_str(self, value):
            postfixes.append(value)

    class FakeSpinner:
        def __init__(self, text, color):
            self.text = text
            spinner_texts.append(text)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        @property
        def text(self):
            return self._text

        @text.setter
        def text(self, value):
            self._text = value
            spinner_texts.append(value)

    monkeypatch.setattr(
        docs_module.subprocess,
        "Popen",
        lambda command, **kwargs: FakeProcess(),
    )
    monkeypatch.setattr(docs_module, "tqdm", FakeProgress)
    monkeypatch.setattr(docs_module, "yaspin", FakeSpinner)

    with working_directory(source_checkout):
        with pytest.raises(ValueError, match="Linkcheck found 1 broken link"):
            docs_module.linkcheck_command(clean=False)

    assert updates == [42, 58]
    assert spinner_texts == [
        "Starting linkcheck...",
        "Starting linkcheck...",
        "Reading docs (42%)",
        "Checked 1 links",
        "Checked 2 links",
    ]
    assert postfixes == []
    assert "http://localhost:5000" in capsys.readouterr().out


def test_parse_linkcheck_warning_relativizes_docs_paths(source_checkout):
    line = (
        f"{source_checkout}/docs/api/utils.rst:3: WARNING: broken link: "
        "http://localhost:5000 (connection refused)"
    )

    issues = docs_module.parse_linkcheck_issues(line, source_checkout / "docs")

    assert issues == [
        docs_module.LinkcheckIssue(
            source="api/utils.rst",
            line=3,
            status="broken",
            url="http://localhost:5000",
            reason="connection refused",
        )
    ]


def test_format_linkcheck_summary_groups_issues_by_category():
    def issue(source, line, url, reason="", status="broken"):
        return docs_module.LinkcheckIssue(
            source=source, line=line, status=status, url=url, reason=reason
        )

    issues = [
        issue("learning/how_to_learn", 21, "../tutorials/index.html"),
        issue("learning/how_to_learn", 15, "../example_experiments/index.html"),
        issue(
            "index",
            8,
            "https://dallinger.readthedocs.io/en/latest/",
            "404 Client Error: Not Found for url: ...",
        ),
        issue(
            "tutorials/assets",
            318,
            "https://linux.die.net/man/1/scp",
            "403 Client Error: Forbidden for url: ...",
        ),
        issue(
            "api/js_synth",
            1,
            "https://github.com/Tonejs/Tone.js/blob/c313bc6/Sampler.ts#L297",
            "Anchor 'L297' not found",
        ),
        issue(
            "tutorials/demography",
            35,
            "https://gold-msi.org",
            "Max retries exceeded with url: / (Caused by SSLError(...))",
        ),
        issue(
            "api/utils",
            3,
            "http://localhost:5000",
            "Max retries exceeded with url: / (Connection refused)",
        ),
        issue("tutorials/slow", 1, "https://slow.example.com", status="timeout"),
        issue("tutorials/odd", 1, "https://odd.example.com", "mysterious failure"),
    ]

    summary = docs_module.format_linkcheck_summary(issues)

    headers = [
        line
        for line in summary.splitlines()
        if re.search(r" \(\d+\):$", line) and not line.startswith("Linkcheck found")
    ]
    assert headers == [
        "Internal documentation links (2):",
        "Missing anchors (1):",
        "Pages not found (404) (1):",
        "Access denied (403), possibly bot-blocked (1):",
        "SSL/TLS errors (1):",
        "Connection errors (1):",
        "Timeouts (1):",
        "Other (1):",
    ]
    assert summary.startswith("Linkcheck found 9 broken link(s):")
    # Issues are sorted by source and line within each category.
    assert summary.index("learning/how_to_learn:15") < summary.index(
        "learning/how_to_learn:21"
    )


def test_format_linkcheck_summary_keeps_unknown_categories(monkeypatch):
    issue = docs_module.LinkcheckIssue(
        source="api/utils",
        line=1,
        status="broken",
        url="https://x.example.com",
        reason="",
    )
    monkeypatch.setattr(
        docs_module, "_categorize_linkcheck_issue", lambda _: "Surprise"
    )

    summary = docs_module.format_linkcheck_summary([issue])

    assert "Surprise (1):" in summary
    assert "https://x.example.com" in summary


def test_format_linkcheck_summary_without_issues():
    assert (
        docs_module.format_linkcheck_summary([]) == "Linkcheck found no broken links."
    )


def test_open_requires_html_target(source_checkout, monkeypatch):
    monkeypatch.setattr(
        docs_module.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0),
    )

    with working_directory(source_checkout):
        with pytest.raises(ValueError, match="only supported for the html docs target"):
            docs_module.make_command(target="dirhtml", open_browser=True)


def test_live_preview_requires_html_target(source_checkout, monkeypatch):
    monkeypatch.setattr(
        docs_module.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0),
    )

    with working_directory(source_checkout):
        with pytest.raises(ValueError, match="only supported for the html docs target"):
            docs_module.make_command(target="dirhtml", live_preview=True)
