.. _live_games:

=====================
Live games: reference
=====================

This page is for looking things up rather than reading through. If you
haven't built a live game before, read the :doc:`live games design page
</design/live_games>` first, which explains how live games work and the ideas
they're built from, and then the :doc:`tutorial <live_game_tutorial>`, which
builds three demo games step by step and links to the sections here.

A live game has three pieces:

1. The game, a subclass of :class:`~psynet.live_game.LiveGame`, with a
   :class:`~psynet.live_game.LiveMessage` subclass for each kind of
   message a page can send.
2. The game page, a :class:`~psynet.live_game.LiveGamePage`, and a JavaScript file
   that plays the game through ``psynet.liveGame``.
3. A :class:`~psynet.live_game.PlayLiveGame` in the timeline, which
   makes each group that reaches it wait for its members, starts a game for
   the group, and then shows them the game page.

The design page explains state, messages and views. This page also uses:

outcome
    The game's result: what its ``outcome`` returns when the game ends.
answer
    One player's part of the outcome, which is their game page's answer
    (see `The answer`_).
reward
    What a player is paid for the game (see `Rewards`_).
record
    What is saved about a game: its outcome, its final state and the
    messages its pages sent. A :class:`~psynet.live_game.LiveGameRecord`
    reads it back (see `A game's record`_). The game page moves on once the
    record is saved.
game id
    The id of one game a group played, a record's ``id``. Dallinger calls a
    game a *session*, so its tables say ``session``.

.. _live-games-the-game:

The game
--------

A game's parts, each explained below or in the tutorial:

.. code-block:: python

    from psynet.live_game import LiveGame, LiveMessage, Reject


    class Choose(LiveMessage):
        type = "choose"  # the name a page sends it under
        action: str  # its fields, which PsyNet checks

        def apply(self, game, state, player, now): ...  # change the state, or raise Reject


    class MyGame(LiveGame):
        name = "my_game"  # must differ from every other game's
        messages = [Choose]  # the kinds of message its pages send
        min_players = 2  # and max_players, duration, timeout and away_timeout

        def initial_state(self, players): ...  # the state at the start, a dict
        def view(self, state, player): ...  # what a player's page shows, a dict
        def is_over(self, state): ...  # whether the game has ended
        def outcome(self, state, reason): ...  # the game's result
        def answer(self, outcome, reason, player): ...  # a player's part of it
        def performance_reward(self, outcome, reason, player): ...  # their pay
        def bot(self, view, player, now): ...  # a bot's next message, or None

        # And, if the game needs them: tick and next_deadline for a clock,
        # on_start, on_join and on_leave.

A game's ``outcome`` is its final state, without PsyNet's entry, unless it
defines ``outcome`` to return less, such as only what the analysis needs from
a large state.

Players are numbered in the order they joined the game, from 0. Those who
start it together are numbered in seat order (see
:attr:`~psynet.sync.SyncGroup.seats`), the order in which a
:class:`~psynet.group_prompt.GroupPrompt` shows the group, and a player who
joins a running game gets the next number. Each method gets the player's
number as ``player``, and
pages see only these numbers, never another player's participant id. A
game in which a player's position matters, such as who moves first, should
take it from a role, such as a :class:`~psynet.sync.Regrouper`'s
``roles``, which are shuffled, rather than from the number, which favours
whoever joined first. ``initial_state`` gets the list of numbers, such as
``[0, 1]``, so the state keeps what each player has in a list, in player
order, and in a game for two, ``1 - player`` is the other player.

``now``, in ``apply``, ``bot`` and the game's other methods, is the time in
seconds since the game started.

The clock, the outcome's ``reason`` and the methods' details come from
Dallinger's :class:`~dallinger.realtime.RealtimeGame`. Dallinger's guide to
`real-time games <dallinger-realtime-games_>`_ explains them, and its `API
reference <dallinger-realtime-api_>`_ describes each method and setting that
comes from ``RealtimeGame``.

PsyNet adds each game to the experiment's ``realtime_games`` itself, so you
don't list it there. It adds every game that Python has loaded, whether or
not the timeline plays it. That includes a game in a module you import from
another experiment, so give every game a name of its own. Dallinger calls
the name the game's ``channel``.

.. _live-games-messages:

Messages and the state
----------------------

PsyNet checks each message before its ``apply`` runs, and rejects one with a
field missing, an extra field, or a field of the wrong type. The sender's page
gets the reason. The check is strict: ``"1"`` isn't accepted as a number, nor
``1`` as text, and no number in the message can be ``NaN`` or infinite. A
message's ``apply`` can turn the message down too, by raising
:class:`~psynet.live_game.Reject` with a reason, such as for a move that's
against the rules. The state then stays as it was, and the sender's page gets
the reason.

A field can have any type Pydantic reads from JSON, such as a ``tuple``, an
``Enum``, a ``datetime`` or another Pydantic model, and in ``apply`` it holds
a value of that type. The state, though, is saved as JSON, so keep it to
plain data: dicts with string keys, lists, strings, finite numbers, booleans
and ``None``. After each method that changes the state, PsyNet converts any
other value to its JSON form, the form Pydantic gives it, such as a list for
a tuple, an enum member's value, or a string for a date. A value with no
JSON form, such as an object of a class of your own, ``math.inf`` or
``NaN``, makes the game fail, and so does a dict key that isn't a string,
which would read back as a string after a save. So compare a stored value
with the form it is stored in:

.. code-block:: python

    from psynet.live_game import Reject


    class Move(LiveMessage):
        type = "move"
        to: tuple[int, int]

        def apply(self, game, state, player, now):
            # The state holds a list, and a list never equals a tuple.
            if state["positions"][player] == list(self.to):
                raise Reject("You're already there.")
            state["positions"][player] = self.to

In the same way, compare an enum field's ``.value`` with the state, turn
a stored date back into a datetime with
``datetime.fromisoformat(state["deadline"])``, and store ``sorted(...)``
of a set, whose list has no fixed order. A game with a very large
state, such as a big grid, can save the time the conversion takes with
:attr:`~psynet.live_game.LiveGame.convert_state_to_json`.

.. _live-games-play:

PlayLiveGame
------------

Put a :class:`~psynet.live_game.PlayLiveGame` after the
:class:`~psynet.sync.Grouper` that forms the groups, and give it the game
page. It waits at a barrier, a :class:`~psynet.sync.GroupBarrier` for the
group's ``group_type``, until all of a group's members reach it, starts a
game, and then shows the group the game page:

