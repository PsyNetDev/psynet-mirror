---
name: announce-release
description: Use psynet dev release announce to preview and post PsyNet release announcements to Slack.
---

# `psynet dev release announce`

Post a PsyNet release announcement to the `#psynet-support` Slack
channel. RC vs final flavour is auto-detected from the version string
(`(rc|a|b)\d+$` → release-candidate template).

The command composes only the message envelope (title, RC notice,
upgrade instructions, links); the experimenter-facing changes summary
is written by the release manager (usually with AI assistance)
and passed via `--summary-file` (see the
**Announce the release on Slack** step in the `release` skill for the
writing guidance). The envelope wording is configured in
`psynet/dev/slack_announcement.md`.

The output is Slack `mrkdwn` — single-asterisk bold, single-backtick
inline code, and `<URL|label>` for clickable links.

## One-time setup

1. **Create a Slack app** at <https://api.slack.com/apps> → *Create New
   App* → *From scratch*. Pick the workspace that owns
   `#psynet-support`. A descriptive name (e.g. `PsyNet Releases`)
   helps recipients recognise the bot.
2. **Add the bot scope.** In *OAuth & Permissions* → *Bot Token
   Scopes*, add `chat:write`. Optionally also add `chat:write.public`
   so the bot can post without being explicitly invited.
3. **Install to the workspace** from the top of *OAuth & Permissions*.
   Workspace admin approval may be required.
4. **Invite the bot to the channel** (skip if you added
   `chat:write.public`):

   ```text
   /invite @PsyNet Releases
   ```

5. **Copy the bot token** (`<slack-bot-token>`) from *OAuth & Permissions*. Treat
   it like a password — it grants posting rights to anyone who has it.

## Token storage

The command reads `SLACK_BOT_TOKEN` from the process environment. Export it
before running the command, or pass it inline for one-shot use:

```bash
export SLACK_BOT_TOKEN=<slack-bot-token>
psynet dev release announce 13.2.0 --dry-run
psynet dev release announce 13.2.0
```

```bash
SLACK_BOT_TOKEN=<slack-bot-token> psynet dev release announce 13.2.0
```

`.env` at the repo root is gitignored, so it's a safe place to store the
token:

```bash
# /home/<you>/projects/PsyNet/.env
SLACK_BOT_TOKEN=<slack-bot-token>
```

However, the command does not load `.env` automatically. If you store the
token there, load it into the shell before running the command, for example:

```bash
set -a
source .env
set +a
psynet dev release announce 13.2.0 --dry-run
```

## Usage

```bash
# Preview the message without posting (always do this first)
psynet dev release announce 13.2.0rc1 --summary-file highlights.md --dry-run
psynet dev release announce 13.2.0    --summary-file highlights.md --dry-run

# Post to the testing channel for rendering review
psynet dev release announce 13.2.0 --summary-file highlights.md --channel testing-bot-messages

# Actually post
psynet dev release announce 13.2.0rc1 --summary-file highlights.md
psynet dev release announce 13.2.0    --summary-file highlights.md
```

The command exits non-zero on Slack API errors or missing dependencies,
so it can be wired into release scripts safely.

## Dependencies

Posting requires `slack_sdk`, which is provided by PsyNet's
`[slack]` extra:

```bash
uv pip install -e '.[dev,slack]'
```

This is already part of the prerequisites listed in the `release` skill.

## Where this fits in the release flow

See the **Announce the release on Slack** shared step in the `release` skill; it applies to minor releases, patch releases, and release candidates alike.

The step is gated by an explicit human checkpoint: the message body
must be approved (via `--dry-run`) before any real post.
