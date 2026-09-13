# Note -- AWS tests will fail without setting AWS keys

set -euo pipefail

AWS_ACCESS_KEY_ID=TODO
AWS_DEFAULT_REGION=TODO
AWS_SECRET_ACCESS_KEY=TODO

POSTGRES_HOST_AUTH_METHOD=trust
HEADLESS=TRUE
DOCKER_IMAGE=psynet-ci-local
DOCKER_HOST=tcp://docker:2375
DOCKER_DRIVER=overlay2
DOCKER_TLS_CERTDIR=""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=ci/ensure-dallinger-docker-network.sh
. "$SCRIPT_DIR/ci/ensure-dallinger-docker-network.sh"

# Builds the Docker image
docker build --tag "$DOCKER_IMAGE" .

# Runs the automated tests
docker run \
  -e HEADLESS=TRUE \
  -e AWS_ACCESS_KEY_ID -e AWS_DEFAULT_REGION -e AWS_SECRET_ACCESS_KEY \
  -e REDIS_URL=redis://dallinger_redis:6379 \
  -e DATABASE_URL=postgresql://dallinger:dallinger@dallinger_postgres/dallinger \
  --network dallinger \
  $DOCKER_IMAGE bash -c \
  "pytest --ignore=tests/local_only --ignore=tests/isolated --chrome --exitfirst tests"

# --existfirst flag stops tests on first error

# Run the following code to enter a terminal in the Docker image. This can be very helpful for debugging failures.
#docker run \
#  -e HEADLESS=TRUE \
#  -e AWS_ACCESS_KEY_ID -e AWS_DEFAULT_REGION -e AWS_SECRET_ACCESS_KEY \
#  -e REDIS_URL=redis://dallinger_redis:6379 \
#  -e DATABASE_URL=postgresql://dallinger:dallinger@dallinger_postgres/dallinger \
#  --network dallinger \
#  --rm -it \
#  psynet-ci-local bash
