Live experiments
================

Many interactive experiments can be implemented with PsyNet's standard
synchronization tools. For example, a two-player rock-paper-scissors experiment
can show each participant a choice page, wait at a
:class:`~psynet.sync.GroupBarrier`, then score the round once both participants
have submitted a response.

This timeline-based approach is straightforward for experiments where
participants interact sequentially. However, it is not suitable for real-time
interactions that can happen continuously and in no particular order. Examples
include real-time movement on a shared canvas, real-time drawing, or real-time
text communication.

WebSockets
----------

PsyNet's native WebSocket API lets browser code send named messages to the
current experiment, and lets the experiment send messages back to one or more
participants.

In the browser:

.. code-block:: javascript

    psynet.websocket.send("choose", {
        action: "rock"
    });

    psynet.websocket.handle("roundResult", function(message) {
        status.textContent = message.text;
    });

In Python:

.. code-block:: python

    from typing import ClassVar

    from psynet.websocket import ClientWebSocketMessage, ServerWebSocketMessage


    class ChooseMessage(ClientWebSocketMessage):
        event_type: ClassVar[str] = "choose"
        action: str

        def handle(self, experiment, participant, receive_time):
            RoundResultMessage(text=self.action).send(participant)


    class RoundResultMessage(ServerWebSocketMessage):
        event_type: ClassVar[str] = "roundResult"
        text: str

PsyNet attaches the participant and current page identity automatically. Most
experiments do not need to work with these values directly. Their main effect is
that, after a refresh or page transition, an old browser tab can no longer send
valid messages for the participant's new page. The practical rule is simple:
register browser WebSocket handlers from a page module's ``activate()``
function, so PsyNet can recreate them whenever it renders a new live page.

Live sessions
-------------

Why sessions are needed
~~~~~~~~~~~~~~~~~~~~~~~

A WebSocket message is an event: a participant clicked a button, moved an
avatar, or collected a coin. Many live experiments also need durable shared
state: the current score, the players' positions, the remaining coins, or the
round that is currently active. If that state only lived in browser memory, it
would be lost when a participant refreshed the page, and different participants
could drift out of sync.

PsyNet provides :class:`~psynet.session.LiveSession` for this purpose. A live
session is a persisted SQL row owned by a synchronized group. It stores the
server's authoritative version of the live interaction.

Declare a session by subclassing ``LiveSession`` and adding ordinary SQL columns
for the state that should survive refreshes and reconnects:

.. code-block:: python

    from sqlalchemy import Column, Integer

    from psynet.session import LiveSession


    class ScoreSession(LiveSession):
        score = Column(Integer, default=0)

        def initialize(self, participant_ids, group):
            self.score = 0

The ``initialize(...)`` method runs when PsyNet creates the row. It receives the
group's participant IDs and the synchronized group, so it can derive the initial
state from the group, trial, node, or network.

Creating a session in the timeline
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Live sessions are normally used with synchronized participants. First group the
participants, then add a :class:`~psynet.session.LiveSessionInitializer` before
the live page. The initializer is a barrier: once the group is ready, the group
leader creates one persisted session row for everyone.

.. code-block:: python

    GROUP_TYPE = "live_score"

    SimpleGrouper(
        group_type=GROUP_TYPE,
        initial_group_size=2,
    )

Inside a synchronized trial, initialize the session before rendering the live
control:

.. code-block:: python

    def show_trial(self, experiment, participant):
        return join(
            LiveSessionInitializer(
                id_="score_session",
                group_type=GROUP_TYPE,
                session_class=ScoreSession,
            ),
            ModularPage(
                "score_page",
                "Click to score.",
                ScoreControl(participant=participant),
                time_estimate=20,
            ),
        )

``LiveSessionInitializer`` uses a short
``WaitPage(wait_time=0.5, save_answer=False)`` by default while the group waits
for the barrier to release. You can pass a custom ``waiting_logic`` when an
experiment needs a different waiting page.

