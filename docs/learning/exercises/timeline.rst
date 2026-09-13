=================
Timeline exercise
=================

Prerequisites
^^^^^^^^^^^^^

- :doc:`Timeline tutorial </tutorials/timeline>`

Exercise
^^^^^^^^

In this exercise you will design your own timeline that takes advantage of various control features in PsyNet. Here’s
the proposal: make a timeline that simulates the experience of going to the shop and buying some items. In particular,
imagine you’re a shop assistant asking the customer what they want. You give them a choice of items, you ask the
customer how many items they want, and add these items to their virtual basket. You then loop round, asking them if they
want to choose any more items, and so on. These items should all accumulate in the basket. Once the participant says
they’re done, tell them how much they need to pay.

**Tips**:

- You can work by modifying the original timeline demo, keeping and modifying bits you want, deleting bits you don’t
  want, and so on. Before you start working on it, though, make sure you copy the original demo to a new location
  outside the experiment's source code.
- Don’t worry so much about the appearance side, for now we are interested primarily in the control logic.
- The notion of setting participant variables (e.g. ``participant.var.set()``) and getting participant variables
  (``participant.var.xxx``) will be very useful here. Have a look at the original timeline demo to get a feel for these.
- Have a look at :doc:`/experiment_development/development_workflow` for tips on how to debug your experiment
  as you are designing it.
