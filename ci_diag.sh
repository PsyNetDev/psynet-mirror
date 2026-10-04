set -x
if [ "$DIAG_ENV" = unpinned ]; then
  python -m venv /tmp/venv && . /tmp/venv/bin/activate
  python -m pip install -q "$PWD[experiment,demos]"
else
  uv pip install --no-cache --system --no-deps -e "$PWD"
fi
pip freeze > /tmp/freeze.txt; grep -i -E "^(dallinger|gunicorn|gevent|rq|redis|flask|werkzeug|sqlalchemy|psycopg|greenlet)" /tmp/freeze.txt
cd tests/experiments/async_processes
psynet performance-test local --n-bots 5 --duration-minutes 2.0 --json-output /tmp/out.json
status=$?
echo "EXIT STATUS $status"
for f in /tmp/psynet_server_*.log; do echo "===== $f (last 200 lines)"; tail -200 "$f"; done
grep -n -i -E "error|exception|killed|signal|worker .*(exit|timeout)|Traceback" /tmp/psynet_server_*.log | head -80
exit $status
