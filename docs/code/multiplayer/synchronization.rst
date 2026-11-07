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

``min_group_size`` (default: ``initial_group_size``)
    A group with fewer active members is below quota and cannot pass a
    barrier; see `Waiting and dropouts`_.

``join_existing_groups`` (default: ``False``)
    If ``True``, an arriving participant first joins an existing group that
    is below ``max_group_size``, preferring the smallest and then the oldest
    group. Participants already waiting at the grouper join such a group on
    the next barrier check after one has room. Closed groups and groups with
    no active members are not joined. Groups formed with this option accept
    *top-ups*: when a member drops out, barriers wait for a replacement
    instead of dissolving the group.

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
    ``join_existing_groups=True``.

``start_short_after`` and ``start_short_with`` (default: ``None``)
    Seconds after which a smaller group may start, and the smallest group
    such a start may form; pass both or neither. Once the longest-waiting
    participant has waited ``start_short_after`` seconds and at least
    ``start_short_with`` are waiting, those waiting form a group even if
    there are fewer than ``batch_size``. Needs a ``max_wait_time`` (default
    20 seconds) longer than ``start_short_after``. A group started short uses
    the lower of ``min_group_size`` and ``start_short_with`` as its minimum
    size, so that it isn't dissolved at its first barrier. Combine it with
    ``join_existing_groups=True`` so that later arrivals can still fill the
    group up. A ``{SECONDS}`` placeholder in ``waiting_message`` counts down
    to that short start once ``start_short_with`` are waiting, and shows
    "…" until then; :ref:`a message function <sync-countdown-messages>` can
    show other text instead.

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
a grouper for longer than ``max_wait_time`` (default 20 seconds) is failed;
raise it if participants arrive slowly.

Accessing the group
~~~~~~~~~~~~~~~~~~~

Each group is a :class:`~psynet.sync.SyncGroup`. Inside a trial,
:attr:`Trial.sync_group <psynet.trial.main.Trial.sync_group>` returns the
group matching the trial maker's ``sync_group_type``. Elsewhere, use
``participant.sync_group`` if the participant is in one active group, or
``participant.active_sync_groups[group_type]`` if they are in several.

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
same ``group_type``. The ``simple_sync_group`` demo forms groups of three,
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
        release_left_over=True,  # an odd player out sits the round out
    )

By default, those who have played the most rounds sit out when not
everyone fits, players are kept apart from last round's partners where
possible, and roles alternate. The regrouper counts each participant's
rounds: :meth:`~psynet.sync.Regrouper.rounds_played`,
:meth:`~psynet.sync.Regrouper.rounds_sat_out`,
:meth:`~psynet.sync.Regrouper.sat_out` (for the latest round) and, with
``roles``, :meth:`~psynet.sync.Regrouper.role`.

:doc:`writing_a_round_based_experiment` builds a complete game this way, including moving
slow players on and sitting out. :class:`~psynet.sync.Regrouper` lists all
its settings, for example rounds on fixed ticks (``every``), fixed roles and
custom grouping.

``waiting_message`` sets the message on the waiting indicator. A ``{SECONDS}``
placeholder shows a live countdown to the deadline, for example ``"The next round starts in {SECONDS} s."``.
Only waits with a release time can count down: a regrouper with ``deadline``
or ``every``, and a :class:`~psynet.sync.SimpleGrouper` with
``start_short_after``. A ``{SECONDS}`` placeholder anywhere else raises an
error.

.. _sync-countdown-messages:

**Countdown messages.** Sometimes the barrier doesn't know yet when the
wait will end, for example while a participant waits alone for a partner,
and ``{SECONDS}`` shows "…". To show different text then, pass a
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
barrier after each choice scores the round:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors/experiment.py
   :pyobject: RockPaperScissorsTrial.show_trial

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors/experiment.py
   :pyobject: RockPaperScissorsTrial.score_trial