Connecting a control to the session
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A :class:`~psynet.session.LiveSessionControl` connects the rendered page to the
session row that was just initialized. It resolves the session ID, initializes
``psynet.session`` in the browser, and exposes
``psynet.session.session_id`` and ``psynet.session.participant_id``.

.. code-block:: python

    class ScoreControl(LiveSessionControl):
        external_template = "score.html"
        macro = "score_control"

        def __init__(self, participant):
            super().__init__(
                participant=participant,
                session_class=ScoreSession,
                group_type=GROUP_TYPE,
                session_initializer_id="score_session",
                show_next_button=False,
            )

        def get_js_page_modules(self):
            return ["/static/score.js"]

Keep the Jinja macro focused on markup. Put live-session setup in a page
module's ``activate()`` function. The ``liveSessionInit`` event means the
control has initialized ``psynet.session``. Page modules run before that event,
so wait for it before calling ``psynet.session``.

.. code-block:: javascript

    export async function activate({root, psynet}) {
        const scoreEl = root.querySelector("#score");
        const scoreButton = root.querySelector("#score-button");

        psynet.trial.onEvent("liveSessionInit", function () {
            psynet.session.onFreshState(function(snapshot) {
                scoreEl.textContent = snapshot.state.score;
            });

            psynet.session.onStarted(function() {
                scoreButton.disabled = false;
            });

            psynet.session.ready();
        });
    }

``psynet.session.onFreshState(...)`` handles the initial snapshot and later
refresh/reconnect snapshots. ``psynet.session.ready()`` tells the server that
this participant has loaded the live page. Once all session participants are
ready, PsyNet sends ``sessionStart`` and runs
``psynet.session.onStarted(...)`` handlers.

After ``LiveSessionControl`` has initialized ``psynet.session``, browser calls
to ``psynet.websocket.send(...)`` automatically include the current
``session_id``. Browser code can also call ``psynet.session.pullState()`` to ask
for a fresh snapshot, or ``psynet.session.pullState(["score"])`` to request
selected state fields.

Using sessions in WebSocket handlers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When a typed WebSocket message needs the current live-session row, decorate its
``handle`` method with ``@session()``. The decorator uses the message's
``session_id`` and the current participant to find the right session, then
injects it as a ``session`` argument.

Use ``@session()`` for handlers that only read from the row:

.. code-block:: python

    class ScoreRequest(ClientWebSocketMessage):
        event_type: ClassVar[str] = "scoreRequest"

        @session()
        def handle(self, experiment, participant, session: ScoreSession, receive_time):
            ScoreUpdate(score=session.score).send(participant)

Use ``@session(mutate=True)`` for handlers that mutate session state. PsyNet
locks the row, commits on success, and rolls back if the handler raises an
exception.

.. code-block:: python

    class ScoreClick(ClientWebSocketMessage):
        event_type: ClassVar[str] = "scoreClick"

        @session(mutate=True)
        def handle(self, experiment, participant, session: ScoreSession, receive_time):
            session.score += 1
            ScoreUpdate(score=session.score).send(session.participants)


    class ScoreUpdate(ServerWebSocketMessage):
        event_type: ClassVar[str] = "scoreUpdate"
        score: int

If you also need an audit trail of the session state after each successful
mutation, use ``@session(mutate=True, logging=True)``. PsyNet queues a full
authoritative state record after the mutation commits, then saves it
asynchronously in a structured log table for that live-session class.

Snapshots and private state
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Browser-facing snapshots are generated automatically from a session subclass's
SQL columns. The base ``LiveSession`` class can also be used directly with
PsyNet's generic ``var`` store, but explicit subclass columns are preferred for
clarity and performance.

Override ``snapshot_state(fields=None, participant=None)`` when you need to hide
columns, rename fields, or include participant-specific recovery state for the
participant requesting a fresh snapshot:

