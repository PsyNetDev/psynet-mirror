CI_NODE_TOTAL=${CI_NODE_TOTAL:=1}
CI_NODE_INDEX=${CI_NODE_INDEX:=1}
PYTHON_VERSION=${PYTHON_VERSION:=3.13}
TEST_SCOPE=${TEST_SCOPE:=full}

TIMEOUT_SECONDS=300

if [[ "$TEST_SCOPE" != "full" && "$TEST_SCOPE" != "isolated" ]]; then
  echo "Unknown TEST_SCOPE: $TEST_SCOPE"
  exit 2
fi

echo "Running $TEST_SCOPE tests with Python $PYTHON_VERSION on node $CI_NODE_INDEX of $CI_NODE_TOTAL"

echo "Installing CI dependencies..."
bash install-ci-dependencies.sh || exit 1

echo "Checking if translation is needed..."
echo "CI_COMMIT_REF_NAME = $CI_COMMIT_REF_NAME"
if [[ ! "$CI_COMMIT_REF_NAME" =~ ^release- ]]; then
    echo "Not a release branch - will use the null translator to populate any missing translations."
    psynet translate --translator null || exit 1
else
    echo "Release branch detected - will require all translations to be present."
fi

# Fail the build if any of the tests fail
EXIT_CODE=0

if [[ "$TEST_SCOPE" == "full" ]]; then
  for file in $(psynet list-experiment-dirs --for-ci-tests --ci-node-total $CI_NODE_TOTAL --ci-node-index $CI_NODE_INDEX); do
    echo "Testing experiment $file"
    test_id=$(printf "%s" "$file" | tr "/." "__")
    # Materialize ignored boilerplate (including test.py) so pytest can collect.
    # The in_experiment_directory fixture also scaffolds, then restores the
    # authored-only tree on teardown; the explicit restore below is a backstop
    # when collection fails before fixtures run.
    if ! (cd "$file" && psynet scripts scaffold --skip-constraints); then
      EXIT_CODE=1
      continue
    fi
    # We use -Werror to ensure that we see all warnings as errors, but ignore yaspin color warnings
    # and the custom_network_filter deprecation until psynet-step migrates to
    # custom_chain_filter (https://github.com/pmcharrison/STEP/pull/5).
    # TODO: drop this ignore once that STEP change is released for PsyNet 14.
    # The suite name carries the Python version so the merged JUnit report can
    # distinguish otherwise identical tests run on different versions.
    pytest \
      --junitxml=/public/${PYTHON_VERSION}_${test_id}_junit.xml \
      -o junit_suite_name=py${PYTHON_VERSION} \
      $file/test.py \
      -Werror \
      -W "ignore:color, on_color and attrs are not supported when output stream is not a TTY:UserWarning:yaspin.core" \
      -W "ignore:custom_network_filter is deprecated:DeprecationWarning" \
      -q \
      -o log_cli=False \
      --chrome \
      --timeout=$TIMEOUT_SECONDS
    status=$?
    if ! (cd "$file" && psynet scripts prune --include-modified); then
      echo "Failed to restore authored-only layout for $file"
      EXIT_CODE=1
    fi
    if [ $status -ne 0 ]; then
      EXIT_CODE=1
    fi
  done
fi

for file in $(psynet list-isolated-tests --ci-node-total $CI_NODE_TOTAL --ci-node-index $CI_NODE_INDEX); do
  echo "Testing isolated test $file"
  test_id=$(printf "%s" "$file" | tr "/." "__")
  # We use -Werror to ensure that we see all warnings as errors, but ignore yaspin color warnings
  pytest \
    --junitxml=/public/${PYTHON_VERSION}_${test_id}_junit.xml \
    -o junit_suite_name=py${PYTHON_VERSION} \
    $file \
    -Werror \
    -W "ignore:color, on_color and attrs are not supported when output stream is not a TTY:UserWarning:yaspin.core" \
    -q \
    -o log_cli=False \
    --chrome \
    --timeout=$TIMEOUT_SECONDS
  if [ $? -ne 0 ]; then
    EXIT_CODE=1
  fi
done

# At the moment we don't have any other tests to run, but here's some template code to do so
# if we decide to add some.
#pytest \
#  --test-group-count=$CI_NODE_TOTAL \
#  --test-group=$CI_NODE_INDEX \
#  --test-group-random-seed=12345 \
#  --ignore=tests/local_only \
#  --ignore=tests/isolated \
#  --ignore=tests/test_run_all_demos.py \
#  --ignore=tests/test_run_isolated_tests.py \
#  --chrome \
#  tests \
#  || exit 1

exit $EXIT_CODE
