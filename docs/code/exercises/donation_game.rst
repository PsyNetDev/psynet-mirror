======================
Donation game exercise
======================

Prerequisites
^^^^^^^^^^^^^

- :doc:`/code/writing_a_timeline`
- :doc:`/code/project/classes_and_sqlalchemy`

Exercise
^^^^^^^^

Design an experiment where each participant starts with a random number of
dollars, stored in the participant variable ``dollars``. Write a
:func:`~psynet.timeline.while_loop` in the timeline containing a page that
shows one push button (:class:`~psynet.modular_page.PushButtonControl`) for
each participant in the study, labeled with that participant's ID and current
dollar amount. Pushing a button donates $1 to that participant. Can you
generalize these mechanics to make an interesting behavioral economics game?

**Tasks:**

- Make the button choices correspond to the participants who are actually in
  the database.

  - Query for participants with ``Participant.query``.
  - The page depends on the database at the moment the participant reaches
    it, so build it inside a :class:`~psynet.timeline.PageMaker`.
  - Use participant IDs as ``choices`` and put the display text, including
    each participant's current money, in ``labels``. Avoid unusual symbols in
    ``choices``.

- When a button is clicked, transfer the money.

  - Take $1 from the current participant and give it to the chosen
    participant.
  - Put this logic in a :class:`~psynet.timeline.CodeBlock` after the page.
    The page's answer is available there as ``participant.answer``.