.. code-block:: python

    from sqlalchemy import Column, Integer

    from psynet.field import PythonDict


    class DemoSession(LiveSession):
        public_score = Column(Integer)
        participant_notes = Column(PythonDict, default=lambda: {})

        def snapshot_state(self, fields=None, participant=None):
            state = super().snapshot_state(fields=None, participant=participant)
            notes = state.pop("participant_notes", {}) or {}
            if participant is not None:
                state["my_note"] = notes.get(str(participant.id))
            if fields is not None:
                state = {field: state[field] for field in fields if field in state}
            return state

For normal gameplay progress and frequent live updates, use custom WebSocket
messages rather than repeatedly pulling full session snapshots. In the browser,
send participant actions with ``psynet.websocket.send(...)``. On the server,
reply or broadcast with typed ``ServerWebSocketMessage`` objects, for example
``ScoreUpdate(...).send(participant)``. Use snapshots for initial rendering,
refresh/reconnect recovery, and occasional explicit state pulls.

Message logs
~~~~~~~~~~~~

Accepted WebSocket messages are saved by default, inbound and outbound. Typed
messages are saved in tables derived from their Pydantic message classes, with
columns for the model fields. If a live update is sent at a high rate, set
``save=False`` on the corresponding message class to skip the default WebSocket
message log.

Putting it together
-------------------

The following sketch puts the pieces together in a live rock-paper-scissors
round. It is included after the smaller examples above so you can see how the
session row, initializer, control, browser setup, and session-aware WebSocket
handler fit together in one timeline.

Server-side experiment
~~~~~~~~~~~~~~~~~~~~~~

The Python code defines the persistent session row, typed WebSocket messages,
and timeline. The server owns the authoritative game state and sends custom
events for gameplay progress.

.. code-block:: python

    from typing import ClassVar

    from sqlalchemy import Boolean, Column

    import psynet.experiment
    from psynet.field import PythonDict
    from psynet.modular_page import ModularPage
    from psynet.page import InfoPage
    from psynet.session import (
        LiveSession,
        LiveSessionControl,
        LiveSessionInitializer,
        session,
    )
    from psynet.sync import SimpleGrouper
    from psynet.timeline import Timeline, join
    from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker
    from psynet.websocket import ClientWebSocketMessage, ServerWebSocketMessage


    GROUP_TYPE = "live_rps"
    CHOICES = ["rock", "paper", "scissors"]


    class ChooseMessage(ClientWebSocketMessage):
        event_type: ClassVar[str] = "choose"
        action: str

        @session(mutate=True)
        def handle(
            self,
            experiment,
            participant,
            session: "RockPaperScissorsSession",
            receive_time,
        ):
            result = session.record_choice(participant, self.action)
            if result is None:
                return

            finished, choices = result
            if finished:
                for recipient in session.participants:
                    GameFinishedMessage(choice=choices[str(recipient.id)]).send(
                        recipient
                    )


    class GameFinishedMessage(ServerWebSocketMessage):
        event_type: ClassVar[str] = "gameFinished"
        choice: str


    class RockPaperScissorsSession(LiveSession):
        choices = Column(PythonDict, default=lambda: {})
        finished = Column(Boolean, default=False)

        def initialize(self, participant_ids, group):
            self.choices = {}
            self.finished = False

        def record_choice(self, participant, action):
            if not self.has_participant(participant):
                return None

            choices = dict(self.choices or {})
            choices[str(participant.id)] = action
            self.choices = choices
            self.finished = len(choices) == len(self.participant_ids or [])
            return self.finished, choices


    class RockPaperScissorsControl(LiveSessionControl):
        external_template = "rps.html"
        macro = "rps_control"

        def __init__(self, participant):
            self.choices = CHOICES
            super().__init__(
                participant=participant,
                session_class=RockPaperScissorsSession,
                group_type=GROUP_TYPE,
                session_initializer_id="rps_session",
            )

        def get_js_page_modules(self):
            return ["/static/rps.js"]


    class RockPaperScissorsTrial(StaticTrial):
        time_estimate = 20

        def show_trial(self, experiment, participant):
            return join(
                LiveSessionInitializer(
                    id_="rps_session",
                    group_type=GROUP_TYPE,
                    session_class=RockPaperScissorsSession,
                ),
                ModularPage(
                    "live_rps",
                    "Choose rock, paper, or scissors.",
                    RockPaperScissorsControl(participant=participant),
                    save_answer="choice",
                    time_estimate=20,
                ),
            )


    class Exp(psynet.experiment.Experiment):
        timeline = Timeline(
            SimpleGrouper(
                group_type=GROUP_TYPE,
                initial_group_size=2,
            ),
            StaticTrialMaker(
                id_="live_rps",
                trial_class=RockPaperScissorsTrial,
                nodes=[StaticNode(definition={})],
                expected_trials_per_participant=1,
                max_trials_per_participant=1,
                sync_group_type=GROUP_TYPE,
            ),
            InfoPage("Finished.", time_estimate=5),
        )

