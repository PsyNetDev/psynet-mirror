=============================
Groups and barriers in detail
=============================

A :class:`~psynet.sync.Grouper` forms groups of participants, and a
:class:`~psynet.sync.GroupBarrier` makes the members of a group wait for each
other. The ``rock_paper_scissors`` demo pairs participants and plays three
synchronized rounds:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors/experiment.py
   :start-at: timeline = Timeline(
   :end-before: test_n_bots
   :dedent: 4

Forming groups
--------------

:class:`~psynet.sync.SimpleGrouper` waits until enough participants are
waiting, then randomly splits them into groups. Participants stay on their
current page, under a waiting indicator, until their group is formed, unless
the grouper has a ``waiting_screen`` (see below).

``group_type``
    A label for the groups. Barriers and trial makers refer to the groups by
    this label.

``initial_group_size``
    The size of each new group. Required.

``batch_size`` (default: ``initial_group_size``)
    How many participants must be waiting before groups are formed. A larger
    batch lets you form several groups at once from the same pool.

``quorum`` (default: ``start_short_with``, or else ``initial_group_size``)
    How many active members a group needs to keep going. A group whose
    members fail or leave until it has fewer is below quorum: it cannot pass
    a barrier, and waits for newcomers or is dissolved (see
    `Groups below quorum`_). For groups of three or more, leaving it out
    warns, so that you decide how many may drop out. ``min_group_size`` is
    a deprecated name for it.

``join_existing_groups`` (default: ``False``)
    If ``True``, an arriving participant first joins an existing group that
    is below ``max_group_size``, preferring the smallest and then the oldest
    group. Participants already waiting at the grouper join such a group on
    the next barrier check after one has room. Closed groups and groups with
    no active members are not joined. Groups formed with this option accept
    *top-ups*; see `Groups below quorum`_ for how they stop and what they
    change when a member drops out.

``max_group_size`` (default: ``initial_group_size``)
    The largest size a group can reach through ``join_existing_groups``;
    ``None`` means no limit. Setting it to anything else requires
    ``join_existing_groups=True``. The limit holds when several participants
    try to join at once: joins to one group take turns, and a participant
    who finds a group busy tries the next suitable group, or waits at the
    grouper and tries again shortly.

``join_criterion``
    A function of ``group`` and ``participant`` that returns whether the
    participant may join that group. Only used with
    ``join_existing_groups=True``. Returning ``False`` only turns that
    newcomer away (see `Groups below quorum`_).

``start_short_after`` (default: ``None``)
    Seconds after which a smaller group may start. Once the longest-waiting
    participant has waited this long and at least ``start_short_with`` are
    waiting, those waiting form a group even if there are fewer than
    ``batch_size``. Needs ``quorum`` or ``start_short_with``, and a
    ``max_wait_time`` (default 20 seconds) longer than ``start_short_after``.
    A ``{SECONDS}`` placeholder in ``waiting_message`` counts down to that
    short start once ``start_short_with`` are waiting; until then the
    participant sees "Waiting for other participants…", or what
    :ref:`a message function <sync-countdown-messages>` returns.

``start_short_with`` (default: ``quorum``)
    The smallest group a short start may form. Leave it unset to start short
    at the quorum; pass a larger value to require more members than the
    quorum before a short start. If you pass it without ``quorum``, the
    quorum defaults to it; the quorum may not be larger, so that a group
    started short is not below quorum at its first barrier.

    With ``join_existing_groups=True``, later arrivals can fill a group
    started short up; see `Groups below quorum`_ for what top-ups change
    when a member then drops out.

``max_wait_time`` (default: 20) and ``max_wait_action`` (default: ``"fail"``)
    How long a participant may wait for a group, and what happens then:
    ``"fail"`` fails them, and ``"continue_without_group"`` lets them carry
    on without one (see `Timeouts`_).

``waiting_message``
    The message on the waiting indicator. If omitted, participants see
    "Waiting for other participants…". For translated experiments, mark it as
    described in :doc:`/code/participants/internationalization`.

``id_`` (default: ``{group_type}_grouper_{initial_group_size}``)
    Groupers with the same ID share one pool of waiting participants.

The ``gibbs_within_sync`` demo tops up groups of three, but only while the
leader has more than one trial left:

.. literalinclude:: ../../../demos/experiments/gibbs_within_sync/experiment.py
   :start-at: SimpleGrouper(
   :end-before: trial_maker,
   :dedent: 8

.. literalinclude:: ../../../demos/experiments/gibbs_within_sync/experiment.py
   :pyobject: is_group_joinable

Groups are formed only from participants who are waiting at the same time,
so recruitment must bring them in close together. A participant who waits at
a grouper for longer than ``max_wait_time`` (default 20 seconds) is failed,
or continues without a group with ``max_wait_action="continue_without_group"``;
raise ``max_wait_time`` if participants arrive slowly.

Accessing the group
~~~~~~~~~~~~~~~~~~~

Each group is a :class:`~psynet.sync.SyncGroup`. Inside a trial,
:attr:`Trial.sync_group <psynet.trial.main.Trial.sync_group>` returns the
group of the trial maker's ``sync_group_type`` (or, for a cued trial, the
trial class's) that the trial was played in. Elsewhere, use
``participant.sync_group`` if the participant is in one active group, or
``participant.active_sync_groups[group_type]`` if they are in several.
``participant.in_sync_group(group_type)`` tells whether they are still in a
group of that type.

A :class:`~psynet.timeline.PageMaker` builds its page again when the
participant submits it, and by then they may have left their group. Read
the group with ``participant.active_sync_groups.get(group_type)``, which
returns ``None`` once they have left, rather than indexing it, which raises
a ``KeyError``, and build the page without the group in that case. To keep
using a value from the group, such as a chat room ID, store it in a
participant variable when the page is first built.

``sync_group.participants`` is a read-only list of the group's members; change
membership with ``sync_group.add_participant(participant)`` and
``sync_group.remove_participant(participant)``. The list has no guaranteed
order, so sort by participant ID when you need a stable one, for example to
assign roles. ``sync_group.leader`` is the group's leader.

Regrouping
~~~~~~~~~~

A participant can be in groups of different ``group_type`` at the same time,
but in only one group of each type. To regroup participants, close the group
with a :class:`~psynet.sync.GroupCloser` and place another grouper with the
same ``group_type``. A ``GroupCloser`` is a group barrier, so members wait
there for each other; the end of the timeline needs none, because a group
whose members have all finished closes by itself. The ``simple_sync_group`` demo forms groups of three,
then groups of two, and assigns roles at a barrier each time:

.. literalinclude:: ../../../demos/experiments/simple_sync_group/experiment.py
   :start-at: timeline = Timeline(
   :end-before: test_n_bots
   :dedent: 4

.. literalinclude:: ../../../demos/experiments/simple_sync_group/experiment.py
   :pyobject: assign_roles

Two groupers of the same type and size share a default ID, and so a waiting
pool. Give them different ``id_`` values if they should not.

Rounds with changing groups
~~~~~~~~~~~~~~~~~~~~~~~~~~~

If the same group plays every round, you need no regrouper: form the group
once with a :class:`~psynet.sync.SimpleGrouper` and make the round loop's
body one cued trial whose ``show_trial`` contains the
:class:`~psynet.sync.GroupBarrier` objects (see :ref:`rounds-cued-trials`). Use a
regrouper when each round should form new groups, for example new pairs
within a cohort.

In games played over many rounds, a participant who is slow in one round
should not hold up everyone else, and should not be failed either. A
:class:`~psynet.sync.Regrouper` placed at the start of each round handles
this. Each time a participant reaches it, they leave their previous group of
that type and wait for the next round. The regrouper then splits everyone
waiting into new groups, when every member of the participant's ``within``
group (such as their cohort) is waiting, or when ``deadline`` passes, without
whoever isn't ready yet, provided enough participants are waiting to form a
group. Latecomers join the next round. The groups it forms are
never dissolved when a member leaves, so the members who are left continue
the round on their own.

.. code-block:: python

    pairing = Regrouper(
        "pair",
        within="cohort",
        roles=["proposer", "responder"],
        deadline=50,
        left_over="sit_out",  # an odd player out sits the round out
    )

By default, those who have played the most rounds sit out when not
everyone fits, players are kept apart from last round's partners where
possible, and roles alternate. With ``avoid_repeats="all_rounds"`` they are
kept apart from everyone they have played with before, so that a cohort of
four meets each partner once in three rounds of pairs. The regrouper counts each participant's
rounds: :meth:`~psynet.sync.Regrouper.rounds_played`,
:meth:`~psynet.sync.Regrouper.rounds_sat_out`,
:meth:`~psynet.sync.Regrouper.sat_out` (for the latest round) and, with
``roles``, :meth:`~psynet.sync.Regrouper.role`.

Play each round as one trial per player, added after the regrouper with
:meth:`Trial.cue() <psynet.trial.main.Trial.cue>` on a trial class that sets
``sync_group_type``. The trials of a group's members in one round share a
:class:`~psynet.trial.main.SyncGroupNode` for the group's results, and each
trial records the group, the player's role and the round, so the game needs
no bookkeeping of its own and its data can be exported from trials and
nodes (see :ref:`rounds-cued-trials`).

:doc:`writing_a_round_based_experiment` builds a complete game this way, including moving
slow players on and sitting out. :class:`~psynet.sync.Regrouper` lists all
its settings, for example rounds on fixed ticks (``every``), fixed roles and
custom grouping.

``waiting_message`` sets the message on the waiting indicator. A ``{SECONDS}``
placeholder shows a live countdown to the deadline, for example ``"The next round starts in {SECONDS} s."``.
Only waits with a release time can count down: a regrouper with ``deadline``
or ``every``, and a :class:`~psynet.sync.SimpleGrouper` with
``start_short_after``. A ``{SECONDS}`` placeholder in a fixed message
anywhere else raises an error; a message function that returns one there
shows "…" instead of a number.

.. _sync-countdown-messages:

**Countdown messages.** Sometimes the barrier doesn't know yet when the
wait will end, for example while a participant waits alone for a partner.
Then ``{SECONDS}`` shows "…", or a :class:`~psynet.sync.SimpleGrouper`
shows "Waiting for other participants…" in place of a fixed message. To show different text then, pass a
module-level function as ``waiting_message``. It receives ``seconds_left``, which
is ``None`` while the time is unknown and otherwise the whole seconds left
(0 once the time has passed), and can also take ``participant`` and
``barrier``. For a live countdown, return the literal ``{SECONDS}``
placeholder rather than writing ``seconds_left`` into the text, which would
stay fixed until the function is next called. The message switches within a
few seconds of the time becoming known:

.. literalinclude:: ../../../demos/experiments/lowest_unique_number/experiment.py
   :pyobject: round_message

Keeping a group in step
-----------------------

Barriers
~~~~~~~~

A :class:`~psynet.sync.GroupBarrier` holds each member until every active
member of the group has reached it. When the last member arrives, the barrier
calls ``on_release`` for the whole group. In ``rock_paper_scissors`` the
barrier after each choice scores the round and saves each player's result
on their trial, where ``show_feedback`` reads it:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors/experiment.py
   :pyobject: RockPaperScissorsTrial.show_trial

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors/experiment.py
   :pyobject: RockPaperScissorsTrial.score_trial

``on_release`` can take any of the arguments ``group``, ``participants``,
``trials`` (each member's current trial, in the same order as
``participants``, or ``None`` for a member with none; its ``answer`` holds
the answer so far), ``node`` (the group's
:class:`~psynet.trial.main.SyncGroupNode` for the round if those trials are
on it, ignoring members with no current trial, and otherwise ``None``),
``leader`` and ``barrier`` (``participant`` is the leader too, kept for
compatibility). In ``rock_paper_scissors`` every pair plays on the same
node, which is not a group's node, so ``node`` is ``None`` and the results
go on the trials. Cued trials share a node per group and round, so there a
``@classmethod`` on the trial class can also save the
group's results in ``node.var`` (see :ref:`rounds-cued-trials`). Results on
the trial or node stay in the export for every round, while a participant
variable keeps only the latest. ``on_release`` must be a module-level
function, a static or class method, or a method bound to a trial maker or a
saved database object such as a trial. The ``barrier`` it receives is rebuilt
from saved settings, so read only scalar settings such as ``waiting_message`` and
``max_wait_time`` from it, and store custom barrier attributes as
JSON-compatible values. Closures and lambdas can't be saved, so to share one
callback between barriers, give each barrier its own arguments with
:func:`functools.partial`. Pass them by keyword, as JSON-compatible values
named in the function's parameters; they take precedence over arguments of
the same name that PsyNet passes:

.. code-block:: python

    from functools import partial

    def score_question(group, question):
        ...

    GroupBarrier(id_="question_1", group_type="team",
                 on_release=partial(score_question, question=1))

``on_release`` can also take ``left``, the members who left the group since
its previous barrier pass (or since it formed), ordered by participant ID;
``participant.sync_group_removal_reason(group_type)`` says why each went, for
example to tell a player whether their partner returned the study or was too
slow.

``on_release`` runs only when the barrier releases the group. A member who
leaves the group before then, or whose group is dissolved, doesn't get
the results it would have stored, so read them with ``.get``, which returns
``None`` when they aren't set: ``trial.var.get("score")`` for results saved on
the trial, or ``participant.var.get("score")`` when there is no trial.
If the group dissolves while some members are waiting at the barrier,
``on_dissolve`` runs for them instead, before they leave the group, with the
same arguments except ``leader`` and ``left``.
``participants`` are then the members waiting at the barrier, so a quiz can
still score the last question for those who answered it:

.. code-block:: python

    GroupBarrier(id_="question_3", group_type="team",
                 on_release=partial(score_question, question=3),
                 on_dissolve=partial(score_question, question=3))

``on_dissolve`` can also do something other than ``on_release``. In the
``public_goods`` demo, a group of three plays on with two, so the group
dissolves when one player is left and the round is cancelled. Its
``on_dissolve`` records the contributions of the round for the export:

.. literalinclude:: ../../../demos/experiments/public_goods/experiment.py
   :pyobject: ContributionTrial.cancel_round

Members who are still on an earlier page, such as the question itself, when
the group dissolves get neither callback: they pass the barrier without
waiting. If they need a result too, give them one in a step after the
barrier, for example when
``participant.sync_group_removal_reason("team") == "group_dissolved"``.
``public_goods`` pays the last player for the cancelled round in
``score_answer``, at the end of their trial, whether or not they were
waiting at the barrier:

.. literalinclude:: ../../../demos/experiments/public_goods/experiment.py
   :pyobject: ContributionTrial.score_answer

The barrier ``id_`` identifies one waiting point. Barriers with the same ID
share a waiting pool, so give barriers with different ``on_release``
callbacks different IDs. Using one ID for barriers with different behavior
(class, ``on_release`` or release settings) raises an error when the
experiment is built. Waiting settings such as ``max_wait_time``,
``max_wait_action`` and ``waiting_message`` may differ, because each applies
to the participant who waits.

Arrival notices
~~~~~~~~~~~~~~~

While a member waits at a barrier, members who have not reached it yet see a
notice on the progress bar ("Your partner is ready.", or
"{ARRIVED}/{TOTAL} of your group are ready."). In groups of three or more,
the waiting indicator also has a smaller second line saying how many members
are not ready yet. Set ``notify_arrivals=False`` to turn both off, or pass
``on_arrival_message`` to change the notices. It receives ``kind``
(``"notice"`` for the progress bar, ``"removed"`` for the notice a member
sees after being removed for being late, ``"waited_too_long"`` for the one
on the next page of a member removed after waiting too long), ``waiting_count`` and
``group_size``, and returns the text or ``None`` to hide it. For a notice it
is called whenever the browser fetches the current count, which can be
several times per arrival, so it should depend only on its arguments and
have no side effects. Notices must fit on two lines of a phone screen:

.. code-block:: python

    def arrival_message(*, kind, waiting_count, group_size, **kwargs):
        if kind == "removed":
            return "Your partner went on without you. Please continue."
        if kind == "waited_too_long":
            return "Your partner didn't arrive in time. Please continue."
        return "Your partner is ready."

    GroupBarrier(
        id_="finished_trial",
        group_type="rock_paper_scissors",
        waiting_message="Waiting for your partner",
        on_arrival_message=arrival_message,
    )

Pages with a :class:`~psynet.group_prompt.GroupPrompt` that ticks members
live don't show the notice, since the ticks say the same.

``waiting_message`` can also be a module-level function of the participant, so that
members waiting at the same barrier see different messages, for example by
role (it can also take ``seconds_left``; see :ref:`countdown messages <sync-countdown-messages>`):

.. code-block:: python

    def waiting_text(participant):
        if participant.var.role == "proposer":
            return "Waiting for your partner to accept or reject your offer…"
        return "Your partner is deciding how much to offer you…"

    GroupBarrier(id_="decided", group_type="pair", waiting_message=waiting_text)

A ``waiting_message`` function on a group barrier can also take ``waiting_count`` and
``group_size`` (both ``None`` if the participant has no group); return
:func:`~psynet.sync.hold_message` from it to write the second line yourself,
or to leave it out:

.. code-block:: python

    from psynet.sync import GroupBarrier, hold_message

    def waiting_text(waiting_count, group_size):
        return hold_message(
            "Waiting for the rest of the room…",
            f"{waiting_count} of {group_size} have chosen",
        )

    GroupBarrier(id_="chosen", group_type="room", waiting_message=waiting_text)

By default the participant's last page stays on screen, greyed out, while
they wait. To show something else instead, pass ``waiting_screen``; to give
them something to do, such as filler trials, pass ``waiting_logic``
instead. A waiting screen can be text,
a prompt, or a :class:`~psynet.modular_page.ModularPage` without a Next
button (``NullControl(show_next_button=False)``), or a module-level
function of the participant that returns one of these, or ``None`` to keep
the last page. The participant can't submit a waiting screen, so a page
with a Next button, push buttons or ``auto_advance`` raises an error; use
a control that doesn't submit, such as ``NullControl``. Groupers and :func:`~psynet.page.wait_while` take ``waiting_screen`` too,
for example to replace the instructions while a cohort forms. A barrier
without a waiting screen (or one whose function returns ``None``) that
follows another barrier's waiting screen shows a plain waiting page, since
the last page is no longer on screen. In the following example, the barrier
is inside a trial's ``show_trial``, and the participant's own choice, read
from their current trial's answer so far, replaces the buttons they chose
it with.
``show_progress=False`` hides the answer ticks, which are of little use
in a pair, where the partner's arrival releases the barrier at once:

.. code-block:: python

    def your_choice(participant):
        return GroupPrompt(
            f"You offer {participant.current_trial.answer} coins.",
            participant=participant,
            group_type="pair",
            show_progress=False,
        )

    GroupBarrier(
        id_="decided",
        group_type="pair",
        waiting_message="Waiting for your partner…",
        waiting_screen=your_choice,
    )

.. _sync-showing-the-group:

Showing the group
~~~~~~~~~~~~~~~~~

:class:`~psynet.group_prompt.GroupPrompt` shows the members of a small group
by their pseudonyms (see :doc:`pseudonyms`), with the participant viewing the
page labelled "You". Each member appears as their pseudonym animal, drawn
in their colour. ``names`` decides how the other members are named: by
pseudonym, read out by screen readers and shown on hover (``"on_hover"``,
the default), also written below the animals (``"shown"``), or not by
pseudonym at all (``"anonymous"``), every member then being drawn as the
same grey figure, labelled below with "Your partner" in a pair and "Another
player" in a larger group.
Use ``"anonymous"`` when partners must not recognise each other across
rounds, with ``ChatRoom(names="anonymous")`` if the page has a chat room.
Members sit in a row for up to four people and in a zigzag across the
width of the page for more, so the display adapts to any screen.

``subgroups`` clusters the members, for example pairs formed within a
room. Pass a sync group type, or a function returning a key per participant;
the viewer's cluster comes first:

.. code-block:: python

    GroupPrompt("Pick a number.", participant=participant, group_type="room", subgroups="pair")

A page shows either progress or answers. On a decision page, members who
have answered get a tick. A member has answered once they wait at a barrier
of the group (:func:`~psynet.sync.is_waiting_at_barrier`), typically the barrier
after the decision page. A member who reached the barrier because their
page's time limit ran out gets a grey dash instead
(:func:`~psynet.sync.reached_barrier_after_time_limit`), and screen readers announce
that they ran out of time (see the :ref:`picture <rounds-variations>` in
:doc:`writing_a_round_based_experiment`). Pass ``show_progress=False`` to
hide the ticks, or ``has_answered`` to decide who gets a tick instead; it
can call :func:`~psynet.sync.is_waiting_at_barrier` to build on the default, and
members who ran out of time keep their dash whatever it returns.

What the page draws from the group's state updates live: ticks and dashes
appear as members arrive at the group's barriers (this uses the barriers'
arrival updates, so it needs ``notify_arrivals``), and members appear as
they join and fade as they leave (see below). Only what the server can't
work out again later is fixed when the page loads: who has answered by a
custom ``has_answered``, clusters from a ``subgroups`` function, and the
members shown with ``answers``. Live redraws need the same ``FLASK_SECRET_KEY`` on every web process; without
one, PsyNet logs a warning and the group stays as first drawn:

.. code-block:: python

    from psynet.group_prompt import GroupPrompt

    def choose_number(participant):
        return ModularPage(
            "choose",
            GroupPrompt("Pick a number.", participant=participant, group_type="room"),
            PushButtonControl(choices=[1, 2, 3, 4, 5]),
        )

After the barrier, pass ``answers`` to show each member's answer in a speech
bubble, as a dictionary from participant ID to answer; ``show_progress``
then defaults to ``False``, and passing ``show_progress=True`` or
``has_answered`` with ``answers`` raises an error. A member whose answer is
``None``, for example because they ran out of time, keeps their seat
without a bubble. Participant variables
store dictionary keys as strings, so a dictionary read back from one can be
passed as it is; ``highlight`` takes string IDs too. Speech bubbles may
overlap a neighbour; hovering over or tapping a member brings their bubble to
the front. Answers are shown as text; pass :class:`~markupsafe.Markup` for
HTML such as an image. ``highlight`` marks members, with built-in styles for
``"winner"`` and ``"duplicate"``, and ``note`` adds a line of text below
the group (hidden, like the group, when there is no group to show). In the
``show_feedback`` of a cued trial:

.. code-block:: python

    choices = self.node.var.choices
    GroupPrompt(
        "The winning number was 2.",
        participant=participant,
        group=self.sync_group,
        answers=choices,
        highlight={pid: "winner" for pid, n in choices.items() if n == 2},
    )

Store the answers when the barrier releases, as the ``lowest_unique_number``
demo does on the round's node in ``on_release``, rather than reading them
from the group's current members: a member who has already moved on to the
next round is no longer in the group, and would disappear if the page is
reloaded.

Without ``group``, the prompt shows the participant's group of type
``group_type``. ``group_type`` can be left out only while a participant has
only ever been in groups of one type; otherwise, as in a cohort that pairs
its players each round, GroupPrompt raises an error rather than switch to
whichever group is left when a pair ends.

GroupPrompt shows the group as it is now:

- A member who left stays in their seat, faded, with the first of these
  labels that applies:

  1. "(left)" if they failed;
  2. "(finished)" if they left after playing their part
     (``reason="finished"``), even if they then left or completed the
     experiment;
  3. "(left)" if they left or completed the experiment;
  4. "(removed)" if a barrier removed them from the group for being late;
  5. "(dropped out)" otherwise.

- A member who moved on to another group, such as next round's pair at a
  :class:`~psynet.sync.Regrouper`, is no longer shown, except on a results
  page (one with ``answers``) that shows their answer.
- A group that accepts top-ups shows no members who left, not even those
  who moved on and whose answer the page shows. Once it stops accepting
  them, members who left before then appear too, as in a team that lost
  someone during its instructions (see :ref:`sync-lobby-top-ups`).
- A participant who is no longer in the group, for example because a
  barrier removed them for being late, sees only the text when the prompt
  is given ``group_type``. The prompt then needs no special case on pages
  that such a player may still reach, though the page's other content, such
  as a round's outcome, may. ``group=self.sync_group`` in trial code is the
  group the trial was played in, which the prompt shows even after the
  player has left it.

:meth:`~psynet.sync.SyncGroup.remove_participant` takes a ``reason``
that sets these labels, such as ``"moved_on"`` or ``"late"``.

Trial makers
~~~~~~~~~~~~

A trial maker with ``sync_group_type`` gives the whole group the same trials.
Each group has a randomly chosen leader. PsyNet assigns the leader's next node
as if the leader were taking the trial maker alone, and the other members get
trials on the same node. The start of every trial is synchronized; add
:class:`~psynet.sync.GroupBarrier` elements inside the trial, as in
``show_trial`` above, to synchronize other points. Each trial records the
group, the member's role and the group's round, counted from 0, in
``sync_group_id``, ``sync_group_role`` and ``sync_group_round`` (see
:ref:`basic_data_groups`).

``sync_group_waiting_message`` sets the waiting message for the trial maker's own
waits. Grouper and barrier waits use their own ``waiting_message``, so pass the
same text to each if the messages should match.

Custom barriers
~~~~~~~~~~~~~~~

To release participants by another rule, subclass
:class:`~psynet.sync.Barrier` and implement
:meth:`~psynet.sync.Barrier.choose_who_to_release`, which returns the waiting
participants to release. Override
:meth:`~psynet.sync.Barrier.would_release` to match, and use
:meth:`~psynet.sync.Barrier.check_waiting_participants` for any preparation
with side effects.

Waiting and dropouts
--------------------

.. _sync-dropout-settings:

Settings for each kind of dropout
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:ref:`concept_groups` describes the ways participants leave a group and the
decisions each one needs. These settings carry them out:

- **Returning the study or being failed:** the grouper's ``below_quorum``
  decides for the members who stay (see `Groups below quorum`_).
- **Closing the tab or not responding:** a barrier's ``late_after`` and
  ``late_action`` act on the member who is late. Without ``late_after``, the
  barrier's ``max_wait_time`` and ``max_wait_action`` act on the members
  waiting for them (see `Timeouts`_).
- **Coming back after being removed:** see `After leaving a group`_ for what
  they see and what the rest of the timeline does with them.
- **Arriving when no group can form:** the grouper's ``max_wait_time``, with
  ``start_short_after`` to start a smaller group, or
  ``join_existing_groups`` to fill a gap in an existing one. Its
  ``max_wait_action`` fails those left over, or with
  ``"continue_without_group"`` lets them carry on (see `Timeouts`_).
- **Falling behind in rounds with a** :class:`~psynet.sync.Regrouper`: a
  player who isn't back by the split's deadline misses the round and joins
  the next (see `Rounds with changing groups`_). One who stops responding
  partway through a round is removed from their group by
  ``late_action="leave_group"``, but stays in the ``within`` group, so the
  next split waits for them until its deadline; ``late_action="leave_all_groups"``
  takes them out of both (see :ref:`rounds-slow-players`).

Test each kind your design can meet with bots (see :ref:`bots_that_drop_out`).

Timeouts
~~~~~~~~

A :class:`~psynet.sync.GroupBarrier` has two limits, the maximum waiting
time and the late limit, which act on different members; groupers have only
the maximum waiting time:

``max_wait_time``
    Acts on members **waiting** at this grouper or barrier: the longest each
    may wait, counted from their arrival. 20 seconds by default (see the
    table below for other defaults), or no limit
    at a :class:`~psynet.sync.GroupBarrier` that sets ``late_after``, which
    then handles late members instead; passing ``max_wait_time`` together
    with ``late_after`` raises an error. ``max_wait_action`` decides what
    happens to a participant who waits longer: ``"fail"`` (default) fails
    them. At a :class:`~psynet.sync.GroupBarrier`, ``"leave_group"`` removes
    them from the group (see :ref:`sync-leaving-a-group` for what they see
    next); at a grouper, where they have no group yet,
    ``"continue_without_group"`` lets them carry on without one, telling them
    "We couldn't find a partner for you in time. Please continue." (or "We
    couldn't form a group for you in time. Please continue." for larger
    groups). Either way it is
    the member who waited who leaves; to go on without slow members, use
    ``late_after`` instead.
    This also applies to a participant who closed the page while waiting,
    including on ``waiting_logic`` pages: the server applies the timeout
    shortly after the deadline.

    ``max_wait_time`` is a hard limit counted from arrival. With
    ``waiting_logic``, the server applies it even while the participant is
    partway through a filler page, not only between filler pages. Make it
    long enough to cover long filler pages, for example trials used as
    filler.

``late_after`` (default: ``None``)
    The late limit. Acts on members who **haven't reached** this
    :class:`~psynet.sync.GroupBarrier` yet: a member who hasn't reached the
    barrier within ``late_after`` seconds of the group's previous barrier
    pass, or of joining the group if that is later, is late, and is handled
    by ``late_action``: ``"fail"`` (default) fails them, ``"leave_group"``
    removes them from the group, and ``"leave_all_groups"`` removes them from
    all their groups, such as the cohort a pair was formed in. Members who arrive on time wait for the
    others until they arrive or are late, so they need no ``max_wait_time``
    of their own.

    A member who has started a page with a ``time_limit``, other than a
    waiting page, since the group last passed a barrier (or since joining)
    is not late until that limit has run out plus 10 seconds, so that an
    answer sent at the deadline can arrive. So the late limit need not be
    longer than the pages' time limits. See
    :ref:`a worked example <rounds-slow-players>`.

    At a group's first barrier the late limit counts from when each member
    joined the group, which for its original members is when it formed.
    Size it to cover everything between the grouper and that barrier, such as
    instructions or a practice trial, or members who read slowly are late
    before they arrive. Removing a late member from the group can also take
    the group below its ``quorum``, which can dissolve it and by default fail
    the members who arrived on time (see
    :ref:`groups below quorum <groups_below_min_size>`).

Trial makers with ``sync_group_type`` take the same settings with a
``sync_group_`` prefix: ``sync_group_max_wait_time``,
``sync_group_max_wait_action``, ``sync_group_late_after`` and
``sync_group_late_action``. ``sync_group_max_wait_time`` defaults to 45
seconds, or, as at a barrier, to no limit with ``sync_group_late_after``,
and passing both raises an error. Passing any of the others, or
``sync_group_waiting_message``, without ``sync_group_type`` also raises an
error; ``sync_group_max_wait_time`` only gives a warning then.

The default ``max_wait_time`` depends on where it is set:

.. list-table::
   :header-rows: 1

   * - Where
     - Default ``max_wait_time``
   * - :class:`~psynet.sync.SimpleGrouper` and other
       :class:`~psynet.sync.Grouper` subclasses
     - 20 seconds
   * - :class:`~psynet.sync.GroupBarrier`
     - 20 seconds, or no limit with ``late_after``
   * - Trial makers with ``sync_group_type``
       (``sync_group_max_wait_time``)
     - 45 seconds, or no limit with ``sync_group_late_after``
   * - :class:`~psynet.sync.Regrouper`
     - 300 seconds, or twice its ``deadline`` or ``every`` plus 60 seconds
       if that is longer

Choose ``max_wait_time`` at the grouper together with how quickly you
recruit, because a participant is failed (or, with
``max_wait_action="continue_without_group"``, continues without one) if too few
others arrive while they wait. To lose fewer than 1 in 20, expect at least 1.3 times the group
size to arrive within one ``max_wait_time``. For groups of three, that is
about 12 participants a minute with the default 20 seconds, or 2 a minute
with ``max_wait_time=120``. In one test with groups of three and about 3
arrivals a minute, the grouper failed 45% of participants with a 20-second
wait and none with 120 seconds. When recruitment stops, up to one fewer than
the group size are left without a group, and are failed unless the grouper
has ``max_wait_action="continue_without_group"``.

At later barriers, ``max_wait_time`` needs to cover how much longer some
members take over the previous page than others. A member who times out
there can take the group below its ``quorum``, with the consequences
described under :ref:`groups_below_min_size` below.

.. _groups_below_min_size:

Groups below quorum
~~~~~~~~~~~~~~~~~~~

Two separate settings decide what happens when someone leaves a group:

- **The member who leaves** is handled by why they left: a barrier's
  ``max_wait_action`` (they waited too long for the others) or
  ``late_action`` (the others waited too long for them), each ``"fail"``
  or ``"leave_group"``, or their own failure, for example when they return
  the study.
- **The members left behind** carry on as before while the group still has
  its ``quorum``. Below it, what happens depends on whether the group
  accepts top-ups:

  - While it accepts newcomers (``join_existing_groups=True``), it is never
    dissolved: its barriers wait for new members to join, until their
    ``max_wait_time``, or without a limit if the barrier sets
    ``late_after``. If every member leaves, the group closes at the next
    periodic sync-group check (every few seconds), and later arrivals form a
    new one. A ``join_criterion`` that returns ``False`` only turns that
    newcomer away; it doesn't stop top-ups.
  - Top-ups stop in three ways, and from then on the group is treated as
    one without top-ups:

    - ``group.stop_top_ups()`` stops them at once; a group already below
      its quorum is then dissolved, however its members left.
    - ``stop_top_ups=True`` on a :class:`~psynet.sync.GroupBarrier` stops
      them when the group passes that barrier, for example after the first
      round, once a newcomer could no longer catch up. A group below its
      quorum doesn't pass, so it keeps waiting there for a newcomer.
    - The grouper's ``top_up_wait=seconds`` limits that wait: once the
      group has been below its quorum that long, the barrier it is waiting
      at stops top-ups and dissolves it. This only helps members who are
      still waiting, so give that barrier a ``max_wait_time`` (20 seconds
      by default) longer than ``top_up_wait``, or ``late_after``, which
      removes the limit.
  - Without top-ups, the group is dissolved at once, and the grouper's
    ``below_quorum`` decides for each remaining member: ``"fail"`` (default)
    fails them, telling them "Too few members of your group remained to
    continue, so we ended your session."; ``"continue_without_group"``
    lets them carry on without the group, and their next page says "Your
    partner is no longer in your group. Please continue." (or "Too few
    members of your group remained. Please continue." in larger groups; see
    :ref:`sync-leaving-a-group`). A module-level function of
    ``participant`` and ``group`` that returns one of these decides member
    by member. A member who is in the middle of a request at that moment
    (for example submitting a page) is handled by the background barrier
    check within about a second instead, once that request finishes.
  - Members who leave with ``reason="finished"``, or who move on at a
    :class:`~psynet.sync.Regrouper` (``"moved_on"``), don't dissolve the
    group when they leave, unlike any other
    :meth:`~psynet.sync.SyncGroup.remove_participant` reason or a failure
    in a group without top-ups. Its next :class:`~psynet.sync.GroupBarrier` treats it like any
    group below quorum: it waits for a newcomer while the group accepts
    top-ups, and dissolves it otherwise, whatever the reason.
  - Groups made by a :class:`~psynet.sync.Regrouper` are never dissolved.

So in a :class:`~psynet.sync.SimpleGrouper` pair without top-ups, the two
settings together decide both fates:

.. list-table::
   :header-rows: 1

   * - The departing member
     - ``below_quorum="fail"`` (default)
     - ``below_quorum="continue_without_group"``
   * - quits or is failed (including by ``max_wait_action="fail"`` or
       ``late_action="fail"``)
     - partner failed
     - partner carries on alone
   * - waited too long, ``max_wait_action="leave_group"``
     - leaver carries on alone, absent partner failed
     - both carry on alone
   * - was late, ``late_action="leave_group"`` or ``"leave_all_groups"``
     - late member carries on alone, partner who was on time failed
     - both carry on alone

The last row is rarely what a pair wants, so PsyNet warns about it when the
experiment loads, and logs a warning when it happens. To let the partner who was on time carry on, set
``below_quorum="continue_without_group"``; ``late_action="fail"`` instead ends the
session for both. With ``late_action="leave_all_groups"`` the same applies to
the late member's other groups: a cohort without top-ups that one departure
takes below its quorum fails all its other members, including those in other
pairs, unless its grouper has ``below_quorum="continue_without_group"``. PsyNet
warns about this too.

For example, a group of four that may start with two after a minute, and
whose members carry on when others are slow or leave, combines these
options:

.. code-block:: python

    SimpleGrouper(
        group_type="team",
        initial_group_size=4,
        quorum=2,
        start_short_after=60,
        max_wait_time=120,
        # The last member left continues alone instead of being failed.
        below_quorum="continue_without_group",
    )

    # In each round, after the timed decision page:
    GroupBarrier(
        id_="round_finished",
        group_type="team",
        late_after=30,
        late_action="leave_group",
    )

The grouper leaves out ``join_existing_groups``, so a team that falls below
its quorum is dissolved rather than waiting for a replacement (see
`Groups below quorum`_).

The ``public_goods`` demo is a complete game built this way: groups of three
play on with two, and the last player left, like a participant for whom no
group forms, carries on without the group:

.. literalinclude:: ../../../demos/experiments/public_goods/experiment.py
   :start-at: SimpleGrouper(
   :end-before: Module(
   :dedent: 8

Each round is one trial per player, which ends at a barrier that removes late
players and scores the round for those who played it:

.. literalinclude:: ../../../demos/experiments/public_goods/experiment.py
   :pyobject: ContributionTrial.show_trial

The ``sync_quorum`` demo lets participants into part of the timeline only
while at least three are present. Its grouper has no maximum size and accepts
top-ups:

.. literalinclude:: ../../../demos/experiments/sync_quorum/experiment.py
   :start-at: SimpleGrouper(
   :end-before: for_loop(
   :dedent: 12

.. _sync-lobby-top-ups:

Letting latecomers join before the game starts
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

To let latecomers join a team only before its game starts, pass
``join_existing_groups=True`` to the team example's grouper and stop top-ups
at the barrier that starts the game. Latecomers can join until the team
passes that barrier, which it does once every member already in it has
reached it and it still has its quorum; passing ends top-ups. The barrier
waits for anyone who joined before then, for up to ``late_after`` after they
joined, before removing them as late, so the pages before it, such as
instructions, are the join window. ``top_up_wait`` stops a
team that falls below its quorum before then from waiting for a newcomer who
may never come; ``late_after`` also removes the barrier's default 20-second
wait limit, which would otherwise time the members out first:

.. code-block:: python

    SimpleGrouper(
        group_type="team",
        initial_group_size=4,
        quorum=2,
        start_short_after=60,
        max_wait_time=120,
        join_existing_groups=True,
        top_up_wait=60,
        below_quorum="continue_without_group",
    )
    InfoPage("Read the rules of the game...", time_estimate=60)
    GroupBarrier(
        id_="game_starts",
        group_type="team",
        stop_top_ups=True,
        late_after=120,
        late_action="leave_group",
    )

At ``game_starts``, as at ``round_finished`` above, ``late_after`` counts
from when each member joined the team or from its previous barrier pass, so
make it cover any untimed pages before the barrier as well.

.. _sync-leaving-a-group:

After leaving a group
~~~~~~~~~~~~~~~~~~~~~

A member removed from their group without being failed, through a
barrier's ``"leave_group"`` or ``below_quorum="continue_without_group"``,
stays in the experiment and continues the timeline without that group. They
leave only the group of that type: a player removed from a ``"pair"`` stays
in their ``"cohort"`` unless the experiment also removes them from it with
``remove_participant`` (see :ref:`rounds-slow-players`). A participant whose grouper let them continue without
a group (``max_wait_action="continue_without_group"``) is treated the same
way for that group type, as if they had left a group. A notice on their
progress bar tells them why. A member removed for being late sees "Your
group went on without you. Please continue." on the page they are on, until
they leave it, even if their leaving dissolved the group. The notices count the group as it was when they
left it: if only one other member was left by then, for example in a group
of three that had already lost someone, they read "Your partner went on
without you. Please continue." instead. Whatever they submit there is saved,
though the group has moved on, including into a participant variable
through ``save_answer``; only the response's ``too_late_for_group`` (see
below) marks it as late. An answer to a timed page usually arrives
after its time limit by then, so it is saved as ``None``. In other cases,
such as when their group was dissolved under them or they waited too long,
the notice appears on their next page.

Members who stay in the group get no notice when someone leaves; members
whose group ended under them are told on their next page. A
:class:`~psynet.group_prompt.GroupPrompt` marks the member who left, for
example "(dropped out)", unless the group still accepts top-ups (see
:ref:`sync-showing-the-group`), and the barriers stop waiting for them.

For the rest of the timeline:

- :class:`~psynet.sync.GroupBarrier`\ s of that group type let them straight
  through. Pages between the barriers are still shown, so give the steps of
  a round to :func:`~psynet.timeline.join` with ``stop_if``, which checks
  before each argument and skips the remaining arguments once the
  participant has left. Each argument runs to its end once started, so a
  page, barrier or cued trial is never cut short, and a trial is still
  scored and paid. To end a game's rounds, give the loop the same
  ``stop_if``: :func:`~psynet.timeline.for_loop` checks it before each
  iteration. Show something to the participants who left with a
  ``conditional`` afterwards, for example to answer a question alone if
  they never answered it with the group. Build each question's steps in a
  function, so that the lambda sees that question rather than the last one
  of a loop:

  .. code-block:: python

      def left_team(participant):
          return not participant.in_sync_group("team")

      def question_steps(question):
          return join(
              join(
                  estimate_page(question),
                  GroupBarrier(id_=f"estimates_{question}", group_type="team",
                               on_release=share_median),
                  revised_estimate_page(question),
                  stop_if=left_team,
              ),
              conditional(
                  f"alone_{question}",
                  left_team,
                  PageMaker(
                      lambda participant: (
                          estimate_page(question)
                          if participant.var.get(f"estimate_{question}") is None
                          else InfoPage("Your group has ended. Let's move on.")
                      ),
                      time_estimate=10,
                  ),
              ),
          )

  Put the grouper or :class:`~psynet.sync.Regrouper` that forms the group
  before the ``join``, not among its arguments: it would be skipped by
  everyone not yet in a group, at the start everyone and later anyone who sat
  out a round, who would then never be grouped again. When pairs change
  every round, use ``for_loop(..., logic=join(Regrouper(...),
  join(decision_page, round_barrier, outcome_page, stop_if=left_pair),
  conditional("sat_out", left_pair, sitting_out)))``, where ``sitting_out``
  is a page for anyone not in a pair by the end of the round: sat out by the
  regrouper, or removed partway for being late. Pass the steps themselves
  to the ``join``, not ``*`` the result of another ``join``, which is
  already a flat list of elements.

  In the ``public_goods`` demo, the rounds' loop stops once a player has left,
  and a ``conditional`` tells them, and a participant who never had a group,
  why the game ended. A trial added with
  :meth:`Trial.cue() <psynet.trial.main.Trial.cue>` runs to its end once
  started, so the last player still reaches the end of the round in which the
  group dissolves, where the trial is scored and paid:

  .. literalinclude:: ../../../demos/experiments/public_goods/experiment.py
     :start-at: Module(
     :end-at: PageMaker(game_over
     :dedent: 8
     :append: )

  .. literalinclude:: ../../../demos/experiments/public_goods/experiment.py
     :pyobject: game_ended_early

- Trial makers synchronized on that group type give them no more trials.
  A member who leaves before finishing any trial of such a trial maker,
  including one who is out of the group when it starts, skips the rest of
  it, with no ``on_complete`` or end-of-trial-maker performance check. A
  member who leaves after finishing some trials gets no more, then the trial
  maker finishes as usual: ``on_complete`` runs, and so does a performance
  check, over the trials they did.
- ``participant.in_sync_group("pair")`` is ``False``, while
  ``trial.sync_group`` still returns the group the trial was played in.
  ``participant.sync_group`` is ``None``
  if they are in no other group, is that group if they are in exactly one
  other, and raises if they are in several, so look groups up by type, as in
  ``participant.active_sync_groups.get("pair")``. A
  :class:`~psynet.chatroom.ChatRoom` whose ``room_id`` comes from the group
  needs another room, or none, then.
- ``participant.sync_group_removal_reason("pair")`` says why they left:
  ``"late"``, ``"waited_too_long"``, ``"no_group_formed"`` (a grouper found
  them no group in time), ``"group_dissolved"``, ``"moved_on"`` (a
  :class:`~psynet.sync.Regrouper` took them out of their previous group, and
  they are waiting there or sitting the round out),
  ``"finished"`` or ``"left_experiment"`` (they failed or returned the study).
- An answer submitted on the page where a member was removed for being late
  has ``response.too_late_for_group`` set, so analysis can leave it out.
- A :class:`~psynet.group_prompt.GroupPrompt` for that group type shows only
  its text from their next page on. A participant who has been in groups of
  several types needs ``group_type`` (or ``group``) on every ``GroupPrompt``.
- A later grouper of that type can put them in a new group. Two groupers
  with the same group type and settings get the same automatic ID and so
  share one waiting pool, which pairs those who left a group with newcomers
  still waiting at the first grouper. Pass the later grouper its own ``id_``
  if they should only be paired with each other.

Your own code blocks, pages and callbacks must handle this: check for
``None`` before using the group, and expect results, such as a score from
the group's last round, to be missing. If your experiment can't continue
meaningfully without a group, keep the default ``"fail"``.

Waiting pages
~~~~~~~~~~~~~

By default, a waiting participant stays on their current page, with input
disabled and a small waiting indicator showing ``waiting_message``. To show dedicated
pages instead, pass them as ``waiting_logic``; they repeat until the
participant is released. In ``sync_quorum``, waiting participants answer
trials from another trial maker:

.. literalinclude:: ../../../demos/experiments/sync_quorum/experiment.py
   :start-at: filler = PageMaker(
   :end-before: class Exp

``expected_wait`` says how long participants are expected to wait, in
seconds. With ``waiting_logic``, progress estimates assume the waiting pages
repeat often enough to fill that time, rounded up to whole passes; here,
``expected_wait=10 * AnimalTrial.time_estimate`` expects ten trials. Without
``expected_wait``, three passes are expected. The older
``waiting_logic_expected_repetitions`` argument is deprecated.

When the barrier releases a participant who is on a waiting page, the page
ends ``release_grace`` seconds (default 3; see
:class:`~psynet.sync.Barrier`) after the browser notices the release, which
is usually within about 2 seconds, unless they submit it first. The page's
answer is then not saved: its response is stored with ``"interrupted": True``
in ``metadata``, its ``on_complete`` doesn't run, and ``participant.answer``
keeps its previous value (``participant.answer_is_fresh`` is ``False``).
Any other waiting pages left in the same pass of ``waiting_logic`` are
skipped, and so are all of them for the participant whose arrival completes
the group. Pass ``release_grace=None`` to :class:`~psynet.sync.Barrier`,
:class:`~psynet.sync.GroupBarrier` or a grouper to let every waiting page
run to its end. Pages inside a trial, as in ``sync_quorum``, always run to
their end, so that the trial is not left without an answer.

During the grace period, the top of the page shows a countdown such as
"Your group is ready. Moving on in 3 s.", so the participant isn't
surprised when the page ends.

A waiting page's JavaScript can react to the release: ``window`` receives a
``psynetWaitingRelease`` event, with the grace period in ``detail.graceMs``,
and a ``psynetWaitingStatus`` event about every 2 seconds, with the time to
the expected release (or ``null``) in ``detail.releaseInMs``. Call
``preventDefault()`` on the release event to show your own notice instead
of the built-in one. This only replaces the notice: the page still ends
when the grace period is over.

.. code-block:: javascript

   window.addEventListener("psynetWaitingRelease", (event) => {
     event.preventDefault();
     document.getElementById("note").textContent =
       "Your partner is here. Finish your sentence!";
   });

Time credit
~~~~~~~~~~~

By default, participants are credited for the time they actually wait, up to
``max_wait_time``. Set ``fix_time_credit=True`` to credit every participant
``expected_wait`` seconds instead (1.5 seconds by default). With
``waiting_logic``, participants are credited for the waiting pages they
complete, by those pages' own time estimates; with ``fix_time_credit=True``,
they are credited for the expected passes instead.

.. seealso::

   The :doc:`/skills/synchronous-experiments` skill.
