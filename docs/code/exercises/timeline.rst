=================
Timeline exercise
=================

Prerequisites
^^^^^^^^^^^^^

- :doc:`/design/timeline`
- :doc:`/code/writing_a_timeline`

Exercise
^^^^^^^^

Design a timeline that uses PsyNet's control-flow features to simulate
buying items in a shop. You are the shop assistant. Offer the customer a
choice of items, ask how many of the chosen item they want, and add them to
their virtual basket. Then ask whether they want anything else, and loop
until they say they are done. The basket should accumulate every item. At
the end, tell the customer how much they need to pay.

**Tips**:

- Start from a copy of ``demos/features/timeline``, made outside the PsyNet
  repository as described in :doc:`/code/project/creating_an_experiment`.
  Keep and adapt the parts you need, and delete the rest.
- Concentrate on the control logic rather than the appearance.
- Participant variables hold the basket: set them with
  ``participant.var.set()`` and read them with ``participant.var.xxx``. The
  timeline demo uses both.
- :doc:`/code/project/running_and_debugging` explains how to debug the
  experiment as you build it.