``on_release`` can take any of the arguments ``group``, ``participants``,
``leader`` and ``barrier`` (``participant`` is the leader too, kept for
compatibility). It must be a module-level
function, a static or class method, or a method bound to a trial maker or a
saved database object such as a trial. The ``barrier`` it receives is rebuilt
from saved settings, so read only scalar settings such as ``waiting_message`` and
``max_wait_time`` from it, and store custom barrier attributes as
JSON-compatible values.

The barrier ``id_`` identifies one waiting point. Barriers with the same ID
share a waiting pool, so give barriers with different ``on_release``
callbacks different IDs. Using one ID for barriers with different behavior
(class, ``on_release`` or release settings) raises an error when the
experiment is built.

Arrival notices
~~~~~~~~~~~~~~~

While a member waits at a barrier, members who have not reached it yet see a
notice on the progress bar ("Your partner is ready.", or
"{ARRIVED}/{TOTAL} of your group are ready."). In groups of three or more,
the waiting indicator also has a smaller second line saying how many members
are not ready yet. Set ``notify_arrivals=False`` to turn both off, or pass
``on_arrival_message`` to change the notices. It receives ``kind``
(``"notice"`` for the progress bar, ``"removed"`` for the notice a member
sees after being removed from the group), ``waiting_count`` and
``group_size``, and returns the text or ``None`` to hide it. For a notice it
is called whenever the browser fetches the current count, which can be
several times per arrival, so it should depend only on its arguments and
have no side effects. Notices must fit on one line:

.. code-block:: python

    def arrival_message(*, kind, waiting_count, group_size, **kwargs):
        if kind == "removed":
            return "Your partner went on without you. Please continue."
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
the last page is no longer on screen. In the following example, the
participant's own choice replaces the buttons they chose it with.
``show_progress=False`` hides the answer ticks, which are of little use
in a pair, where the partner's arrival releases the barrier at once:

