set -x
if [ "$DIAG_ENV" = unpinned ]; then
  python -m venv /tmp/venv && . /tmp/venv/bin/activate
  python -m pip install -q "$PWD[experiment,demos]"
else
  uv pip install --no-cache --system --no-deps -e "$PWD"
fi
pip freeze > /tmp/freeze.txt; grep -i -E "^(dallinger|gunicorn|gevent|rq|redis|flask|werkzeug|sqlalchemy|psycopg|greenlet)" /tmp/freeze.txt
if [ "$DIAG_ENV" = asv ]; then
  git config --global --add safe.directory '*'
  uv pip install --no-cache --system asv virtualenv
  asv machine --yes --machine gitlab-ci
  asv run --show-stderr --bench 'slow.experiment_performance.AsyncProcesses' HEAD^! 2>&1 | tee /tmp/asv.log
  grep -q -E 'failed|n/a' /tmp/asv.log && { echo ASV BENCHMARK FAILED; exit 1; }
  echo ASV BENCHMARK OK; exit 0
fi
cd tests/experiments/async_processes
psynet performance-test local --n-bots 5 --duration-minutes 2.0 --json-output /tmp/out.json
status=$?
echo "EXIT STATUS $status"
for f in /tmp/psynet_server_*.log; do echo "===== $f (last 200 lines)"; tail -200 "$f"; done
grep -n -i -E "error|exception|killed|signal|worker .*(exit|timeout)|Traceback" /tmp/psynet_server_*.log | head -80
exit $status
