"""Click commands for `psynet dev`.

These commands are part of the installed package but only function from a
PsyNet source checkout, where `CHANGELOG.md` and `changelog.d/` are present.
"""

import subprocess

import click

from psynet.dev import changelog as changelog_module
from psynet.dev import ci as ci_module
from psynet.dev import docs as docs_module
from psynet.dev import experiments as experiments_module
from psynet.dev import slack_announcement as slack_announcement_module

CHANGELOG_CATEGORIES = (
    "breaking",
    "added",
    "changed",
    "deprecated",
    "removed",
    "fixed",
    "updated",
    "documentation",
)


def assert_changelog_available() -> None:
    """Fail fast when not running from a PsyNet source checkout."""
    if (
        not changelog_module.CHANGELOG_PATH.exists()
        or not changelog_module.FRAGMENTS_DIR.exists()
    ):
        raise click.UsageError(
            "Run from a PsyNet source checkout: "
            f"{changelog_module.CHANGELOG_PATH} and {changelog_module.FRAGMENTS_DIR} "
            "must exist in the current directory."
        )


@click.group("dev")
def dev():
    """Developer utilities for PsyNet source checkouts."""


@dev.group("ci")
def ci():
    """Maintain CI build inputs from a PsyNet source checkout."""


@ci.command("update-dallinger-constraints")
@click.option(
    "--skip-compile-check",
    is_flag=True,
    help="Refresh the snapshot without validating Docker constraints compilation.",
)
def update_dallinger_constraints(skip_compile_check):
    """Refresh the vendored Dallinger dev-requirements snapshot."""
    ci_module.update_dallinger_constraints_command(check_compile=not skip_compile_check)


@dev.group("experiments")
def experiments():
    """Manage canonical experiment templates from a PsyNet source checkout."""


@experiments.command("update")
def update_experiments():
    """Update canonical experiment templates."""
    try:
        experiments_module.update_command()
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


@dev.group("docs")
def docs():
    """Build PsyNet documentation from a source checkout."""


