#!/usr/bin/env bash
# Build the multi-version PsyNet docs site for GitLab Pages publishing.
#
# Modes (selected by CI environment):
# - Default-branch pipeline (no $CI_COMMIT_TAG): rebuild default-branch HEAD to
#   public/alpha/.
# - Prerelease tag pipeline ($CI_COMMIT_TAG matches vX.Y.Z(rc|a)N): adds a
#   single subdirectory at public/rc/<tag>/ for the tagged docs and removes
#   older prerelease docs for the same base version.
# - Stable tag pipeline ($CI_COMMIT_TAG matches vX.Y.Z): builds the tagged
#   release into public/<tag>/, updates public/ when the tag is the highest
#   stable release, and removes stale prerelease docs for that base.
#
# All modes end by syncing the latest version_switcher.json into every
# public/**/_static/version_switcher.json so cached subdirs whose HTML
# predates the absolute-URL switch still pick up new entries.
#
# Required environment:
#   CI_DEFAULT_BRANCH  (default: master)
# Optional environment:
#   CI_COMMIT_TAG      (when set to vX.Y.Z or vX.Y.Z(rc|a)N, switches to tag mode)

set -euo pipefail

ALPHA_REF="${CI_DEFAULT_BRANCH:-master}"
SWITCHER_JSON="docs/_static/version_switcher.json"
SCRIPT="docs/scripts/generate_version_switcher.py"
STABLE_TAG_RE='^v[0-9]+\.[0-9]+\.[0-9]+$'
PRERELEASE_TAG_RE='^v[0-9]+\.[0-9]+\.[0-9]+(rc|a)[0-9]+$'

pip install -e '.[dev]'
pip install furo pydata-sphinx-theme

git fetch --tags --force origin "$ALPHA_REF"
python "$SCRIPT" --default-branch "$ALPHA_REF" --output "$SWITCHER_JSON"

build_docs_from_ref() {
    local ref="$1" output_dir="$2" docs_display_version="$3"
    local worktree_dir
    worktree_dir=$(mktemp -d)
    git worktree add --detach "$worktree_dir" "$ref"
    mkdir -p "$worktree_dir/docs/_static"
    cp "$SWITCHER_JSON" "$worktree_dir/$SWITCHER_JSON"
    DOCS_VERSION="$docs_display_version" sphinx-build \
        -D version="$docs_display_version" \
        -D release="$docs_display_version" \
        -b html "$worktree_dir/docs" "$output_dir"
    git worktree remove --force "$worktree_dir"
}

build_alpha_docs() {
    local alpha_version
    alpha_version=$(python "$SCRIPT" --default-branch "$ALPHA_REF" --print-alpha-version)
    build_docs_from_ref "origin/$ALPHA_REF" "public/alpha" "$alpha_version"
}

build_stable_tag_docs() {
    local tag="$1"
    local highest_stable
    highest_stable=$(python "$SCRIPT" --print-highest-stable)

    rm -rf "public/$tag"
    build_docs_from_ref "$tag" "public/$tag" "$tag"

    if [ "$tag" = "$highest_stable" ]; then
        cp -a "public/$tag"/. public/
    fi
}

prerelease_base_tag() {
    local tag="$1"
    if [[ "$tag" =~ ^(v[0-9]+\.[0-9]+\.[0-9]+)(rc|a)[0-9]+$ ]]; then
        echo "${BASH_REMATCH[1]}"
    else
        echo "$tag"
    fi
}

remove_prerelease_docs_for_base() {
    local base_tag="$1"
    local keep_tag="${2:-}"
    local rc_dir

    if [ ! -d public/rc ]; then
        return
    fi

    for rc_dir in public/rc/"$base_tag"rc* public/rc/"$base_tag"a*; do
        if [ ! -d "$rc_dir" ]; then
            continue
        fi
        if [ -n "$keep_tag" ] && [ "$(basename "$rc_dir")" = "$keep_tag" ]; then
            continue
        fi
        rm -rf "$rc_dir"
    done
}

mkdir -p public

if [[ "${CI_COMMIT_TAG:-}" =~ $PRERELEASE_TAG_RE ]]; then
    # Prerelease tag pipeline: build the tagged RC docs.
    latest_rc=$(python "$SCRIPT" --print-latest-rc-tag)
    if [ "$CI_COMMIT_TAG" != "$latest_rc" ]; then
        echo "Skipping stale prerelease docs tag: $CI_COMMIT_TAG (latest active: ${latest_rc:-none})"
        exit 0
    fi
    remove_prerelease_docs_for_base "$(prerelease_base_tag "$CI_COMMIT_TAG")" "$CI_COMMIT_TAG"
    build_docs_from_ref \
        "$CI_COMMIT_TAG" \
        "public/rc/$CI_COMMIT_TAG" \
        "$CI_COMMIT_TAG"
elif [[ "${CI_COMMIT_TAG:-}" =~ $STABLE_TAG_RE ]]; then
    # Stable tag pipeline: build the tagged stable docs.
    build_stable_tag_docs "$CI_COMMIT_TAG"
    remove_prerelease_docs_for_base "$CI_COMMIT_TAG"
elif [ -n "${CI_COMMIT_TAG:-}" ]; then
    echo "Unsupported docs tag format: $CI_COMMIT_TAG" >&2
    exit 1
elif [ "${CI_COMMIT_BRANCH:-}" = "$ALPHA_REF" ]; then
    # Default-branch pipeline: rebuild alpha docs from the default branch only.
    build_alpha_docs
else
    echo "Unsupported docs branch: ${CI_COMMIT_BRANCH:-<unset>}" >&2
    exit 1
fi

# Sync version_switcher.json into every existing _static directory.
# Use `\;` (one cp per match), not `+`: cp's multi-target form treats the
# last argument as a destination directory and would fail otherwise.
mkdir -p public/_static
cp "$SWITCHER_JSON" public/_static/version_switcher.json
find public -path '*/_static/version_switcher.json' \
    -exec cp "$SWITCHER_JSON" {} \;
