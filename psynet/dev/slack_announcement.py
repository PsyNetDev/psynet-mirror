"""Post PsyNet release announcements to Slack (`psynet dev release announce`).

This module handles the *mechanical* side of a release announcement: the
message envelope (title, release-candidate notice, upgrade instructions,
links), Slack Block Kit assembly (including splitting text across section
blocks to respect Slack's length limits), dry-run previews, and the actual
posting. The *editorial* side — the experimenter-facing summary of changes —
is deliberately not generated here: the release manager (usually assisted by
an AI agent following the repo's release skill) writes the summary from the
release's CHANGELOG section and passes it in via ``--summary-file``.
Earlier versions selected changelog entries with keyword patterns, which
proved too brittle in both directions (missed recruiter changes, included
maintainer tooling).

The sibling ``slack_announcement.md`` file is runtime configuration for the
envelope wording (stable release description, summary intro, upgrade
instructions), so editing the announcement style should not require code
changes.

Posting requires the ``[slack]`` extra and a ``SLACK_BOT_TOKEN`` environment
variable with ``chat:write`` access to the target channel. The message
flavour (release candidate vs. final) is auto-detected from the version
string.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DEFAULT_CHANNEL = "psynet-support"
ANNOUNCEMENT_GUIDANCE_PATH = Path(__file__).with_suffix(".md")

PRERELEASE_RE = re.compile(r"(rc|a|b)\d+$", re.IGNORECASE)


@dataclass(frozen=True)
class AnnouncementGuidance:
    stable_release_description: str
    experimenter_summary_intro: str
    stable_upgrade_instructions: str


def is_prerelease(version: str) -> bool:
    """Return True if *version* has a pre-release segment (rc/a/b)."""
    return bool(PRERELEASE_RE.search(version))


@lru_cache(maxsize=1)
def load_announcement_guidance() -> AnnouncementGuidance:
    """Read announcement envelope wording from ``slack_announcement.md``."""
    if not ANNOUNCEMENT_GUIDANCE_PATH.exists():
        raise ValueError(
            f"Missing announcement guidance: {ANNOUNCEMENT_GUIDANCE_PATH.resolve()}. "
            "Run from a PsyNet source checkout."
        )

    markdown = ANNOUNCEMENT_GUIDANCE_PATH.read_text(encoding="utf-8")
    stable_release_description = _markdown_section_text(
        markdown, "Stable Release Description"
    )
    experimenter_summary_intro = _markdown_section_text(
        markdown, "Experimenter Summary Intro"
    )
    stable_upgrade_instructions = _markdown_section_message(
        markdown, "Stable Upgrade Instructions"
    )

    if not stable_release_description:
        raise ValueError(
            "slack_announcement.md must define a stable release description."
        )
    if not experimenter_summary_intro:
        raise ValueError(
            "slack_announcement.md must define an experimenter summary intro."
        )
    if not stable_upgrade_instructions:
        raise ValueError(
            "slack_announcement.md must define stable upgrade instructions."
        )

    return AnnouncementGuidance(
        stable_release_description=stable_release_description,
        experimenter_summary_intro=experimenter_summary_intro,
        stable_upgrade_instructions=stable_upgrade_instructions,
    )


def _markdown_section_text(markdown: str, heading: str) -> str:
    section = _markdown_section(markdown, heading)
    lines = [
        line.strip()
        for line in section.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return " ".join(lines)


def _markdown_section_message(markdown: str, heading: str) -> str:
    section = _markdown_section(markdown, heading)
    lines = [
        line.rstrip()
        for line in section.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return "\n".join(lines)


def _markdown_section(markdown: str, heading: str) -> str:
    pattern = re.compile(rf"^## {re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(markdown)
    if not match:
        return ""

    next_heading = re.search(r"^##\s+", markdown[match.end() :], re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(markdown)
    return markdown[match.end() : end].strip()


def build_blocks(version: str, summary: str | None = None) -> tuple[list[dict], str]:
    """Return (blocks, fallback_text) for a Slack message.

    *summary* is the release manager's experimenter-facing highlights text in
    Slack mrkdwn (typically ``*Category*`` headers with ``•`` bullets). When
    omitted, the announcement carries only the envelope (title, notice,
    upgrade instructions, links).
    """
    guidance = load_announcement_guidance()
    pypi_url = f"https://pypi.org/project/psynet/{version}/"

    if is_prerelease(version):
        # Prereleases are tag-only: no GitLab release entry is created for
        # them, so link to the CHANGELOG at the tag instead.
        release_url = (
            f"https://gitlab.com/PsyNetDev/PsyNet/-/blob/v{version}/CHANGELOG.md"
        )
        final_version = PRERELEASE_RE.sub("", version)
        title = f":test_tube: PsyNet {version} — Release Candidate :test_tube:"
        subtitle = "A new release candidate is ready for testing!"
        docs_url = f"https://psynetdev.gitlab.io/PsyNet/rc/v{version}/"
        notice = (
            ":warning: *This is a release candidate.* "
            "It is not the latest release on PyPI; "
            f"opt in explicitly with `pip install psynet=={version}`. "
            "Please test against your studies and report any regressions "
            f"before the final `{final_version}` tag."
        )
        install = None
    else:
        release_url = f"https://gitlab.com/PsyNetDev/PsyNet/-/releases/v{version}"
        title = f":tada: PsyNet {version} is out! :rocket:"
        subtitle = guidance.stable_release_description
        docs_url = "https://psynetdev.gitlab.io/PsyNet/"
        versioned_docs_url = f"https://psynetdev.gitlab.io/PsyNet/v{version}/"
        notice = None
        # Not str.format, so that literal braces in the config file are safe.
        install = guidance.stable_upgrade_instructions.replace("{version}", version)

    buttons = [
        ("Release notes", release_url),
        ("Documentation", docs_url),
        ("PyPI", pypi_url),
    ]
    if not is_prerelease(version):
        buttons.insert(2, ("Versioned docs", versioned_docs_url))

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": title, "emoji": True},
        },
        _mrkdwn_block(f"_{subtitle}_"),
    ]

    if notice:
        blocks.append(_mrkdwn_block(notice))

    if summary:
        blocks.append({"type": "divider"})
        blocks.append(_mrkdwn_block(guidance.experimenter_summary_intro))
        # One section block per category: Slack adds vertical padding
        # between blocks, which keeps the categories visually separated.
        for section in _summary_sections(summary):
            blocks.extend(_mrkdwn_block(chunk) for chunk in _split_mrkdwn(section))

    blocks.append({"type": "divider"})
    if install:
        blocks.append(_mrkdwn_block(install))
    blocks.append(_actions_block(buttons))
    blocks.append(_context_block(_footer_text(version)))

    fallback = f"{title} — {release_url}"
    return blocks, fallback


# Emoji markers prepended to the summary's category headers so
# authors don't have to remember them.
CATEGORY_EMOJI = {
    "Breaking": ":rotating_light:",
    "Added": ":sparkles:",
    "Changed": ":arrows_counterclockwise:",
    "Deprecated": ":hourglass:",
    "Removed": ":wastebasket:",
    "Fixed": ":lady_beetle:",
}


def _summary_sections(summary: str) -> list[str]:
    """Split the summary into one text chunk per ``*Category*`` header.

    Known category headers get their emoji marker prefixed; any text before
    the first header becomes its own leading chunk.
    """
    sections: list[list[str]] = [[]]
    for line in summary.split("\n"):
        stripped = line.strip()
        emoji = CATEGORY_EMOJI.get(stripped.strip("*"))
        if emoji and stripped.startswith("*") and stripped.endswith("*"):
            sections.append([f"{emoji} {stripped}"])
        else:
            sections[-1].append(line)
    return [s for s in ("\n".join(sec).strip() for sec in sections) if s]


def _footer_text(version: str) -> str:
    from datetime import date

    released = date.today().strftime("%-d %b %Y")
    return (
        f"PsyNet {version}  •  released {released}  •  "
        "questions and regression reports in #psynet-support"
    )


def _actions_block(buttons: list[tuple[str, str]]) -> dict:
    """Render URL buttons. Clicking one opens the link directly; note that
    Slack may show an 'app cannot handle interactive responses' toast if the
    posting app has no interactivity endpoint configured."""
    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": label, "emoji": True},
                "url": url,
            }
            for label, url in buttons
        ],
    }


LOGO_URL = (
    "https://gitlab.com/PsyNetDev/PsyNet/-/raw/master/"
    "docs/_static/images/psynet-transparent.png"
)


def _context_block(text: str) -> dict:
    return {
        "type": "context",
        "elements": [
            {"type": "image", "image_url": LOGO_URL, "alt_text": "PsyNet logo"},
            {"type": "mrkdwn", "text": text},
        ],
    }


def _mrkdwn_block(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


# Slack rejects section blocks whose text exceeds 3000 characters
# ("invalid_blocks"); leave headroom for safety.
SECTION_TEXT_LIMIT = 2900


def _split_mrkdwn(text: str, limit: int = SECTION_TEXT_LIMIT) -> list[str]:
    """Split mrkdwn text into chunks below Slack's section length limit.

    Splits on line boundaries so bullet entries stay intact. A single line
    longer than the limit is emitted as its own (oversized) chunk rather
    than being broken mid-line; Slack's limit is far above any realistic
    changelog entry length.
    """
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.split("\n"):
        line_len = len(line) + 1
        if current and current_len + line_len > limit:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def render_dry_run(blocks: list[dict], channel: str) -> str:
    """Render the Block Kit payload as readable preview text."""
    lines = [f"# Would post to #{channel}:", ""]
    for block in blocks:
        if block["type"] == "divider":
            lines.append("---")
        elif block["type"] == "header":
            lines.append(f"# {block['text']['text']}")
            lines.append("")
        elif block["type"] == "actions":
            lines.append(
                "Buttons: "
                + " | ".join(
                    f"[{el['text']['text']}]({el['url']})" for el in block["elements"]
                )
            )
            lines.append("")
        elif block["type"] == "context":
            lines.append(
                "Footer: "
                + " ".join(
                    el["text"] if el["type"] == "mrkdwn" else f"[{el['alt_text']}]"
                    for el in block["elements"]
                )
            )
            lines.append("")
        else:
            lines.append(block["text"]["text"])
            lines.append("")
    return "\n".join(lines)


def announce_command(
    version: str,
    channel: str = DEFAULT_CHANNEL,
    summary_file: str | None = None,
    dry_run: bool = False,
    dry_run_json: bool = False,
) -> None:
    """Build the announcement for *version* and post or preview it.

    Raises ValueError for configuration problems and RuntimeError for
    Slack API failures.
    """
    summary = None
    if summary_file:
        summary_path = Path(summary_file)
        if not summary_path.exists():
            raise ValueError(f"Summary file not found: {summary_path.resolve()}")
        summary = summary_path.read_text(encoding="utf-8").strip()
        if not summary:
            raise ValueError(f"Summary file is empty: {summary_path.resolve()}")

    blocks, fallback = build_blocks(version, summary=summary)

    if dry_run_json:
        print(json.dumps({"blocks": blocks}, indent=2))
        return

    if dry_run:
        print(render_dry_run(blocks, channel))
        return

    try:
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError
    except ImportError as exc:
        raise ValueError(
            "slack_sdk is not installed. Install the [slack] extra:\n"
            "    uv pip install -e '.[slack]'"
        ) from exc

    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise ValueError("SLACK_BOT_TOKEN is not set.")

    client = WebClient(token=token)
    try:
        resp = client.chat_postMessage(
            channel=channel,
            text=fallback,
            blocks=blocks,
        )
    except SlackApiError as exc:
        raise RuntimeError(f"Slack error: {exc.response['error']}") from exc

    print(f"Posted to #{channel} (ts={resp['ts']})")