.. code-block:: python

    timeline = Timeline(
        SimpleGrouper(
            group_type="pair",
            initial_group_size=2,
            below_quorum="continue_without_group",
        ),
        PlayLiveGame(
            group_type="pair",
            game_class=RockPaperScissors,
            settings={"throws": 5},
            late_after=60,
            late_action="leave_group",
            page=LiveGamePage(
                "rock_paper_scissors",
                tags.div(
                    tags.p(id="status"),
                    tags.p(id="rejection"),
                    tags.button("Rock", type="button", id="rock"),
                    tags.button("Paper", type="button", id="paper"),
                    tags.button("Scissors", type="button", id="scissors"),
                ),
                js_page_modules=["/static/rock-paper-scissors.js"],
                time_estimate=30,
            ),
        ),
        ...
    )

The game page plays the game that this ``PlayLiveGame`` started, so give
each ``PlayLiveGame`` a page of its own. Its ``id_``, which keys the
participant's records of their games, is the game's ``name`` unless you give
one. Steps with the same id share their wait,
like barriers with the same id, so a game that the timeline plays in two
places, such as a practice game and the main game, needs a different
``id_`` in each.

A game needs at least ``min_players`` players, 2 unless the game sets it. A
group that reaches the ``PlayLiveGame`` with fewer active members, for example
because the others left it while it waited, starts no game, and its members'
game pages show the no-game notice (see `Cases a game page should allow
for`_). Set ``min_players = 1`` for a game a player can play alone.

A game made for a fixed number of players, such as a game for two, or one
with something for each player that runs out, such as a color, sets
``max_players``. A larger group is a mistake in the experiment's design, so
it starts no game either, and PsyNet logs an error that says so. Make the
grouper's groups no larger than the game allows.

.. _live-games-wait:

``PlayLiveGame`` takes the options of a :class:`~psynet.sync.GroupBarrier`
for its wait, and needs a limit on it. Use ``late_after`` unless the group
takes newcomers:

- ``late_after``, with ``late_action="leave_group"``, waits for the slowest
  member, and removes them from the group if they keep the others waiting
  that many seconds. The members who were on time then reach the game page
  without a game. Give the pages before the game a ``time_limit``, such as
  instructions or the last game's result: ``late_after`` counts only from 10
  seconds after a page's time limit has run out, so it only has to cover the
  untimed moments. The group's grouper needs a ``below_quorum``, such as
  ``"continue_without_group"``, for the members left behind.
- ``max_wait_time``, with ``max_wait_action="leave_group"``, is for a group
  that takes newcomers, as in the ``microsociety_live`` demo. There PsyNet
  can't tell a slow member from one who hasn't joined yet, so it can't use
  ``late_after``. Instead each member waits ``max_wait_time`` seconds from
  when they arrive, and then leaves the group themselves.

Here and below, ``rock_paper_scissors_page()`` returns a new game page like
the one above:

.. code-block:: python

    InfoPage(instructions, time_estimate=60, time_limit=90),
    PlayLiveGame(
        group_type="pair",
        game_class=RockPaperScissors,
        page=rock_paper_scissors_page(),
        late_after=20,  # counts from 10 s after the instructions' 90 s are up
        late_action="leave_group",
    ),

A ``PlayLiveGame`` without either raises an error, since a group barrier's
default is to fail a member still waiting after 20 seconds. Bots that
``psynet test`` runs one at a time never meet, so the experiment refuses
live games whose bots aren't run together (see `Bots and testing`_), and two
``PlayLiveGame`` steps in the timeline with one id.

Its ``on_release`` runs when the wait before the game ends, not when the
game ends, once the group's game has been created. It gets the arguments a
group barrier's ``on_release`` takes, and also ``live_game``, the new game's
record (see `A game's record`_), whose ``status`` is ``"not_started"`` if the
group started no game. Use it for group bookkeeping at the
start of a round, such as choosing who leaves after it. Work done once the
game ends, such as scoring, goes in the trial, which gets the game's answer
(see `The answer`_), or in a later group barrier's ``on_release``.

To play one game under different conditions, such as with a different
number of throws, pass ``PlayLiveGame`` ``settings``: a dict, or any other
value that can be saved as JSON. The game's ``initial_state`` gets it as a
second argument, and keeps what the game's other methods need in the state,
since they get only the state:

.. code-block:: python

    PlayLiveGame(
        group_type="pair",
        game_class=RockPaperScissors,
        page=rock_paper_scissors_page(),
        settings={"throws": 3},
        late_after=60,
        late_action="leave_group",
    )


    class RockPaperScissors(LiveGame):
        def initial_state(self, players, settings):
            return {"n_throws": settings["throws"], "choices": [None, None], ...}

To vary the settings from trial to trial, return a ``PlayLiveGame`` from a
trial's ``show_trial``, and pass the trial's ``definition`` as the settings:

.. code-block:: python

    from psynet.trial.main import Trial


    class RockPaperScissorsTrial(Trial):
        sync_group_type = "pair"

        def show_trial(self, experiment, participant):
            return PlayLiveGame(
                group_type="pair",
                game_class=RockPaperScissors,
                page=rock_paper_scissors_page(),
                settings=self.definition,
                late_after=60,
                late_action="leave_group",
            )

Every member of a group has to arrive with the same settings: a member
whose settings differ from those of the members already waiting gets an
error that says so. Trials that a group plays in one round share a
definition, so set ``sync_group_type`` on the trial class and cue one trial
per player (see :ref:`rounds-cued-trials`). The ``bargaining_live`` demo
draws each pair's stake this way, with a function as the definition that
``cue`` calls once for the pair.

A trial played in a group needs a :class:`~psynet.sync.GroupBarrier` in its
``show_trial``, and the barrier of the ``PlayLiveGame`` is one. Each trial's
:attr:`~psynet.trial.main.Trial.live_game` is then the record of the game
played in it, with the trial's participant's answer.

.. _live-games-ready:

The ready step
--------------

Between the end of the wait and the start of the game, PsyNet waits a moment
for the players' pages, so that a page that opens a little after the others
doesn't miss the start. A game page says its player is ready by itself a
moment after it opens, and a bot is ready at once. The game starts once every
player is ready, or at the game's ``ready_timeout``, 60 seconds after the
wait ended unless the game sets it, and players who aren't ready then can
still join and play. If none of the players has opened the game page by
then, the game ends instead, with the reason ``"not_joined"``. A player
whose page closes before the game starts isn't ready any more, until the
page reconnects.

