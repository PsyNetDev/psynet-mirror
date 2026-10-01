---
name: public-tunnel
description: Expose a local HTTP service, usually a running PsyNet experiment, through a temporary public HTTPS tunnel, and hand the user public participant and dashboard links for live review in their browser. Use when the user needs to open a local experiment or service from another machine.
---

# Public tunnel

## Read first

Read these pages before acting. The "Documentation" section of the experiment's `AGENTS.md` explains how to find and search them.

- `code/project/running_and_debugging`: running an experiment locally

## Helper script

`scripts/public_tunnel.py` in this skill directory starts the tunnel. Its path
is `.cursor/skills/experiment/public-tunnel/` in a PsyNet source checkout and
`.cursor/skills/psynet/public-tunnel/` in an experiment.

The script uses `cloudflared` if installed, otherwise downloads a temporary
copy to `/tmp/cloudflared`, otherwise falls back to `localtunnel` or
`npx -y localtunnel`. The download fetches Linux builds only, so on macOS
install `cloudflared` first (for example with Homebrew). When the public URL
appears, the script prints `Public tunnel ready` followed by the URL. The URL
stops working when the script stops.

## Open a tunnel

1. Confirm that the local service is running:
   `curl -I --max-time 10 http://127.0.0.1:<port>/`
2. Start the script in its own long-running terminal, so it keeps running
   after your command returns:
   `uv run python <skill-dir>/scripts/public_tunnel.py --port <port>`
   On Cursor cloud agents, run it in a tmux session:
   `tmux -f /exec-daemon/tmux.portal.conf new-session -d -s <name>-public-tunnel -- uv run python <skill-dir>/scripts/public_tunnel.py --port <port>`
3. Wait for `Public tunnel ready` in its output.
4. Check the public URL: `curl -I --max-time 20 <public-url>`

## Preview a running experiment

1. Start the experiment with `psynet debug local` and wait until it serves
   port `5000`.
2. Open a tunnel to port `5000` as above.
3. Give the user two links built from the public origin:
   - Participant link: the local participant URL printed by
     `psynet debug local` (`/ad?generate_tokens=true&recruiter=...`), with
     `http://127.0.0.1:5000` replaced by the public origin.
   - Dashboard link: `https://<dashboard_user>:<dashboard_password>@<host>/dashboard/develop`,
     using the experiment's `dashboard_user` and `dashboard_password` config
     values. Share it only with the user, and warn that anyone with the link
     can open the dashboard while the tunnel runs.

Stop the tunnel when the review is finished.