.. code-block:: python

    def your_choice(participant):
        return GroupPrompt(
            f"You offer {participant.var.decision} coins.",
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

Showing the group
~~~~~~~~~~~~~~~~~

:class:`~psynet.group_prompt.GroupPrompt` shows the members of a small group
by their pseudonyms (see :doc:`pseudonyms`), with the participant viewing the
page labelled "You". Each member appears as their pseudonym animal, drawn
in their colour. ``names`` decides how the other members are named: by
pseudonym, read out by screen readers and shown on hover (``"on_hover"``,
the default), also written below the animals (``"shown"``), or not at all
(``"anonymous"``), every member then being drawn as the same grey figure,
labelled "Your partner" in a pair and "Another player" in a larger group.
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
            save_answer="choice",
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
the group (hidden, like the group, when there is no group to show):

.. code-block:: python

    result = participant.var.last_round
    choices = result["choice_by_player"]
    GroupPrompt(
        "The winning number was 2.",
        participant=participant,
        group_type="room",
        answers=choices,
        highlight={pid: "winner" for pid, n in choices.items() if n == 2},
    )

Store the answers when the barrier releases, as the ``lowest_unique_number``
demo does in ``on_release``, rather than reading them from the group's
current members: a member who has already moved on to the next round is no
longer in the group, and would disappear if the page is reloaded.

Without ``group``, the prompt shows the participant's group of type
``group_type``. ``group_type`` can be left out only while a participant has
only ever been in groups of one type; otherwise, as in a cohort that pairs
its players each round, GroupPrompt raises an error rather than switch to
whichever group is left when a pair ends.

GroupPrompt shows the group as it is now:

- A member who left stays in their seat, faded, with the reason:
  "(removed)" if a barrier removed them from the group for being late,
  "(left)" if they failed or left the experiment, and "(dropped out)"
  otherwise. Groups that accept top-ups don't keep these seats.
- A member who moved on to another group, such as next round's pair at a
  :class:`~psynet.sync.Regrouper`, is no longer shown, except on a results
  page (one with ``answers``) that shows their answer.
- A participant who is no longer in the group, for example because a
  barrier removed them for being late, sees only the text, as they do with
  ``group=self.sync_group`` in trial code (it is ``None`` after such a
  removal). The prompt needs no special case on pages that such a player
  may still reach, though the page's other content, such as a round's
  outcome, may.

:meth:`~psynet.sync.SyncGroup.remove_participant` takes a ``reason``
(``"moved_on"`` or ``"late"``) that sets these labels.

Trial makers
~~~~~~~~~~~~

A trial maker with ``sync_group_type`` gives the whole group the same trials.
Each group has a randomly chosen leader. PsyNet assigns the leader's next node
as if the leader were taking the trial maker alone, and the other members get
trials on the same node. The start of every trial is synchronized; add
:class:`~psynet.sync.GroupBarrier` elements inside the trial, as in
``show_trial`` above, to synchronize other points.

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

Timeouts
~~~~~~~~

A grouper or barrier has two limits, the maximum waiting time and the late
limit, which act on different members:

``max_wait_time``
    Acts on members **waiting** at this grouper or barrier: the longest each
    may wait, counted from their arrival. 20 seconds by default (see the
    table below for other defaults), or no limit
    at a :class:`~psynet.sync.GroupBarrier` that sets ``late_after``, which
    then handles late members instead; passing ``max_wait_time`` together
    with ``late_after`` raises an error. At a grouper, a participant who
    waits longer is failed. At a :class:`~psynet.sync.GroupBarrier`,
    ``max_wait_action`` decides: ``"fail"`` (default) fails the participant,
    and ``"kick"`` removes them from the group so that they continue alone,
    passing later group barriers of that type straight through.
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
    by ``late_action``: ``"fail"`` (default) fails them, and ``"kick"``
    removes them from the group. Members who arrive on time wait for the
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
    the group below ``min_group_size``; a group that doesn't accept top-ups is then dissolved,
    which by default fails the members who arrived on time (see
    :ref:`groups below minimum size <groups_below_min_size>`).

Trial makers with ``sync_group_type`` take the same settings with a
``sync_group_`` prefix: ``sync_group_max_wait_time``,
``sync_group_max_wait_action``, ``sync_group_late_after`` and
``sync_group_late_action``. ``sync_group_max_wait_time`` defaults to 45
seconds, or, as at a barrier, to no limit with ``sync_group_late_after``,
and passing both raises an error. Passing any of these options, or
``sync_group_waiting_message``, without ``sync_group_type`` also raises an
error.

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
recruit, because a participant is failed if too few others arrive while
they wait. To lose fewer than 1 in 20, expect at least 1.3 times the group
size to arrive within one ``max_wait_time``. For groups of three, that is
about 12 participants a minute with the default 20 seconds, or 2 a minute
with ``max_wait_time=120``. In one test with groups of three and about 3
arrivals a minute, the grouper failed 45% of participants with a 20-second
wait and none with 120 seconds. When recruitment stops, up to one fewer than
the group size are left without a group and are failed.

At later barriers, ``max_wait_time`` needs to cover how much longer some
members take over the previous page than others. A member who times out
there can take the group below ``min_group_size``, with the consequences
described under *Groups below minimum size* below.

.. _groups_below_min_size:

Groups below minimum size
~~~~~~~~~~~~~~~~~~~~~~~~~

When failed or departed members take a group below ``min_group_size``, what
happens depends on whether the group accepts top-ups:

- With ``join_existing_groups=True``, the group's next barrier waits for new
  members to join. If every member leaves, the group closes at the next
  periodic sync-group check (every few seconds), and later arrivals form a
  new one.
- Otherwise the group is dissolved as soon as the member leaves, and its
  remaining members are failed. Set ``fail_participants_below_min_size=False``
  on the grouper to remove them from the group without failing them, so that
  they continue alone. A member who is in the middle of a request at that
  moment (for example submitting a page) is handled by the background
  barrier check within about a second instead, once that request finishes.

The ``sync_quorum`` demo lets participants into part of the timeline only
while at least three are present. Its grouper has no maximum size and accepts
top-ups:

.. literalinclude:: ../../../demos/experiments/sync_quorum/experiment.py
   :start-at: SimpleGrouper(
   :end-before: for_loop(
   :dedent: 12

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