Until the game starts, it rejects messages with the reason ``"The game
hasn't started yet."``, and its ``tick`` and ``bot`` don't run, so disable
the page's controls with ``enableWhilePlaying`` (see `The game page`_), check
``playing``, or wait for ``onStarted``. The game's clock, ``now`` in its
methods, starts at 0 when the game starts, and the game's ``on_start`` runs
then. The game's other methods can run before it starts: ``on_join``,
``on_leave``, ``view``, ``is_over``, and ``outcome`` if the game ends before
it starts.

The messages that say a player is ready are PsyNet's, so a message's
``apply`` never receives them. To show who is ready, read
``state["psynet"]["ready"]`` from the view (see `PsyNet's entry in the
state`_).

.. _live-games-page:

The game page
-------------

The game page is the :class:`~psynet.live_game.LiveGamePage` given to the
``PlayLiveGame``, as in the example under `PlayLiveGame`_. It shows its
content, and its options, such as the texts below, change how it plays the
game. The page's JavaScript goes in a
file in the experiment's ``static`` folder, listed in the page's ``js_page_modules``. It exports an ``activate``
function, which PsyNet runs each time the page opens
(:doc:`/code/pages/custom_front_ends` explains page modules).
A sketch of one, ``static/my-game.js``, for the ``Choose`` message under
`The game`_ (the rock, paper, scissors demo's own page differs, since its
message also carries the throw's number):

.. code-block:: javascript

    export function activate({root, psynet}) {
        let buttons = ["rock", "paper", "scissors"].map(
            (action) => root.querySelector("#" + action)
        );
        psynet.liveGame.enableWhilePlaying(...buttons);
        psynet.liveGame.showStatus(root.querySelector("#status"), (view) =>
            view.chosen ? "Waiting for your partner" : "Your turn"
        );
        psynet.liveGame.showRejections(root.querySelector("#rejection"));
        for (let button of buttons) {
            button.addEventListener("click", () => {
                psynet.liveGame.send("choose", {action: button.id});
            });
        }
    }

``psynet.liveGame`` offers:

Showing the game:

- ``onChange(callback)`` calls ``callback`` with the game as the player sees
  it, whenever that changes: with each new view, ending with the final view,
  and, with a ``predict`` callback, after each ``send``, with the move
  predicted. Update the page here: what it shows, which controls work, and
  any state the page keeps from the view.
- ``showStatus(element, playing)`` keeps a status line up to date (see `The
  status line`_).
- ``enableWhilePlaying(...elements)`` enables buttons and other elements
  only while the game is played.
- ``player`` is this player's number, and ``players`` says how to show each
  player (see `Who's who`_).
- ``started`` and ``ended`` say whether the game has started and whether
  the player's game has ended, and ``playing`` whether it has started and
  not ended.
- ``hasGame`` says whether the group started a game at all (see `No game`_).
- ``onStarted(callback)`` calls ``callback`` with the first view once the
  game starts.

Sending moves:

- ``send(type, message)`` sends the game a message and returns its number.
- ``showRejections(element)`` shows why the game rejected the page's latest
  message.
- ``onRejected(callback)`` calls ``callback`` with the number of each
  rejected message and the reason, to show it some other way.

Showing time:

- ``onTimeLeft(callback)`` calls ``callback`` with the seconds left, a few
  times a second, for a countdown.
- ``gameTime()`` returns the seconds since the game started, the clock of
  ``now`` in the game's methods.
- ``duration`` and ``secondsLeft()`` give the game's ``duration`` and the
  seconds left in it (see `Time limits`_).

Smooth play (see `Smooth play`_):

- ``predict(callback)`` and ``predictedView()`` show the player's own moves
  at once.
- ``interpolate(callback)`` and ``interpolatedView()`` show other players
  moving smoothly between ticks.

At the end, and when players leave:

- ``onEnded(callback)`` calls ``callback`` once the player's game ends (see
  `The end`_).
- ``onResultSaved(callback)`` calls ``callback`` once the player's result is
  saved, and ``onRefused(callback)`` if the server refuses the page's
  connection. Either way, the page then moves on by itself.
- ``onResultTimeLeft(callback)`` calls ``callback`` with the seconds left
  before the page moves on, a few times a second, for a countdown while the
  page shows the result (see `The end`_).
- ``onPlayersAway(callback)`` calls ``callback`` with the numbers of the
  players who have left the game page (see `Joining and leaving`_).

Anything else:

- ``onReceive(callback)`` calls ``callback`` with each view as the game sends
  it, without predictions, and Dallinger's details of it. Few pages need it:
  it's for code that reacts to the views arriving, such as a measure of how
  far behind the page is.
- ``socket`` is the page's Dallinger socket, such as for ``serverTime``.

In ``onChange``, ``started``, ``ended`` and ``playing`` are already up to date
for the view. On a page that opens after the end, ``started`` stays
``false``, so check ``ended`` first, and the page gets just the final view
and ``onEnded``, not ``onStarted``. ``player`` is set from the page's first
view. ``gameTime()`` is ``null`` before the game starts, and so are
``duration`` and ``secondsLeft()``, which are also ``null`` for a game
without a ``duration``. ``send`` returns ``undefined`` once the page's
connection is closed or refused. ``enableWhilePlaying`` disables its
elements until the game starts, and again once it ends.

The page leaves the game when the participant moves on, so ``activate``
doesn't need to return a cleanup function for it.

.. _live-games-whos-who:

Who's who
~~~~~~~~~

``psynet.liveGame.players`` lists how to show each player, by player number,
as the group's other pages show them. Each player's ``label`` is "You" for
this player and otherwise their pseudonym, such as "Pink koala", and
``sticker_html`` draws their animal in their colour, as
:class:`~psynet.group_prompt.GroupPrompt` and chat rooms do. ``name``,
``css_color`` and ``emoji`` are the pseudonym's parts, and ``you`` says
whether it's this player:

.. code-block:: javascript

    // "You" or "Pink koala", or undefined for a moment after a player joins
    let name = psynet.liveGame.players[player]?.label;

