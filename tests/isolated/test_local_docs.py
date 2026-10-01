from pathlib import Path

import pytest
from click.testing import CliRunner

from psynet.bootstrap_cli import _bootstrap
from psynet.dev.docs import _bundle_demo_code
from psynet.local_docs import DocsError, _find_page, _locate_docs, published_docs_url
from psynet.utils import get_psynet_root


@pytest.mark.parametrize(
    "version, url",
    [
        ("14.0.0", "https://psynetdev.gitlab.io/PsyNet/v14.0.0/"),
        ("14.0.0.post1", "https://psynetdev.gitlab.io/PsyNet/v14.0.0/"),
        ("14.0.0rc1", "https://psynetdev.gitlab.io/PsyNet/rc/v14.0.0rc1/"),
        ("14.1.0a0", "https://psynetdev.gitlab.io/PsyNet/alpha/"),
        ("14.1.0.dev1", "https://psynetdev.gitlab.io/PsyNet/alpha/"),
    ],
)
def test_published_docs_url_matches_version(version, url):
    assert published_docs_url(version) == url


def test_bundled_docs_are_used_only_for_their_own_version(tmp_path):
    bundle = tmp_path / "docs_text"
    bundle.mkdir()
    (bundle / "VERSION").write_text("14.0.0\nabc123\n")

    assert _locate_docs(tmp_path, bundle, "14.0.0") == bundle
    with pytest.raises(DocsError, match="PsyNet/v14.0.1/"):
        _locate_docs(tmp_path, bundle, "14.0.1")


def test_find_page_accepts_urls_and_stays_inside_the_docs(tmp_path):
    (tmp_path / "code").mkdir()
    page = tmp_path / "code" / "payment.txt"
    page.write_text("Payment")
    (tmp_path / "conf.py").write_text("")
    (tmp_path.parent / "secret.txt").write_text("")

    url = "https://psynetdev.gitlab.io/PsyNet/v14.0.0/code/payment.html#bonus"
    assert _find_page(tmp_path, url) == page.resolve()
    assert _find_page(tmp_path, "code/payment") == page.resolve()
    for name in ["conf.py", "../secret"]:
        with pytest.raises(DocsError):
            _find_page(tmp_path, name)


def test_docs_show_prints_page_from_source_checkout():
    result = CliRunner().invoke(
        _bootstrap, ["docs", "show", "code/participants/payment"]
    )

    assert result.exit_code == 0, result.output
    assert result.output.startswith("=======\nPayment\n")


def test_docs_demos_prints_demos_from_source_checkout():
    result = CliRunner().invoke(_bootstrap, ["docs", "demos"])

    assert result.exit_code == 0, result.output
    assert (Path(result.output.strip()) / "experiments" / "hello_world").is_dir()


def test_bundled_demo_code_keeps_authored_files_only(tmp_path):
    _bundle_demo_code(get_psynet_root(), tmp_path)

    assert (
        tmp_path / "experiments" / "rock_paper_scissors" / "experiment.py"
    ).is_file()
    assert not (
        tmp_path / "experiments" / "jspsych" / "static" / "jspsych" / "jspsych.js"
    ).exists()
    assert not list(tmp_path.rglob("*.wav"))
