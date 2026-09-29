---
name: realtime-synchronous-experiments
description: Design and implement PsyNet websocket experiments with live synchronous interactions between multiple participants in the same trial.
---

# Implement real-time synchronous PsyNet experiments

## Read first

Read these pages before acting. In a PsyNet source checkout read `docs/<page>.rst`; otherwise fetch `https://psynetdev.gitlab.io/PsyNet/<page>.html`.

- `code/multiplayer/realtime_interaction` — channels, `WebSocketElt`, the
  server-authority model, consistency, disconnects, and testing
- `design/groups` — group design concepts, including real-time interaction
- `code/multiplayer/synchronization` — groups, barriers, and timeouts
- `code/multiplayer/chatroom` — the built-in chatroom, a complete
  `WebSocketElt` implementation
- `code/pages/custom_routes` — authenticated HTTP routes for private data
- `code/pages/custom_front_ends` — page modules and cleanup

## Prerequisites

- Read `implement-experiment/SKILL.md` for the general PsyNet implementation
  workflow and validation expectations.
- Read `synchronous-experiments/SKILL.md` for grouping and barriers.
- Inspect `psynet/chatroom.py`, `psynet/static/scripts/chatroom-widget.js`,
  and `demos/features/websocket_chatroom/` before writing custom handlers or
  page JavaScript. If the interaction is only text chat, use `ChatRoom` and
  `EnableChatrooms` instead of writing a handler.

## Design the session

Write these decisions into the experiment plan before coding:

1. **Session boundaries.** Which trial or node owns each live session, how its
   input parameters come from the node definition, and which group members
   share it (usually `trial.sync_group`).
2. **State table.** Where the server stores session state, and how each
   request is checked (turn order, duplicate or stale action numbers,
   deadlines).
3. **Message protocol.** Each request `type` a browser sends, each state
   `type` the server publishes, and the fields in each. Browsers render only
   server state.
4. **Visibility.** For each field, who may see it. Anything private to one
   participant goes over an HTTP route that checks `unique_id`, never over the
   shared channel.
5. **Data records.** Keep three things separate: the private log of accepted
   actions (enough to replay and analyze the session), the current or
   checkpointed state, and, where it matters what each participant was
   shown, a record of each delivery. Store the outcome needed for analysis or
   `summarize_trials` on the trial.
6. **Recovery.** What the page does on reconnect or reload (request the full
   state in `onOpen`), and what happens when a member stops responding
   (barrier `max_wait_action`, turn deadlines).

## Validation

- Unit-test the handler by calling `handle_message` directly with accepted,
  out-of-turn, duplicate, and late requests.
- Test the browser flow with Playwright, one browser context per participant
  (see `playwright-testing/SKILL.md`), including a reload mid-session and a
  check of what each participant can see.
- Check that the trial data alone reconstructs each session's outcome.
