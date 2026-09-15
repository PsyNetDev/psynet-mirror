---
name: public-tunnel
description: Start an ephemeral public HTTPS tunnel to a local HTTP service for live review from a browser.
---

# Public tunnel

## Helper script

Run `scripts/public_tunnel.py` from this skill directory. Paths:

- PsyNet source: `.cursor/skills/experiment/public-tunnel`
- Experiment bundle: `.cursor/skills/psynet/public-tunnel`

The helper:

- chooses `cloudflared`, `localtunnel`, or `npx -y localtunnel`;
- downloads temporary `/tmp/cloudflared` if needed;
- starts the tunnel to `http://127.0.0.1:<port>`;
- prints `Public tunnel ready` when it detects the public URL;
- provides URL helpers for caller workflows.

## Workflow

1. Confirm the local service is already running:
   `curl -I --max-time 10 http://127.0.0.1:<port>/`
2. Start `scripts/public_tunnel.py` in its own tmux session:
   `tmux -f /exec-daemon/tmux.portal.conf new-session -d -s <name>-public-tunnel -- uv run python .cursor/skills/experiment/public-tunnel/scripts/public_tunnel.py --port <port>`
   (Use the experiment-bundle path when the skill was installed with `psynet scripts update`.)
3. Watch that session for `Public tunnel ready`.
4. Verify the public URL:
   `curl -I --max-time 20 <public-url>`