@docs.command("make")
@click.argument("target", default="html", metavar="[TARGET]")
@click.option(
    "--clean",
    "-c",
    is_flag=True,
    help="Delete docs/_build before running the Sphinx target.",
)
@click.option(
    "--open",
    "open_browser",
    is_flag=True,
    help="Open the HTML docs after building. Implied by --live-preview.",
)
@click.option(
    "--live-preview",
    is_flag=True,
    help="Serve the HTML docs with sphinx-autobuild and reload on changes.",
)
@click.option(
    "--port",
    "live_preview_port",
    default=8000,
    show_default=True,
    type=int,
    help="Port to use with --live-preview.",
)
@click.option(
    "--strict",
    is_flag=True,
    help="Treat Sphinx warnings as errors and keep going to report all warnings.",
)
@click.option(
    "--jobs",
    "-j",
    default="1",
    show_default=True,
    help="Parallel Sphinx build jobs to pass through SPHINXOPTS, e.g. 1, 4, or auto.",
)
@click.option(
    "--sphinx-option",
    "sphinx_options",
    multiple=True,
    help=(
        "Extra option passed to Sphinx via SPHINXOPTS; repeat as needed. "
        "Common examples: --nitpicky, -E, -a, -T, -v."
    ),
)
def make_docs(
    target,
    clean,
    open_browser,
    live_preview,
    live_preview_port,
    strict,
    jobs,
    sphinx_options,
):
    """Run a Sphinx Makefile TARGET for PsyNet docs.

    TARGET defaults to html, matching `make html` in docs/.

    Uses --jobs 1 by default for deterministic output. Pass extra Sphinx flags
    with --sphinx-option. Pass --live-preview to serve the HTML docs with
    sphinx-autobuild and reload the browser when files change.
    """
    try:
        if live_preview:
            open_browser = True
        docs_module.make_command(
            target=target,
            clean=clean,
            open_browser=open_browser,
            live_preview=live_preview,
            live_preview_port=live_preview_port,
            strict=strict,
            jobs=jobs,
            sphinx_options=sphinx_options,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(
            f"Docs command failed with exit code {exc.returncode}."
        ) from exc


@docs.command("linkcheck")
@click.option(
    "--clean/--no-clean",
    default=True,
    show_default=True,
    help="Delete docs/_build before checking links.",
)
@click.option(
    "--jobs",
    "-j",
    default="1",
    show_default=True,
    help="Parallel Sphinx jobs to pass through SPHINXOPTS, e.g. 1, 4, or auto.",
)
@click.option(
    "--sphinx-option",
    "sphinx_options",
    multiple=True,
    help="Extra option passed to Sphinx via SPHINXOPTS; repeat as needed.",
)
def linkcheck_docs(clean, jobs, sphinx_options):
    """Wrap Sphinx's linkcheck builder and summarize broken links.

    Runs `make linkcheck` in docs/ (the same Sphinx target as
    `psynet dev docs make linkcheck`), then prints broken links grouped
    by failure category.

    Cleans docs/_build by default. For faster local reruns, pass
    --no-clean. Pass extra Sphinx flags with --sphinx-option.
    """
    try:
        docs_module.linkcheck_command(
            clean=clean,
            jobs=jobs,
            sphinx_options=sphinx_options,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


@dev.group("release")
def release():
    """Release management helpers for PsyNet source checkouts."""


@release.command("announce")
@click.argument("version", metavar="VERSION")
@click.option(
    "--channel",
    default=slack_announcement_module.DEFAULT_CHANNEL,
    show_default=True,
    help="Slack channel name to post to.",
)
@click.option(
    "--summary-file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help=(
        "Path to the experimenter-facing summary in Slack mrkdwn "
        "(e.g. *Category* headers with bullet entries). Written by the "
        "release manager from the release's CHANGELOG section; see the "
        "release skill for curation guidance."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print the message instead of posting.",
)
@click.option(
    "--dry-run-json",
    is_flag=True,
    help=(
        "Print the raw Block Kit JSON payload (paste into "
        "https://app.slack.com/block-kit-builder to preview rendering)."
    ),
)
def release_announce(version, channel, summary_file, dry_run, dry_run_json):
    """Announce a PsyNet release on Slack.

    VERSION is e.g. 13.2.0 or 13.2.0rc1 (no leading 'v'). The release
    candidate vs. final message flavour is auto-detected from the version.

    Posting requires the [slack] extra and a SLACK_BOT_TOKEN environment
    variable with chat:write access to the channel. Always preview with
    --dry-run first.

    Example:

        psynet dev release announce 13.2.0 --summary-file highlights.md --dry-run
    """
    try:
        slack_announcement_module.announce_command(
            version,
            channel=channel,
            summary_file=summary_file,
            dry_run=dry_run,
            dry_run_json=dry_run_json,
        )
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc


@dev.group("changelog")
def changelog():
    """Manage changelog fragments from a PsyNet source checkout."""


@changelog.command("preview")
def changelog_preview():
    """Preview rendered changelog fragments without changing files."""
    assert_changelog_available()
    try:
        changelog_module.build_command()
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


@changelog.command("check-mr", hidden=True)
@click.argument("base", metavar="BASE")
@click.argument("head", metavar="HEAD")
def changelog_check_mr(base, head):
    """Validate changelog requirements for a merge-request diff."""
    assert_changelog_available()
    try:
        changelog_module.check_mr_command(base, head)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


@changelog.command("new")
@click.argument("category", type=click.Choice(CHANGELOG_CATEGORIES), metavar="CATEGORY")
@click.argument("description")
def changelog_new(category, description):
    """Create a new date-prefixed changelog fragment.

    CATEGORY must be one of: breaking, added, changed, deprecated, removed,
    fixed, updated, documentation.

    Example:

        psynet dev changelog new fixed "Fixed login timeout"
    """
    assert_changelog_available()
    try:
        changelog_module.new_command(category, description)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


@changelog.command("release")
@click.argument("version", metavar="VERSION")
@click.argument("date", metavar="DATE")
def changelog_release(version, date):
    """Create a release section from current fragments.

    VERSION is the PsyNet release version. DATE should use YYYY-MM-DD format.

    Example:

        psynet dev changelog release 13.2.0 2026-05-18
    """
    assert_changelog_available()
    try:
        changelog_module.release_command(version, date)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
