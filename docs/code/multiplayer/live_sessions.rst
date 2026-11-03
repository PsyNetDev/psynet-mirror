.. _live_sessions:

=============
Live sessions
=============

A live session is a game that a group of participants play together in real
time, such as a negotiation, a coordination game or a game on a shared board.
The server keeps one state for the whole group, applies each player's
messages to it in order, and sends each player's page its own view of the
game. Each session, with its messages, is saved with the experiment's data.

A live session has three pieces:

1. The game, a subclass of :class:`~psynet.live_session.LiveSession`, with a
   :class:`~psynet.live_session.LiveMessage` subclass for each kind of
   message a page can send.
2. A :class:`~psynet.live_session.LiveSessionInitializer` in the timeline,
   which starts a session for each group that reaches it.
3. The game page, a :class:`~psynet.modular_page.ModularPage` with a
   :class:`~psynet.live_session.LiveSessionControl`, and a JavaScript file
   that plays the game through ``psynet.liveSession``.

The game
--------

A game of rock, paper, scissors:

.. code-block:: python

    from typing import Literal

    from psynet.live_session import LiveMessage, LiveSession


    class Choose(LiveMessage):
        type = "choose"
        action: Literal["rock", "paper", "scissors"]

        def apply(self, game, state, player_id, now):
            state["choices"][player_id] = self.action


    class RockPaperScissors(LiveSession):
        channel = "rock_paper_scissors"
        messages = [Choose]

        def initial_state(self, players):
            return {"choices": {player: None for player in players}}

        def view(self, state, player_id):
            return {"chosen": state["choices"][player_id] is not None}

        def is_over(self, state):
            return None not in state["choices"].values()

Define each game, or import it, before the experiment class. PsyNet then adds
it to the experiment's ``realtime_games``, so you don't list it there.
:class:`~psynet.live_session.LiveSession` and
:class:`~psynet.live_session.LiveMessage` describe the rest: how messages are
checked, what the state can hold, and the game's time limit, clock and
outcome, which come from Dallinger's
:class:`~dallinger.realtime.RealtimeGame`.

Starting sessions and the game page
-----------------------------------

Put the initializer after the :class:`~psynet.sync.Grouper` that forms the
groups. When all of a group's members reach it, it starts a session, and the
group moves on together. The game page comes after it, and its
:class:`~psynet.live_session.LiveSessionControl` names the initializer:

.. code-block:: python

    timeline = Timeline(
        SimpleGrouper(group_type="pair", initial_group_size=2),
        LiveSessionInitializer(
            id_="rock_paper_scissors",
            group_type="pair",
            game_type=RockPaperScissors,
        ),
        ModularPage(
            "rock_paper_scissors",
            Prompt(
                tags.div(
                    tags.p(id="status"),
                    tags.button("Rock", type="button", id="rock"),
                    tags.button("Paper", type="button", id="paper"),
                    tags.button("Scissors", type="button", id="scissors"),
                )
            ),
            LiveSessionControl("rock_paper_scissors"),
            js_page_modules=["/static/rock_paper_scissors.js"],
            time_estimate=30,
        ),
        ...
    )

The page's JavaScript goes in a file in the experiment's ``static`` folder,
listed in the page's ``js_page_modules``. It exports an ``activate``
function, which PsyNet runs each time the page opens
(:doc:`/code/pages/custom_front_ends` explains page modules).
``static/rock_paper_scissors.js``:

.. code-block:: javascript

    export function activate({root, psynet}) {
        let status = root.querySelector("#status");
        if (!psynet.liveSession.hasSession) {
            status.textContent = "Your group couldn't start the game.";
            return;
        }
        psynet.liveSession.onView((view) => {
            status.textContent =
                view.chosen ? "Waiting for your partner" : "Your turn";
        });
        psynet.liveSession.onRejected((number, reason) => {
            status.textContent = reason;
        });
        psynet.liveSession.onEnded(() => {
            status.textContent = "The game is over. Click Next.";
        });
        for (let action of ["rock", "paper", "scissors"]) {
            root.querySelector("#" + action).addEventListener("click", () => {
                psynet.liveSession.send("choose", {action: action});
            });
        }
    }

:class:`~psynet.live_session.LiveSessionControl` lists everything
``psynet.liveSession`` offers. The page leaves the session when the
participant moves on, so ``activate`` doesn't need to return a cleanup
function for it.

Cases a game page should allow for
----------------------------------

No session
    A participant can reach the page without one, for example when the
    initializer's ``max_wait_action="kick"`` removed them from a group that
    took too long to arrive. ``psynet.liveSession.hasSession`` is then
    ``false``, and the other methods throw an error. Check it first, as
    above, and tell the participant.

Joining in time
    The page joins the session when its JavaScript first uses
    ``psynet.liveSession``, so call ``onView`` in ``activate``, and the page
    joins as it opens. The session's clock starts when the group leaves the
    initializer, and if none of the group has opened the page by the game's
    ``join_timeout``, 60 seconds unless the game sets it, the session ends.
    Pages between the initializer and the game page count against it, so
    raise ``join_timeout`` to allow for them.

Rejected messages
    A message is rejected when one of its fields is missing or of the wrong
    type, which is usually a mistake in the page's JavaScript, or when the
    game's ``apply`` raises ``Reject``, such as for a move out of turn. Show
    the participant the reason, or match the number ``send`` returned.

The end
    ``onEnded`` says the game is over. The game ignores messages sent after
    it, though ``send`` still returns a number. The page doesn't move on by
    itself. To keep the participant on the page until the game is over, pass
    ``show_next_button=False`` to the control and call ``psynet.nextPage()``
    in ``onResultSaved``. The page then needs other ways on: in
    ``onRefused``, since a refused page gets no ``onResultSaved``, and, with
    no session, its own button that calls ``psynet.nextPage()``.

Joining and leaving
    The game's ``on_join`` runs when a player opens their first page in the
    session, and ``on_leave`` when their last one closes. With a Next button,
    a participant can move on during the game. Their page leaves the session,
    ``on_leave`` runs unless the page is still open in another tab, and the
    game carries on without them unless ``on_leave`` ends it.

Reloading and dropped connections
    The page reconnects by itself and rejoins, and gets the game as it
    stands. A reload usually runs ``on_leave`` and then ``on_join``, but runs
    neither if the new page joins before the old one has left. So an
    ``on_leave`` that ends the session also ends it when a player reloads. A
    message sent while the connection is down goes once it reconnects. A page
    reloaded within an hour of the session ending gets the ending at once.
    After that, the server has forgotten the session and refuses the
    connection.

Another tab
    The same page left open in another tab can go on playing until its
    connection drops, or the session ends: then it can't connect again.
