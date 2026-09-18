# Shared Canvas

This demo shows a real-time shared canvas experiment built with PsyNet
websocket service handlers.

Participants are grouped into live canvas sessions. They move colored avatars
with the arrow keys, see other participants' positions update over websockets,
and collect shared coins for a performance bonus.

The implementation is based on
<https://github.com/lucasgautheron/shared-canvas/tree/reconciliation>.

## Repository layout

- `experiment.py` defines the PsyNet experiment and websocket service.
- `templates/shared_canvas.html` renders the live browser canvas markup.
- `static/shared-canvas.css` and `static/shared-canvas.js` supply the
  in-place page styles and canvas behavior.
- `config.txt` contains Dallinger/PsyNet configuration.
- `requirements.txt` pins PsyNet from GitLab.
- `constraints.txt` is present for Dallinger dependency locking workflows.
- `Dockerfile` supports PsyNet/Dallinger SSH deployments.
- `test.py` runs the standard PsyNet experiment test through pytest.

## Local checks

From this demo directory:

```bash
pytest test.py
```

For full local PsyNet validation, ensure PostgreSQL, Redis, Docker, and the
Heroku CLI are available, then run:

```bash
psynet test local
```