With ``LiveGamePage(..., names="anonymous")``, every other player's ``label``
is "Your partner" in a game for two and "Another player" otherwise, as on the
group's other anonymous pages, ``sticker_html`` is the same neutral figure for all of
them, and the page is never sent their pseudonyms (see :doc:`pseudonyms`). A
player who joins while the game runs is added a moment after the views first
show them, and ``onChange`` then runs again, so a page that labels players in
``onChange`` shows the newcomer's name. A game's colours for its pieces, such
as each snake's, are the game's own, and needn't match the pseudonyms'.

PsyNet translates its own texts on the page, such as the notices and the
status line's defaults, and the labels above. Text that the game puts in its
views or its JavaScript is the experiment's, so translate it as the
experiment's other texts (see :doc:`/code/participants/internationalization`).

.. _live-games-status:

The status line
~~~~~~~~~~~~~~~

``showStatus(element, playing)`` keeps ``element`` saying what's happening:

- before the game starts, the page's ``waiting_status``, "Waiting for
  the other players to open the game" by default;
- while it's played, what ``playing(view)`` returns for each view, or
  nothing if ``playing`` is ``null``, for a page that shows what's happening
  some other way;
- once the player's game has ended, the page's ``ended_status``, "The
  game is over." by default.

The default texts are translated. A third argument, ``{waiting, ended}``,
replaces the page's texts, and ``ended`` can be a function of
the final view:

.. code-block:: javascript

    psynet.liveGame.showStatus(status, (view) => `Offer: ${view.offer}`, {
      ended: (view) => (view.deal ? "You made a deal." : "Time's up: no deal."),
    });

With a ``predict`` callback, ``playing`` gets the predicted view, and the
line is drawn again after each ``send``.

.. _live-games-smooth-play:

Smooth play
~~~~~~~~~~~

