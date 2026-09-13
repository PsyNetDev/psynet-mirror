---
name: realtime-synchronous-experiments
description: Design and implement PsyNet websocket experiments with live synchronous interactions between multiple participants in the same trial.
---

# Implement real-time synchronous PsyNet experiments

## Prerequisites

- Read `implement-experiment/SKILL.md` for the general PsyNet
  implementation workflow, setup reminders, and validation expectations.
- Inspect the closest PsyNet demos and framework APIs for groups, trials,
  nodes, events, websocket handling, and participant routing before designing
  custom frontend behavior.

## Design workflow

1. Model each live interaction as a server-owned session. Interactions within a
   trial belong to a session, and the server tracks each session state at every
   point in time.
2. Treat the server as the authority for shared state. It should accept actions,
   reject out-of-turn or duplicate actions, advance turns, and broadcast the
   resulting state snapshot.
3. Move experiment logic to the server side as much as is reasonable. This
   reduces out-of-sync client bugs and keeps page templates from accumulating
   complex JavaScript experiment logic.
4. Make page reloads resumable from the current server session state.
5. After every accepted update, send each participant only the current session
   state information they are allowed to see. The browser should render that
   filtered snapshot instead of reconstructing or tracking the session
   independently.
6. Keep browser state as a rendering cache only. Clients may show pending UI
   feedback, timers, animations, or sounds, but they should not decide what the
   session state is.
7. Integrate live sessions with PsyNet's node and trial system even when many
   interactions happen inside one trial. Load live-session input parameters from
   the trial's node definition.
8. Record important trial outputs, such as the accepted event sequence, in the
   trial answer so `summarize_trials` can build subsequent nodes from the
   accumulated data. Not every event needs to be in the trial answer, but all
   information needed for downstream node construction should be there.

## Data boundaries

- Keep websocket payloads scoped to what each participant is allowed to know. Do
  not send private information to the wrong client for local UI convenience, and
  do not rely on the browser to hide fields that should not have been sent.
- Separate three data concepts instead of mixing them in one table or payload:
  raw submitted events, reconstructed or checkpointed session state, and
  participant-specific outbound deliveries.
- Treat the raw event log as the private source of truth. It should contain the
  complete submitted action and any information needed to update the session
  state or analyze the data.
- Record outbound deliveries separately when it matters what each participant
  actually received. Delivery records should contain only the public payload sent
  to that participant, plus routing and status metadata.

## Validation

- Test multi-participant flows with separate browser profiles or contexts so
  participants have independent identities and routing.
- Test out-of-turn, duplicate, reload/resume, and participant-specific visibility
  cases, not only the happy path.
- Verify that trial answers contain enough accepted-session data for
  `summarize_trials` or later analysis to reconstruct the relevant outcome.
