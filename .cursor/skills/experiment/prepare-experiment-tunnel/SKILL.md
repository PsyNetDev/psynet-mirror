---
name: prepare-experiment-tunnel
description: Start a live PsyNet experiment preview and expose it through a temporary public tunnel for user review.
---

# Prepare experiment tunnel

## Workflow

1. Start the experiment locally (for example with `psynet debug local`) so it is
   listening on the expected port, usually `5000`.
2. Follow the `public-tunnel` skill for port `5000`.
3. Derive the public participant and dashboard/develop links:
   - the public participant link is the public tunnel origin with `/ad?generate_tokens=true&recruiter=hotair` appended
   - the public dashboard link is the public tunnel origin with `/dashboard/develop` appended and local debug credentials embedded, for example `https://<username>:<password>@<host>/dashboard/develop`
