#!/bin/sh
# Provide the CI test image as $DOCKER_LOCAL_TAG, or as
# $DOCKER_LOCAL_TAG-playwright for `ci/ci-image.sh playwright`.
#
# Each job pulls a shared image from the GitLab container registry, falling
# back to a local build when it is missing. There is no separate build stage:
# a pull saves about half a minute per job over a build, which a serial stage
# would spend again before any test starts.
#
# Tags combine a hash of the files that define the image with the ISO week, so
# images are rebuilt weekly and dependency resolution still picks up new
# upstream releases. Only protected-branch pipelines push, which keeps merge
# requests from replacing the images that the default branch uses; merge
# requests with changed image inputs therefore build locally as before. Within
# a pipeline only the first parallel job pushes. Runs under busybox sh.
set -eu

kind="${1:-base}"
key=$(cat Dockerfile Dockerfile.playwright pyproject.toml ci/dallinger-dev-requirements.txt \
  | sha256sum | cut -c1-16)
remote="${CI_REGISTRY_IMAGE:-}/ci:py$PYTHON_VERSION-$(date -u +%G-w%V)-$key"
logged_in=false

_login() {
  [ -n "${CI_REGISTRY_IMAGE:-}" ] \
    && echo "$CI_REGISTRY_PASSWORD" \
      | docker login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY" >/dev/null \
    && logged_in=true
}

_pull_as() {
  # Usage: _pull_as <remote image> <local tag>
  $logged_in && docker pull --quiet "$1" && docker tag "$1" "$2"
}

_push_as() {
  # Usage: _push_as <local tag> <remote image>
  if $logged_in && [ "${CI_COMMIT_REF_PROTECTED:-}" = "true" ] \
    && [ "${CI_NODE_INDEX:-1}" = "1" ]; then
    docker tag "$1" "$2"
    docker push --quiet "$2" || echo "Warning: could not push $2" >&2
  fi
}

_base() {
  if _pull_as "$remote" "$DOCKER_LOCAL_TAG"; then
    echo "Using $remote"
    return
  fi
  echo "Building $DOCKER_LOCAL_TAG ($remote not available)"
  docker build --build-arg PYTHON_VERSION="$PYTHON_VERSION" --tag "$DOCKER_LOCAL_TAG" .
  _push_as "$DOCKER_LOCAL_TAG" "$remote"
}

_playwright() {
  if _pull_as "$remote-playwright" "$DOCKER_LOCAL_TAG-playwright"; then
    echo "Using $remote-playwright"
    return
  fi
  _base
  docker build --build-arg BASE_IMAGE="$DOCKER_LOCAL_TAG" \
    --tag "$DOCKER_LOCAL_TAG-playwright" -f Dockerfile.playwright .
  _push_as "$DOCKER_LOCAL_TAG-playwright" "$remote-playwright"
}

_login || echo "Registry login unavailable; building the CI image locally."
case "$kind" in
  base) _base ;;
  playwright) _playwright ;;
  *)
    echo "Usage: $0 [base|playwright]" >&2
    exit 2
    ;;
esac
