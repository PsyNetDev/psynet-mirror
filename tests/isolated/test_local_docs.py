import pytest
from click.testing import CliRunner

from psynet.bootstrap_cli import _bootstrap
from psynet.local_docs import DocsNotAvailable, _locate_docs, published_docs_url


@pytest.mark.parametrize(
    "version, url",
    [
        ("14.0.0", "https://psynetdev.gitlab.io/PsyNet/v14.0.0/"),
        ("14.0.0rc1", "https://psynetdev.gitlab.io/PsyNet/rc/v14.0.0rc1/"),
        ("14.1.0a0", "https://psynetdev.gitlab.io/PsyNet/alpha/"),
    ],
)
def test_published_docs_url_matches_version(version, url):
    assert published_docs_url(version) == url


def test_bundled_docs_are_used_only_for_their_own_version(tmp_path):
    bundle = tmp_path / "docs_text"
    bundle.mkdir()
    (bundle / "VERSION").write_text("14.0.0\n")

    assert _locate_docs(tmp_path, bundle, "14.0.0") == bundle
    with pytest.raises(DocsNotAvailable, match="PsyNet/v14.0.1/"):
        _locate_docs(tmp_path, bundle, "14.0.1")


def test_docs_show_prints_page_from_source_checkout():
    result = CliRunner().invoke(
        _bootstrap, ["docs", "show", "code/participants/payment"]
    )

    assert result.exit_code == 0, result.output
    assert "Performance reward" in result.output
