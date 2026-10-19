#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
from pathlib import Path

SEMVER_TAG = re.compile(r"^v\d+\.\d+\.\d+$")
PRERELEASE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(rc|a)(\d+)$")
PSYNET_VERSION_RE = re.compile(r'^psynet_version\s*=\s*"([^"]+)"', re.MULTILINE)


def parse_semver(tag):
    major, minor, patch = tag[1:].split(".")
    return int(major), int(minor), int(patch)


def parse_prerelease(tag):
    """Parse e.g. ``v13.2.0rc0`` into ``(major, minor, patch, kind, num)``.

    ``kind`` is ``"rc"`` or ``"a"``. Returns ``None`` for non-prerelease tags."""
    match = PRERELEASE_TAG.match(tag)
    if match is None:
        return None
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        match.group(4),
        int(match.group(5)),
    )


def list_local_tags():
    """Return all local git tags, sorted descending by ``version:refname``.

    Single source of truth for tag enumeration. Callers that only want stable
    semver tags should filter with ``SEMVER_TAG.match`` themselves.
    """
    output = subprocess.check_output(
        ["git", "tag", "--list", "--sort=-version:refname"], text=True
    )
    return [tag.strip() for tag in output.splitlines() if tag.strip()]


def _highest_stable_base(all_tags):
    """Return the highest stable ``(major, minor, patch)`` tuple, or ``(-1, -1, -1)``.

    ``all_tags`` is sorted descending by ``--sort=-version:refname``, but rely
    on ``parse_semver`` for an explicit ordering in case the sort heuristic
    ever disagrees with semver.
    """
    stable_tags = [tag for tag in all_tags if SEMVER_TAG.match(tag)]
    if not stable_tags:
        return (-1, -1, -1)
    return max(parse_semver(tag) for tag in stable_tags)


def _iter_active_prereleases(all_tags, highest_stable_base):
    """Yield ``(base, kind_rank, num, tag)`` for active prereleases.

    "Active" means the prerelease's base ``(major, minor, patch)`` is strictly
    greater than ``highest_stable_base`` (i.e. that base has not yet shipped
    stable). The tuple sorts ``rc`` above ``a`` for the same base, so sorting
    descending picks the most recent active prerelease.
    """
    kind_order = {"a": 0, "rc": 1}
    for tag in all_tags:
        parsed = parse_prerelease(tag)
        if parsed is None:
            continue
        major, minor, patch, kind, num = parsed
        base = (major, minor, patch)
        if base <= highest_stable_base:
            continue
        yield (base, kind_order[kind], num, tag)


def get_latest_active_prerelease_tag():
    """Return the most recent ``vX.Y.Z(rc|a)N`` tag whose base version is greater
    than the highest stable release tag, or ``None``.

    "Active" means the prerelease still has a future release we're working
    towards, i.e. its base ``X.Y.Z`` has not yet shipped as stable.
    """
    all_tags = list_local_tags()
    candidates = sorted(
        _iter_active_prereleases(all_tags, _highest_stable_base(all_tags)),
        reverse=True,
    )
    if not candidates:
        return None
    return candidates[0][3]


def parse_psynet_version(source_text):
    match = PSYNET_VERSION_RE.search(source_text)
    if match is None:
        raise RuntimeError("Could not parse psynet_version from psynet/version.py")
    return match.group(1)


def get_master_psynet_version(default_branch):
    source = subprocess.check_output(
        ["git", "show", f"origin/{default_branch}:psynet/version.py"], text=True
    )
    return parse_psynet_version(source)


def select_recent_patch_tags(tags, max_majors=2):
    parsed = [(tag, *parse_semver(tag)) for tag in tags]
    majors = sorted({major for _, major, _, _ in parsed}, reverse=True)[:max_majors]

    best_per_minor = {}
    for tag, major, minor, patch in parsed:
        if major not in majors:
            continue
        key = (major, minor)
        current = best_per_minor.get(key)
        if current is None or patch > current[2]:
            best_per_minor[key] = (tag, minor, patch)

    selected = [
        value[0]
        for _, value in sorted(
            best_per_minor.items(),
            key=lambda item: (item[0][0], item[0][1]),
            reverse=True,
        )
    ]
    return selected


def get_highest_stable_tag(tags):
    if not tags:
        return None
    parsed = sorted(
        ((tag, *parse_semver(tag)) for tag in tags),
        key=lambda item: (item[1], item[2], item[3]),
        reverse=True,
    )
    return parsed[0][0]


def _strip_v_prefix(value):
    """Return ``value`` without a leading ``v`` (e.g. ``v13.0.5`` -> ``13.0.5``).

    Used purely for the user-facing ``name`` field in the switcher; the
    ``version`` field that pydata-sphinx-theme matches against keeps the
    raw tag form so internal version matching is unaffected.
    """
    return value[1:] if value.startswith("v") else value