:ref:`The design page <design-live-games>` explains why a fast game needs
prediction and interpolation, and the tutorial's :ref:`Showing a choice at
once <live-game-tutorial-predict>` and shared canvas apply them.

``predict(callback)`` takes ``callback(view, type, message, sentAt)``, which
changes a copy of a view as the game will once it applies one of the page's
messages, sent with that ``type`` and ``message``. ``onChange`` then gets the
newest view with each message the game hasn't applied yet applied this way,
and runs again after each ``send``. The callback runs again for each new
view until the game has applied the message, and if the game rejects it, the
prediction goes. ``sentAt`` is the game time when the page sent the message,
or ``null`` if it wasn't known yet, and stays the same each time, for
predicting when something happens, such as when a moving boat arrives. Keep
the callback to what the game will certainly do. ``predictedView()`` returns
the same predicted view, for drawing at other times, such as in an animation
loop.

``interpolate(callback)`` takes ``callback(a, b, fraction)``, which returns a
new view part of the way between two tick views, for a game whose
``tick_rate`` is above 0. It must leave ``a`` and ``b`` unchanged, since
they're the tick views the page keeps. ``interpolatedView()`` returns the
game two tick intervals in the past, between the tick views either side of
that time. Call it each time the page draws, and draw the player's own piece
from ``predictedView()``, so it isn't behind.

.. _live-games-cases:

Cases a game page should allow for
----------------------------------

No game
~~~~~~~

A participant can reach the page without one, for example when another
member was late for the ``PlayLiveGame`` and their group broke up, or when
their group ended before they reached it. PsyNet tells the participant with
a notice at the top of the page, "Your group couldn't start the game.",
which the page's ``no_game_message`` changes or turns off, and hides the
page's content. When the page already has a notice saying that the
participant's group left them, such as "Your partner is no longer in your
group.", PsyNet doesn't add a second one. The page's
``psynet.liveGame`` methods then do nothing: ``send`` returns ``undefined``,
callbacks never run, and ``enableWhilePlaying`` leaves its elements
disabled. So a page needs no check for this, unless it starts work of its
own, such as an animation loop, which it can skip when
``psynet.liveGame.hasGame`` is ``false``.

Joining in time
~~~~~~~~~~~~~~~

The page joins the game when its JavaScript first uses
``psynet.liveGame``, so call ``onChange`` or ``showStatus`` in ``activate``.
If none of the group has opened the page by the game's ``ready_timeout``,
60 seconds after the wait ends unless the game sets it, the game ends with
the reason ``"not_joined"`` (see `The ready step`_).

Rejected messages
~~~~~~~~~~~~~~~~~

A message is rejected when one of its fields is missing or of the wrong
type, which is usually a mistake in the page's JavaScript, or when the
message's ``apply`` raises ``Reject``, such as for a move out of turn. Show
the participant the reason with ``showRejections``, or match the number
``send`` returned in ``onRejected``.

The end
~~~~~~~

A player's game ends when the game ends, or earlier in a game that lets
each player finish before the others (see `Players who join or finish
during the game`_). Their answer and reward are then worked out from the
outcome and saved, which this page calls the player's result.

``onChange`` gets the final view with ``ended`` set, and ``onEnded`` runs,
and the game ignores any message sent after that.

A game fails when its code raises an error or runs past the game's
`time_limit <live-games-time-limit_>`_, or when its record can't be saved. Its pages keep the view they had, which comes again with ``ended``
set, and once the failure is saved, each player's game page raises
:class:`~psynet.live_game.LiveGameFailed`, with the game's own error. PsyNet
then handles it as any other error in the experiment: it records the error
for the dashboard and the notifier, and fails the participant, who leaves
through the error page. In ``psynet test``, the bot's request raises, so a
game with a bug fails the test. A player whose own game ended before the
game failed, through ``is_done``, has their result and moves on as usual.
Endings that are part of play, such as ``"players_left"``, ``"timeout"`` and
``"not_joined"``, aren't failures.

The participant can leave the page only once their result is saved, a few
seconds after the game ends, and the page then moves on by
itself. Until then its Next button is hidden. A participant without a
game still sees it, so they can move on. So does a participant whose
page has been disconnected for ten seconds: if they click it, the page
says the game isn't over yet and moves on once the result is saved. The
page also moves on if the server refuses its connection, as it does when
the participant reloads the page long after the game ended.

To show the result on the game page first, pass the seconds to show it
for as the page's ``show_result_for``, such as
``LiveGamePage(..., show_result_for=8)``, and draw the result in
``onResultSaved``. The page moves on once the seconds are up, and
``psynet.liveGame.onResultTimeLeft`` counts them down for the page. A later :class:`~psynet.sync.GroupBarrier`'s ``late_after``
counts from the end of these seconds, so it needn't cover them.

To move on from the page's JavaScript instead, pass ``auto_advance=False``
to the page, and call ``psynet.nextPage()`` in both ``onResultSaved``
and ``onRefused``. The Next button then stays, and if the participant
clicks it before the result is saved, the page says the game isn't over
yet and sends the response again every second until it's accepted. If you
hide the Next button with ``show_next_button=False``, give a page without
a game another way to move on, such as a button of its own that calls
``psynet.nextPage()``.

.. _live-games-leaving:

Joining and leaving
~~~~~~~~~~~~~~~~~~~

The game's ``on_join`` runs when a player opens a page in the game while
none of theirs is open, and ``on_leave`` runs when their last one closes,
so a participant who closes the page during the game leaves it. Before the
game starts, both get ``None`` as ``now``.

A player away for the game's ``away_timeout``, 60 seconds unless the game
sets it, is gone, and once fewer than ``min_players`` players aren't, the
game ends with the reason ``"players_left"``, so the players left behind
can move on. A game for two ends a minute after one player goes, and a
game for five with ``min_players = 3`` carries on until a third player is
gone. Otherwise:

- A game that should end sooner, such as rock, paper, scissors, sets a
  shorter ``away_timeout``, such as 30.
- A game that should carry on however many players are away sets
  ``away_timeout = None``. Its players then wait until it ends by itself,
  so make sure it does, through its ``duration``, ``timeout`` or
  ``is_over``.
- A game that should react in its own way, such as by handing the player's
  turn on, does so in ``on_leave``, or ends in ``is_over``.

A reload or a dropped connection also makes a player leave for a moment,
so allow for one, with an ``away_timeout`` of 30 seconds or more, and don't
end the game in ``on_leave`` itself. ``bot`` doesn't play for a player who
has left, only for ``psynet test``'s bots.

While a player is away for more than a few seconds, the other players'
pages show a notice at the top that says "Another player has left the
game." Change it with the page's ``player_left_message``, such as
``LiveGamePage(..., player_left_message="Your partner has left.")``. To
show it your own way, set ``player_left_message=None`` and use
``onPlayersAway``, which gets the numbers of the players who are away,
and an empty list once they're all back. The notice only says what
happened: a game that should end when a player leaves ends through its
``away_timeout``, ``on_leave`` or ``is_over``.

Reloading and dropped connections
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The page reconnects by itself, rejoins and gets the game as it stands,
and messages sent while it was down go then. A reload usually runs
``on_leave`` and then ``on_join``, so an ``on_leave`` that ends the
game also ends it when a player reloads. A page reloaded within an
hour of the game ending gets the ending at once. After that, the
server refuses the connection.

Another tab
~~~~~~~~~~~

The same page open in another tab plays as the same player. When the
game's result is saved, both tabs try to move on. One of them does,
and in the other PsyNet asks the participant to close their other tabs
and refresh the page.

.. _live-games-time-limits:

Time limits
-----------

Each of these limits ends a wait or a game when it runs out. The first is
the ``PlayLiveGame``'s, and the others are the game's:

.. list-table::
   :header-rows: 1
   :widths: 25 20 55

   * - Setting
     - Default
     - When it runs out
   * - ``late_after`` or ``max_wait_time``, of the ``PlayLiveGame``
     - None: one is needed
     - The wait for the group's members ends. With ``late_after``, a member
       still keeping the others waiting is late and leaves the group; with
       ``max_wait_time``, a member who has waited that long leaves it (see
       `PlayLiveGame`_).
   * - ``ready_timeout``
     - 60 seconds after the wait
     - The game starts without the players who aren't ready yet, or ends
       with the reason ``"not_joined"`` if none of them has opened the game
       page (see `The ready step`_).
   * - ``duration``
     - ``None``
     - The game ends with the reason ``"finished"``.
   * - ``timeout``
     - 600 seconds after the start
     - A game without a ``duration`` that hasn't ended by itself ends with
       the reason ``"timeout"``.
   * - ``away_timeout``
     - 60 seconds
     - A player who has been away that long is gone, and once fewer than
       ``min_players`` players aren't, the game ends with the reason
       ``"players_left"`` (see `Joining and leaving`_).
   * - ``time_limit``
     - 1 second
     - The game's code has run that long in one of the runner's turns at
       the game, and the game fails (see below).

A game that lasts a fixed time sets ``duration``, in seconds. PsyNet runs
the game's ``tick`` at the end, if it has one, and then ends the game with
the reason ``"finished"``, unless the game's ``is_over`` ended it earlier.
Messages that arrive from then on are rejected with the reason ``"The
game's time is up."``. The page shows the time left with
``psynet.liveGame.onTimeLeft``, which gets the seconds left, 0 once the game
has ended, and ``psynet.liveGame.duration``:

.. code-block:: javascript

    psynet.liveGame.onTimeLeft((left) => {
      bar.style.width = `${(left / psynet.liveGame.duration) * 100}%`;
    });

A game that ends by itself, through its ``is_over``, has a ``timeout``
instead, in case it doesn't end: participants can't leave the game page until
the game ends. A game still running ``timeout`` seconds after it started
ends with the reason ``"timeout"``, and rejects messages from then on.
``timeout = None`` removes the limit, so set it only if the game always
ends by itself, even when players leave. A game
with a ``duration`` ends then, so its ``timeout`` doesn't apply.

For other deadlines, such as one for each move, a game returns the next one,
in seconds since the game started, from ``next_deadline``. Its ``tick`` runs
at each one, and at the end of its ``duration``. A tick that runs late gets
the end as ``now``, so a game that counts things on a schedule, such as
catches every few seconds, counts none after the end.

.. _live-games-time-limit:

The game's own ``time_limit`` is not a page's ``time_limit``: it limits how
long the game's code may run in one of the game runner's turns at it, the
ticks and messages that have come due since its last turn. It stops game
code that never finishes, and the game then fails (see `The end`_).
The game page itself can't have a ``time_limit``, since a page that runs
out of time would save no answer: limit the game with its ``duration`` or
``timeout`` instead.
Game code should take far less, since a runner plays its games in turn.
It can also run out when the runner falls far behind, with many ticks due at
once (see :ref:`performance_testing_live_games`).

If a game is still running more than a minute after it should have ended,
for example because the worker that runs the experiment's games has stopped,
its game page stops waiting: the participant sees PsyNet's error page, and a
bot fails with an error that names the game.

The game page also stops a later :class:`~psynet.sync.GroupBarrier` from
counting a player who is still in the game as late. ``late_after`` counts from
the group's previous barrier, which is usually the barrier of a
``PlayLiveGame``, so it would otherwise include the whole game. Instead, as
for a page with a ``time_limit``, it counts from when the game page ends: at
first the latest the game could end, plus a minute, and once the game's
result is saved, when the game actually ended, plus the page's
``show_result_for``. So ``late_after`` needs to cover only the pages after the
game.

.. _live-games-join-and-finish:

Players who join or finish during the game
------------------------------------------

Most games are played from start to end by the group that started them. A
game that keeps going while people come and go, such as a market or a
society fishing on a shared lake, can take new players while it runs, and
let each player finish before the others. The ``microsociety_live`` demo
does both.

Joining a running game
~~~~~~~~~~~~~~~~~~~~~~

Give the ``PlayLiveGame`` ``join_running_game=True``. A member who reaches
it while their group is playing a game from it then joins that game, and
goes straight to the game page instead of waiting at the barrier. A member
who arrives while no game is running waits at the barrier as usual, and
starts the next game with the others there. Newcomers join the group
first, through a :class:`~psynet.sync.Grouper` with
``join_existing_groups=True``. Give it ``use_admission_points=False``, so
that it admits them at once: a pending member waits at the barrier.

.. code-block:: python

    SimpleGrouper(
        group_type="society",
        initial_group_size=2,
        max_group_size=4,
        quorum=1,
        join_existing_groups=True,
        use_admission_points=False,
        below_quorum="continue_without_group",
    ),
    PlayLiveGame(
        group_type="society",
        game_class=Fishing,
        page=lake_page(),
        join_running_game=True,
        max_wait_time=60,
        max_wait_action="leave_group",
    ),

The game defines ``on_add(self, state, player, now)``, which makes room in
the state for the new player, such as by appending to each list in it:

.. code-block:: python

    class Fishing(LiveGame):
        ...

        def on_add(self, state, player, now):
            state["boats"].append({"spot": None, "joined_at": now or 0})
            state["fish"].append(0)

A new player gets the next number. ``now`` is
``None`` for a player added before the game starts, who has to be ready like
the others. A new player is in ``state["psynet"]["away"]`` until their page
opens, so an ``away_timeout`` covers one who never arrives. A game's
``max_players`` counts every player it has had: a member who would go over
it waits at the barrier for the group's next game. Write the page so that
it allows for views with more players than before, and give each new
player what they need, such as a colour no other player on the board has.

A game played in a trial can't take newcomers, since its round is already
under way, so a ``PlayLiveGame`` with ``join_running_game`` in a trial's
``show_trial`` raises an error.

Finishing before the others
~~~~~~~~~~~~~~~~~~~~~~~~~~~

To let a player's game end while the others play on, define
``is_done(self, state, player)``. It returns whether the player is done,
such as once they've had their turns or their time, or a string that says
why, which is then the reason their game ended. ``True`` gives the reason
``"done"``. PsyNet asks it about each player still playing after every
change to the state, once the game has started. It only reads the state,
so a game that ends a player's game after some time marks that in its
``tick``, as the demo does:

.. code-block:: python

        def tick(self, state, now):
            ...
            for boat in state["boats"]:
                if not boat["left"] and now >= boat["joined_at"] + STAY_SECONDS:
                    boat["left"] = "stayed"

        def is_done(self, state, player):
            return state["boats"][player]["left"]  # a reason, or None

A player whose game has ended gets their final view, with ``ended`` set, and
their page gets no more views. The game rejects their messages with the
reason "Your game has ended.", and a bot stops playing. Their answer and
``performance_reward`` come from the outcome of the state then, with their
reason, and their result is saved a few seconds later, so ``onResultSaved``
runs and the page moves on as it would at the end of the game. They no
longer count towards the game's ``min_players`` for its ``away_timeout``.

The game itself still ends through its ``is_over``, ``duration`` or
``timeout``, and the players still playing then get their results from the
outcome at the end. A game in which every player finishes in their own
time can end once nobody is left, with an ``is_over`` that returns whether
every player is done. Give it ``min_players = 1``, or no ``away_timeout``:
otherwise, once fewer than ``min_players`` players are still playing, the
game ends with the reason ``"players_left"``, however many of them are on
the page.

:class:`~psynet.live_game.testing.LocalGame` plays both:
``game.add(now=10)`` adds a player and returns their number, and
``game.is_done(player)`` asks the game's ``is_done``.

.. _live-games-answer:

The answer
----------

The game page's answer comes from the game's outcome: what the game's
``outcome`` method returned when the player's game ended. It covers the
player's time in the game. PsyNet sets it on the
server and ignores what the page sends, and a participant without a game
gets ``None``. By default, every player's answer is the whole outcome. Define
``answer(outcome, reason, player)`` to give each player only their own
part, so that a trial holds only its player's data and code reading
``trial.answer`` needs no player numbers:

.. code-block:: python

    class RockPaperScissors(LiveGame):
        ...

        def outcome(self, state, reason):
            return {"choices": state["choices"]}

        def answer(self, outcome, reason, player):
            choices = outcome["choices"]
            return {"mine": choices[player], "theirs": choices[1 - player]}

Results that belong to the whole group, such as a team's total, stay in the
outcome. The ``rock_paper_scissors_live``, ``snake_live`` and
``shared_canvas_live`` demos each define an ``answer``.

When the game is played as a trial (see `PlayLiveGame`_), PsyNet copies the outcome to the round the game was played in once
the game's result is saved, so a trial and later pages read the whole
group's outcome from the trial's record of its game, with no need for another
barrier after the game page to score the round:

.. code-block:: python

    pot = trial.live_game.outcome["pot"]

It is ``None`` until then. On a later page, the participant's record of the
game has their answer (see `A game's record`_):

