CI_NODE_TOTAL=${CI_NODE_TOTAL:=1}
CI_NODE_INDEX=${CI_NODE_INDEX:=1}
PYTHON_VERSION=${PYTHON_VERSION:=3.14}
TEST_SCOPE=${TEST_SCOPE:=full}
TEST_SLOTS=${TEST_SLOTS:=1}

TIMEOUT_SECONDS=300

if [[ "$TEST_SCOPE" != "full" && "$TEST_SCOPE" != "isolated" ]]; then
  echo "Unknown TEST_SCOPE: $TEST_SCOPE"
  exit 2
fi

echo "Running $TEST_SCOPE tests with Python $PYTHON_VERSION on node $CI_NODE_INDEX of $CI_NODE_TOTAL ($TEST_SLOTS slot(s))"

echo "Installing CI dependencies..."
bash install-ci-dependencies.sh || exit 1


if [[ "$CI_COMMIT_REF_NAME" =~ ^release- ]]; then
    echo "Release branch detected - all PsyNet translations must be present."
else
    echo "Not a release branch - missing PsyNet translations fall back to English during tests."
fi

# Each item runs in its own pytest process; see psynet/dev/ci_tests.py for how
# shards are balanced and how parallel slots are isolated from each other.
psynet dev ci run-tests \
  --scope "$TEST_SCOPE" \
  --node-total "$CI_NODE_TOTAL" \
  --node-index "$CI_NODE_INDEX" \
  --slots "$TEST_SLOTS" \
  --timeout "$TIMEOUT_SECONDS" \
  --junit-dir /public \
  --python-version "$PYTHON_VERSION" \
  --durations-output "/public/ci_durations_${PYTHON_VERSION}_${CI_NODE_INDEX}.json" \
  --log-dir /public/test-logs