def is_alpha_version(version):
    """Return whether ``version`` looks like an alpha version (e.g. ``13.4.0a0``).

    The default branch briefly carries a stable version between a release
    branch being merged back and the post-release alpha bump landing; during
    that window there is no alpha version to advertise in the switcher.
    """
    return re.match(r"^\d+\.\d+\.\d+a\d+$", version) is not None


def format_alpha_name(alpha_version):
    """Return the user-facing switcher label for the alpha docs."""
    match = re.match(r"^(\d+\.\d+\.\d+)a\d+$", alpha_version)
    if match is None:
        raise ValueError(f"Expected an alpha version, got {alpha_version!r}.")
    return f"{match.group(1)} alpha"


def format_prerelease_name(tag):
    """Return the user-facing switcher label for a prerelease tag.

    Styled like the alpha entry (base version, space, suffix), e.g.
    ``v13.3.0rc0`` -> ``13.3.0 rc0``.
    """
    parsed = parse_prerelease(tag)
    if parsed is None:
        raise ValueError(f"Expected a prerelease tag, got {tag!r}.")
    major, minor, patch, kind, num = parsed
    return f"{major}.{minor}.{patch} {kind}{num}"


def build_entries(base_url, tags, alpha_version, latest_rc_tag=None):
    """Build the version_switcher.json entry list.

    ``tags`` is expected to be sorted descending by ``(major, minor)`` (as
    returned by :func:`select_recent_patch_tags`), so ``tags[0]`` is the
    highest stable release. That entry gets ``preferred: true``, which
    pydata-sphinx-theme treats as the canonical/recommended version: the
    switcher highlights it as the default stable, and pages on alpha, rc,
    or older stable subdirs render a "you're not on the latest stable,
    switch to vX.Y" banner pointing back at it.
    """
    base_url = base_url.rstrip("/")

    entries = []
    if alpha_version is not None:
        entries.append(
            {
                "name": format_alpha_name(alpha_version),
                "version": alpha_version,
                "url": f"{base_url}/alpha/",
            }
        )
    if latest_rc_tag:
        entries.append(
            {
                "name": format_prerelease_name(latest_rc_tag),
                "version": latest_rc_tag,
                "url": f"{base_url}/rc/{latest_rc_tag}/",
            }
        )
    for index, tag in enumerate(tags):
        entry = {
            "name": _strip_v_prefix(tag),
            "version": tag,
            "url": f"{base_url}/{tag}/",
        }
        if index == 0:
            entry["preferred"] = True
        entries.append(entry)
    return entries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="Output JSON path")
    parser.add_argument(
        "--base-url",
        default="https://psynetdev.gitlab.io/PsyNet",
        help="Base public URL for docs",
    )
    parser.add_argument(
        "--default-branch",
        default="master",
        help="Default branch name for reading alpha version",
    )
    parser.add_argument(
        "--print-highest-stable",
        action="store_true",
        help="Print the highest stable release tag and exit",
    )
    parser.add_argument(
        "--print-selected-stable-tags",
        action="store_true",
        help="Print selected stable tags (space-separated) and exit",
    )
    parser.add_argument(
        "--print-alpha-version",
        action="store_true",
        help="Print alpha version from default branch and exit",
    )
    parser.add_argument(
        "--print-latest-rc-tag",
        action="store_true",
        help=(
            "Print the latest active prerelease tag (rc/a whose base version "
            "exceeds the highest stable). Prints nothing if none. Used by CI "
            "to decide whether to build/publish RC docs."
        ),
    )
    args = parser.parse_args()

    stable_tags = [tag for tag in list_local_tags() if SEMVER_TAG.match(tag)]
    if args.print_highest_stable:
        highest_stable_tag = get_highest_stable_tag(stable_tags)
        if highest_stable_tag is None:
            raise RuntimeError("No stable release tags found.")
        print(highest_stable_tag)
        return

    if args.print_selected_stable_tags:
        print(" ".join(select_recent_patch_tags(stable_tags)))
        return

    if args.print_alpha_version:
        print(get_master_psynet_version(args.default_branch))
        return

    if args.print_latest_rc_tag:
        latest_rc = get_latest_active_prerelease_tag()
        if latest_rc:
            print(latest_rc)
        return

    if not args.output:
        raise ValueError("--output is required unless a --print-* option is used.")

    tags = select_recent_patch_tags(stable_tags)
    alpha_version = get_master_psynet_version(args.default_branch)
    if not is_alpha_version(alpha_version):
        # Post-release window: the release branch has been merged back but
        # the alpha bump has not landed yet, so skip the alpha entry.
        print(
            f"Default branch version {alpha_version!r} is not an alpha; "
            "omitting the alpha entry from the switcher."
        )
        alpha_version = None
    latest_rc_tag = get_latest_active_prerelease_tag()
    entries = build_entries(args.base_url, tags, alpha_version, latest_rc_tag)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(entries, indent=2) + "\n")


if __name__ == "__main__":
    main()