.. code-block:: python

    answer = participant.live_games["snake"].answer  # None without one

.. _live-games-rewards:

Rewards
-------

A game can add to each player's performance reward in two ways. Each amount
must be a number of 0 or more. For a reward based on the outcome, define
``performance_reward(outcome, reason, player)`` to return the player's
reward. PsyNet pays it to each player once, when their result is saved,
however the game ended, so a player who left the game page early is paid
too. A player whose game ended early, through ``is_done``, is paid from the
outcome then. This game pays 0.10 for a win:

.. code-block:: python

    BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}


    class RockPaperScissors(LiveGame):
        ...

        def performance_reward(self, outcome, reason, player):
            choices = outcome["choices"]
            mine, theirs = choices[player], choices[1 - player]
            return 0.10 if mine is not None and BEATS[mine] == theirs else 0

``reason`` is ``"finished"`` when ``is_over`` returned ``True`` or the
game's ``duration`` ran out, and ``"timeout"`` when its ``timeout`` did. An
``is_over`` that returns a string instead, such as ``"deal"``, ends the
game with that string as its reason, which then isn't ``"finished"``.
Dallinger's `outcome <dallinger-outcome_>`_ lists the other reasons, such as
``"not_joined"``. If the game's code raised an error, ``reason`` is
``"failed"``, and ``outcome`` is the outcome of the state just before the
error.

