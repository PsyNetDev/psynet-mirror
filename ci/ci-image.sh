#!/bin/sh
# Build the CI test images once per pipeline and share them via the GitLab
# container registry.
#
#   ci/ci-image.sh publish     build_image job: reuse or build + push both
#                              images, check translation extraction, and write
#                              ci-image.env for downstream jobs.
#   ci/ci-image.sh base        tag $DOCKER_LOCAL_TAG from the shared image.
#   ci/ci-image.sh playwright  tag $DOCKER_LOCAL_TAG-playwright likewise.
#
# Images are tagged by the hash of their inputs plus the UTC date, so
# pipelines with unchanged inputs reuse one image per day while dependency
# resolution still picks up new upstream releases daily. Jobs without a shared
# image for their Python version (release-only matrix jobs, or a failed pull)
# fall back to building locally. Runs under the docker image's busybox sh.
set -eu

_build_base() {
  docker build --build-arg PYTHON_VERSION="$PYTHON_VERSION" --tag "$DOCKER_LOCAL_TAG" .
}

_build_playwright() {
  docker build --build-arg BASE_IMAGE="$DOCKER_LOCAL_TAG" \
    --tag "$DOCKER_LOCAL_TAG-playwright" -f Dockerfile.playwright .
}

_login() {
  echo "$CI_REGISTRY_PASSWORD" | docker login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
}

_shared_image_usable() {
  [ -n "${SHARED_IMAGE:-}" ] && [ "${SHARED_IMAGE_PYTHON:-}" = "$PYTHON_VERSION" ]
}

_pull_as() {
  # Usage: _pull_as <remote image> <local tag>
  _login && docker pull "$1" && docker tag "$1" "$2"
}

publish() {
  key=$(cat Dockerfile Dockerfile.playwright pyproject.toml ci/dallinger-dev-requirements.txt \
    | sha256sum | cut -c1-16)
  base="$CI_REGISTRY_IMAGE/ci:py$PYTHON_VERSION-$(date -u +%Y%m%d)-$key"
  playwright="$base-playwright"
  _login
  # The Playwright image is pushed last, so its presence implies the base.
  if docker manifest inspect "$playwright" >/dev/null 2>&1; then
    echo "Reusing $base"
    docker pull "$base"
    docker tag "$base" "$DOCKER_LOCAL_TAG"
  else
    echo "Building $base"
    _build_base
    _build_playwright
    docker tag "$DOCKER_LOCAL_TAG" "$base"
    docker tag "$DOCKER_LOCAL_TAG-playwright" "$playwright"
    docker push "$base"
    docker push "$playwright"
  fi
  {
    echo "SHARED_IMAGE=$base"
    echo "SHARED_PLAYWRIGHT_IMAGE=$playwright"
    echo "SHARED_IMAGE_PYTHON=$PYTHON_VERSION"
  } > ci-image.env

  # Fail here rather than in every test shard. Release branches skip the
  # null translator, matching run-ci-tests.sh.
  case "${CI_COMMIT_REF_NAME:-}" in
    release-*) ;;
    *)
      docker run --rm -e PSYNET_WORKSPACE=/root/workspaces/PsyNet \
        -v "$PWD:/root/workspaces/PsyNet" -w /root/workspaces/PsyNet \
        "$DOCKER_LOCAL_TAG" \
        bash -c "bash install-ci-dependencies.sh && psynet translate --translator null"
      ;;
  esac
}

base() {
  if _shared_image_usable && _pull_as "$SHARED_IMAGE" "$DOCKER_LOCAL_TAG"; then
    return
  fi
  _build_base
}

playwright() {
  if _shared_image_usable \
    && _pull_as "$SHARED_PLAYWRIGHT_IMAGE" "$DOCKER_LOCAL_TAG-playwright"; then
    return
  fi
  _build_base
  _build_playwright
}

case "${1:-}" in
  publish | base | playwright) "$1" ;;
  *)
    echo "Usage: $0 publish|base|playwright" >&2
    exit 2
    ;;
esac
