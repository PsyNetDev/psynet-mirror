import pytest

from psynet.dev import slack_announcement

SAMPLE_SUMMARY = """*Added*
• A new demo experiment

*Fixed*
• A participant recruitment bug
"""


@pytest.mark.parametrize(
    "version,expected",
    [
        ("13.2.0", False),
        ("13.2.0rc0", True),
        ("13.2.0a1", True),
        ("13.2.0b2", True),
    ],
)
def test_is_prerelease(version, expected):
    assert slack_announcement.is_prerelease(version) is expected


def _section_texts(blocks):
    return [
        block["text"]["text"]
        for block in blocks
        if block["type"] in ("header", "section")
    ]


def _button_urls(blocks):
    return [
        element["url"]
        for block in blocks
        if block["type"] == "actions"
        for element in block["elements"]
    ]


def test_build_blocks_final_release():
    blocks, fallback = slack_announcement.build_blocks("13.2.0", summary=SAMPLE_SUMMARY)
    texts = _section_texts(blocks)
    joined = "\n".join(texts)

    assert "PsyNet 13.2.0 is out" in texts[0]
    assert "13.2.0" in fallback
    assert "A new demo experiment" in joined
    assert "pip install --upgrade psynet" in joined
    # The {version} placeholder from the guidance file must be substituted.
    assert "{version}" not in joined
    assert "release candidate" not in joined.lower()

    urls = _button_urls(blocks)
    assert "https://gitlab.com/PsyNetDev/PsyNet/-/releases/v13.2.0" in urls
    assert "https://pypi.org/project/psynet/13.2.0/" in urls
    assert "https://psynetdev.gitlab.io/PsyNet/v13.2.0/" in urls


def test_build_blocks_release_candidate():
    blocks, _ = slack_announcement.build_blocks("13.2.0rc1", summary=SAMPLE_SUMMARY)
    texts = _section_texts(blocks)
    joined = "\n".join(texts)

    assert "Release Candidate" in texts[0]
    assert "pip install psynet==13.2.0rc1" in joined

    urls = _button_urls(blocks)
    assert "https://psynetdev.gitlab.io/PsyNet/rc/v13.2.0rc1/" in urls
    # RCs are tag-only on GitLab; release notes link to the CHANGELOG at the tag.
    assert "https://gitlab.com/PsyNetDev/PsyNet/-/blob/v13.2.0rc1/CHANGELOG.md" in urls


def test_build_blocks_without_summary_omits_highlights():
    blocks, _ = slack_announcement.build_blocks("13.2.0")
    joined = "\n".join(_section_texts(blocks))
    assert "key changes relevant for experimenters" not in joined
    assert any(block["type"] == "header" for block in blocks)


def test_build_blocks_decorates_category_headers():
    blocks, _ = slack_announcement.build_blocks("13.2.0", summary=SAMPLE_SUMMARY)
    joined = "\n".join(_section_texts(blocks))
    assert ":sparkles: *Added*" in joined
    assert ":lady_beetle: *Fixed*" in joined


def test_build_blocks_puts_each_category_in_its_own_section():
    blocks, _ = slack_announcement.build_blocks("13.2.0", summary=SAMPLE_SUMMARY)
    category_sections = [
        text
        for text in _section_texts(blocks)
        if text.startswith((":sparkles:", ":lady_beetle:"))
    ]
    assert len(category_sections) == 2
    assert category_sections[0].startswith(":sparkles: *Added*")
    assert category_sections[1].startswith(":lady_beetle: *Fixed*")


def test_summary_sections_split_and_decorate_headers():
    summary = "*Added*\n• one\n*Fixed*\n• two"
    assert slack_announcement._summary_sections(summary) == [
        ":sparkles: *Added*\n• one",
        ":lady_beetle: *Fixed*\n• two",
    ]


def test_build_blocks_includes_context_footer():
    blocks, _ = slack_announcement.build_blocks("13.2.0", summary=SAMPLE_SUMMARY)
    context_blocks = [block for block in blocks if block["type"] == "context"]
    assert len(context_blocks) == 1
    elements = context_blocks[0]["elements"]
    assert elements[0]["type"] == "image"
    assert "PsyNet 13.2.0" in elements[1]["text"]


def test_announce_command_rejects_missing_summary_file(tmp_path):
    with pytest.raises(ValueError, match="Summary file not found"):
        slack_announcement.announce_command(
            "13.2.0",
            summary_file=str(tmp_path / "nope.md"),
            dry_run=True,
        )


def test_announce_command_rejects_empty_summary_file(tmp_path):
    empty = tmp_path / "empty.md"
    empty.write_text("  \n", encoding="utf-8")
    with pytest.raises(ValueError, match="Summary file is empty"):
        slack_announcement.announce_command(
            "13.2.0",
            summary_file=str(empty),
            dry_run=True,
        )


def test_announce_command_dry_run_uses_summary_file(tmp_path, capsys):
    summary = tmp_path / "highlights.md"
    summary.write_text(SAMPLE_SUMMARY, encoding="utf-8")
    slack_announcement.announce_command(
        "13.2.0",
        summary_file=str(summary),
        dry_run=True,
    )
    out = capsys.readouterr().out
    assert "A new demo experiment" in out
    assert "Would post to #psynet-support" in out


def test_split_mrkdwn_short_text_is_single_chunk():
    assert slack_announcement._split_mrkdwn("hello\nworld") == ["hello\nworld"]


def test_split_mrkdwn_splits_on_line_boundaries_below_limit():
    lines = [f"• entry {i} " + "x" * 200 for i in range(30)]
    chunks = slack_announcement._split_mrkdwn("\n".join(lines))
    assert len(chunks) > 1
    assert all(len(chunk) <= slack_announcement.SECTION_TEXT_LIMIT for chunk in chunks)
    assert "\n".join(chunks).split("\n") == lines