For a reward earned during the game, such as for each coin a player collects,
call ``game.add_performance_reward(player, amount)`` in a message's
``apply`` or in another method that changes the state. PsyNet adds it to the
player's reward a few seconds later, so the player keeps it even if they
leave early.

When the game is played as a trial, PsyNet also records both kinds of
reward on the player's trial, adding them to its ``performance_reward``, so
each trial shows what its game paid. A trial can pay through its own
``score_answer`` and ``compute_performance_reward`` instead, as the
``rock_paper_scissors_live`` demo does, when what a game pays depends on the
trial's definition. The two would add up, paying each player twice, so a
game with a ``performance_reward`` played in a trial with a
``compute_performance_reward`` raises an error.

A game that fails (see `The end`_) still pays its ``performance_reward`` from
the outcome of the state before the error, unless the record couldn't be
saved or ``outcome`` raised an error too, and amounts from
``add_performance_reward`` saved before the problem are paid either way. Its
players then leave through the error page, which pays them as error recovery
does.

.. _live-games-record:

A game's record
---------------

Each game's record is saved with the experiment's data, in Dallinger's
``realtime_session`` and ``realtime_event`` tables: the game's outcome and
final state, and each message a page sent, with whether the game accepted it.
In Python, a :class:`~psynet.live_game.LiveGameRecord` reads it back. The
participant's :attr:`~psynet.participant.Participant.live_games` gives their
record of their latest game at each ``PlayLiveGame`` they reached, keyed by
its ``id_``, as ``participant.active_sync_groups`` is keyed by group type:

.. code-block:: python

    game = participant.live_games["rock_paper_scissors"]
    if game.finished:
        game.answer  # this participant's answer
        game.outcome  # the whole game's outcome
        for saved in game.messages:
            if saved.type == "choose":
                print(saved.player, saved.message.action, saved.time)

A record has:

- ``status``: ``"not_started"`` if the participant's group started no game
  there, for example because it broke up while it waited, ``"running"``
  until the game's result is saved, then ``"ended"``, or ``"failed"`` if the
  game's code raised an error or its record couldn't be saved, with the
  error in ``error``;
- ``finished``, whether ``end_reason`` is ``"finished"`` (see `Rewards`_ for
  the reasons), rather than early, for example because players left;
- ``outcome`` and ``end_reason``, the game's outcome and the ``reason`` it
  ended, both ``None`` until it has ended;
- ``answer``, the participant's answer on the game page, and ``player``,
  their player number;
- ``answers``, each player's answer, in player order, and
  ``participant_ids``, each player's participant id;
- ``messages``, ``moments`` and ``checkpoints``, below;
- ``id``, the game id, and ``record_complete``, which is ``False`` if saving
  the record failed.

A game that didn't start has a record too, with ``None`` and empty lists, so
a page can read ``participant.live_games["snake"].answer`` and get ``None``
without a game. A step the participant never reached isn't in
``live_games``. Each attribute reads the database when you use it, so a
record of a running game stays up to date.

Other records of the same games:

- :attr:`~psynet.participant.Participant.live_game_history` gives a list of
  every game the participant played at each step, oldest first, such as one
  per round of a loop, each with their answer in it.
- A trial's :attr:`~psynet.trial.main.Trial.live_game` is the participant's
  record of the game played in the trial, so an analysis of trials reads
  ``trial.live_game.outcome``.
- A group's :attr:`~psynet.sync.SyncGroup.running_live_games` gives the
  games it is playing now, keyed in the same way. These records are the
  group's, not one participant's, so they have ``answers`` but no ``answer``
  or ``player``.

.. _live-games-saved-messages:

Saved messages
~~~~~~~~~~~~~~

``messages`` holds each message as a :class:`~psynet.live_game.SavedMessage`,
in the order the game applied them, with its ``type``, the sender's
``player`` number and ``participant_id``, and its ``time`` in seconds since
the game started, negative for a message that arrived before the start.
Pick out one type with ``[m for m in game.messages if m.type == "choose"]``.
Its ``message`` is the :class:`~psynet.live_game.LiveMessage` the page sent,
or ``None`` if what the page sent can't be read as one of the game's message
types, and its ``payload`` holds what the page sent. Each player's
:class:`~psynet.live_game.PlayerReady` message says when they became ready.

Each message also has ``receive_time``, when it arrived as a date and time;
``browser_time``, the clock on the participant's own computer when their page
sent it; ``view_time``, the game time of the view the participant was looking
at when they acted; and ``status``, whether the game accepted it. In the
exported ``realtime_event`` table, its ``event_type`` column tells messages
apart from the game's other events, such as its end.

The record is written a few seconds behind the game, so while a game is
still running, ``messages`` holds only the messages written so far. By the
page after the game page, the whole record has been written, unless
``record_complete`` says that saving it failed.

A game saves every message by default. A game whose pages send many
messages, such as a move on every key press, can leave some out with the
message type's :meth:`~psynet.live_game.LiveMessage.should_save`, which
returns ``False`` for a message to leave out. Keep what the analysis needs,
such as when each player found the exit, in the state or the outcome:
``should_save`` only decides whether the message itself is kept too. It runs
after the game has accepted or rejected the message, and ``rejection`` is
the :class:`~psynet.live_game.Reject` that ``apply`` raised, or ``None``:

.. code-block:: python

    class Step(LiveMessage):
        type = "step"
        direction: Literal["up", "down", "left", "right"]

        def apply(self, game, state, player, now):
            ...
            if state["positions"][player] == state["exit"]:
                state["found_exit"][player] = now

        def should_save(self, game, state, player, rejection):
            # Keep only the steps into walls, which apply rejects.
            return rejection is not None

PsyNet always saves its own messages, such as each player's
:class:`~psynet.live_game.PlayerReady`. A message the game couldn't read
is saved too, with ``message`` set to ``None``.