Client-side markup and page module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Keep ``templates/rps.html`` focused on markup. The page module waits for
``liveSessionInit``, recovers from fresh state snapshots after load/reconnect,
sends participant choices, and handles the server's custom ``gameFinished``
event.

In ``templates/rps.html``:

.. code-block:: html

    {% macro rps_control(config) %}
    <div id="status">Waiting for your partner...</div>

    {% for choice in config.choices %}
        <button type="button" class="choice" data-choice="{{ choice }}" disabled>
            {{ choice }}
        </button>
    {% endfor %}
    {% endmacro %}

In ``static/rps.js``:

.. code-block:: javascript

    export async function activate({root, psynet}) {
        psynet.trial.onEvent("liveSessionInit", function () {
            const participantId = String(psynet.session.participant_id);
            const statusEl = root.querySelector("#status");
            const buttons = Array.from(root.querySelectorAll(".choice"));
            let submitted = false;

            function setButtonsEnabled(enabled) {
                buttons.forEach(function(button) { button.disabled = !enabled; });
            }

            function promptForChoice() {
                statusEl.textContent = "Choose your action.";
                setButtonsEnabled(true);
            }

            psynet.session.onFreshState(function(freshState) {
                // Fresh state is for initial load/reconnect recovery. Normal
                // gameplay progress uses custom events below.
                const state = freshState.state || {};
                const choices = state.choices || {};
                const hasChosen = Object.prototype.hasOwnProperty.call(
                    choices,
                    participantId
                );
                if (state.finished && hasChosen) {
                    psynet.nextPage(choices[participantId]);
                    return;
                }

                submitted = hasChosen;
                if (hasChosen) {
                    statusEl.textContent = "Waiting for your partner...";
                    setButtonsEnabled(false);
                } else if (freshState.started) {
                    promptForChoice();
                }
            });

            psynet.session.onStarted(function() {
                if (!submitted) promptForChoice();
            });

            psynet.websocket.handle("gameFinished", function(message) {
                psynet.nextPage(message.choice);
            });

            psynet.session.ready();

            buttons.forEach(function(button) {
                button.addEventListener("click", function () {
                    if (submitted) return;
                    submitted = true;
                    statusEl.textContent = "Waiting for your partner...";
                    setButtonsEnabled(false);
                    psynet.websocket.send("choose", {
                        action: button.getAttribute("data-choice")
                    });
                });
            });
        });
    }

The complete rock-paper-scissors WebSocket demo in
``demos/experiments/rock_paper_scissors_websocket`` expands this pattern with
multiple rounds, hidden move rows, scoring, and participant-specific reveal
messages. The shared-canvas demo in ``demos/experiments/shared_canvas`` shows a
continuous movement example with low-latency position updates and server-owned
coin collection state.