A message left out isn't in the exported data, so leave out only what the
analysis won't need. Dallinger's `save_message <dallinger-save-message_>`_
has the details.

.. _live-games-history:

Moments and copies of the state
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The outcome describes how a game ended, which is enough for a short game.
A game that runs for a long time, or changes as players come and go,
also needs a record of what happened along the way, such as each catch or
each trade. Record it with ``self.record(name, data)`` in a method that
changes the state, such as ``tick`` or a message's ``apply``:

.. code-block:: python

        def tick(self, state, now):
            ...
            self.record("catch", {"at": at, "caught": caught})

A record's ``moments`` holds the game's moments in order, each a
:class:`~psynet.live_game.LiveGameMoment` with its ``name``, its ``data``
and its ``time`` in seconds since the game started, so
``[m for m in game.moments if m.name == "catch"]`` is the catches. Moments are saved with the game's
messages, so like them they're written a few seconds behind the game, and
they're in the exported ``realtime_event`` table, as effects with the name
``psynet_moment``. The ``microsociety_live`` demo shows newcomers the
recent catches from its moments, and exports a row for each catch.

Dallinger also saves copies of the game's state, at most every five seconds
by default (the game's ``checkpoint_interval``), and when the game ends.
A record's ``checkpoints`` holds them, each a
:class:`~psynet.live_game.LiveGameCheckpoint` with the ``state``, without
PsyNet's entry, and its ``time``. They help to check what a game did, but
when they're taken depends on the game's traffic, so record what an
analysis needs as moments.

.. _live-games-bots:

Bots and testing
----------------

``psynet test`` runs an experiment with bots, which don't run a page's
JavaScript. When a group's members include bots, the game plays for them
through its ``bot`` method. It gets the
bot's view, the bot's player number and ``now``, and returns the bot's next
message, or ``None`` to send nothing. A message the game can't read makes
the game fail. A :class:`~psynet.live_game.PlayLiveGame` refuses a game
without ``bot``, since its bots would never move.

In a game without ticks, nothing happens between messages, so the game asks
the bots for their next moves straight after each change: once the game has
started, and again after every message (other bots' too), join and leave,
until no bot sends a message the game accepts. So ``bot`` must return
``None`` once the bot has nothing to do, or the bots would play forever and
the game fails. In a game with ticks, it runs once per tick. Dallinger's `bot
<dallinger-bot_>`_ has the details.

A group's bots have to reach the ``PlayLiveGame`` together, so set the
experiment's ``test_mode = "parallel"``, and ``test_n_bots`` to a multiple of
the group size. The experiment refuses live games with more than one bot run
one at a time, unless its ``test_serial_run_bots`` drives them, as the
``microsociety_live`` demo's does. A bot's answer on the game page comes from the game's
``answer`` too, so the page doesn't need a ``bot_response``. Check each
bot's game at the end of the test through its record:

.. code-block:: python

    class Exp(psynet.experiment.Experiment):
        timeline = ...

        test_mode = "parallel"
        test_n_bots = 2

        def test_check_bot(self, bot, **kwargs):
            super().test_check_bot(bot, **kwargs)
            game = bot.live_games["rock_paper_scissors"]
            assert game.finished, game.error
            assert game.answer["mine"] is not None

To test a game's rules in Python, without starting the experiment, play it
with :class:`~psynet.live_game.testing.LocalGame`. It starts the game, and
calls the game's methods as PsyNet does. With the tutorial's rock, paper,
scissors game:

.. code-block:: python

    import pytest
    from psynet.live_game import Reject
    from psynet.live_game.testing import LocalGame

    game = LocalGame(RockPaperScissors, players=2, settings={"throws": 1})
    game.send(0, Choose(throw=1, action="rock"))
    assert game.view(0)["chosen"] and not game.is_over()
    assert game.bot(0) is None
    with pytest.raises(Reject):
        game.send(0, Choose(throw=1, action="paper"))
    game.send(1, Choose(throw=1, action="paper"))
    assert game.is_over()

``send`` raises ``Reject`` for a message the game rejects. ``leave`` and
``join`` close and open a player's game page, and ``is_over`` returns the
reason the game ended when it has one, such as ``"players_left"``.

Each of the experiment's worker processes runs a game runner, which plays
its games one after another, so slow game code in one game delays the
others. To check that a game's code keeps up with many games at once, time
it with ``LocalGame.time_play`` and run a performance test (see
:ref:`performance_testing_live_games`).

To play a game yourself, run ``psynet debug local`` and open the participant
link in a browser window for each player. For a game with ticks, run
``psynet debug local --legacy`` instead, which uses gunicorn, the web server a
deployed experiment uses. The development server that ``psynet debug local``
runs by default sometimes delivers the game's views late, in bursts, so other
players' movement stalls or jumps, which looks like a problem with the game
when it isn't. ``psynet debug local`` warns about this when it starts.

PsyNet's entry in the state
---------------------------

PsyNet keeps its own record of the game in ``state["psynet"]``, and adds
the same entry to each view. Don't use the name ``psynet`` for anything else
in the state or a view. The parts a game can use are:

- ``participant_ids``, each player's participant id, in player order,
  including players added while the game runs. It is in the state only, not
  in views.
- ``ready``, the numbers of the players who are ready
- ``away``, the numbers of the players who have left the game page and not
  come back. One of the game's first players who hasn't opened it yet isn't
  in it, but a player added while the game runs is, until their page opens.
- in a view, ``you``, the number of the player it's for, which the page
  reads as ``psynet.liveGame.player``

The entry's other parts, such as ``started_at``, are PsyNet's timekeeping,
on Dallinger's clock rather than the game's. Use ``now`` and the page's
``gameTime()`` instead.

.. _dallinger-realtime-games: https://dallinger.readthedocs.io/latest/realtime_games.html
.. _dallinger-realtime-api: https://dallinger.readthedocs.io/latest/realtime_games.html#api-reference
.. _dallinger-outcome: https://dallinger.readthedocs.io/latest/realtime_games.html#dallinger.realtime.RealtimeGame.outcome
.. _dallinger-save-message: https://dallinger.readthedocs.io/latest/realtime_games.html#dallinger.realtime.RealtimeGame.save_message
.. _dallinger-bot: https://dallinger.readthedocs.io/latest/realtime_games.html#dallinger.realtime.RealtimeGame.bot
