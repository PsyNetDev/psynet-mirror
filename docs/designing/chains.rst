.. _concept_chains:

Chains
======

In a chain experiment, participants' responses change what later participants
see. One participant retells a story and the next participant reads their
version; one participant adjusts a slider and the next starts from where they
left off. PsyNet uses chains for serial reproduction, cultural transmission,
adaptive procedures such as staircases, and sampling methods such as
Gibbs Sampling with People.

Chains use the same pieces as :doc:`trials`: a trial maker, nodes, and
trials, where each trial is one participant's visit to one node. The
difference is that in a chain the nodes change during the experiment.

How a chain grows
-----------------

A **chain** is a sequence of nodes. You write only the first node of each
chain, its **start node**. Participants visit the chain's current node,
exactly as in a static experiment: each visit is a trial that records their
answer.

Once the current node has received enough trials, PsyNet makes the next node
from those responses, and later participants visit that one instead. In a
chain, a node is therefore the chain's **current state**: the latest version
of the story, the current slider settings, the current difficulty level.

The heart of a chain design is the **rule for making the next node**. It
looks at the current node and the responses it received, and returns the
definition of the next node. For example:

- **serial reproduction**: the next story is the participant's retelling,
  unchanged;
- **several responses per node**: the next slider setting is the average of
  the participants' settings;
- **carrying information forward**: the next node keeps the original question
  and adds the new answer, so each node still knows what it is about;
- **adaptive procedures**: the next difficulty level goes up after a correct
  answer and down after a mistake.

Only responses that are complete, fully processed (for example, a recording
whose analysis has finished), and not failed are passed to the rule.

Within and across participants
------------------------------

- In **across-participant** chains, chains are shared by everyone. Each
  participant contributes to several chains, typically one node each, so a
  chain passes through many people. This is the usual design for cultural
  transmission.
- In **within-participant** chains, each participant gets chains of their
  own, created when they arrive, and works through them alone. This is the
  usual design for staircases and for studying an individual's biases.

Choosing the next chain
-----------------------

When a participant is ready for another trial, PsyNet looks for a chain they
can contribute to:

- the chain is not yet full and has not been failed (see below);
- in across-participant chains, the participant has not visited it before;
- the chain matches the participant's group, if you use participant groups.

If no chain is available, the participant moves on to the rest of the
timeline. You can ask PsyNet to make them wait instead when chains are only
temporarily busy, for example while a new node is being prepared. Chains can
also be balanced, so that new trials go to the chains with fewest responses.

Chain length and trials per node
--------------------------------

Two settings decide how much data a chain collects:

- **Trials per node**: how many responses a node needs before the next node
  is made. It is usually one; more than one lets each state combine several
  people's responses, for example by averaging.
- **Maximum nodes per chain**: how long the chain grows before it is full.

The number of chains and the number of trials per participant decide how many
participants you need. Recruitment can stop once enough participants have
finished, or once every chain is full.

Built-in paradigms
------------------

PsyNet includes ready-made chain designs, so you often only need to supply
the stimuli and the page:

- **Imitation chains**, where each participant reproduces what they heard or
  saw, including audio and video versions that record the participant;
- **Gibbs Sampling with People**, where participants adjust one dimension of
  a stimulus at a time to match a description;
- **Markov Chain Monte Carlo with People**, where participants choose between
  two stimuli;
- **Staircases**, which adjust difficulty according to performance;
- **Create and rate**, where some participants create stimuli and others
  rate them;
- **Graph chains**, where each node draws on several neighbors rather than a
  single predecessor.

When a trial fails
------------------

A failed trial stays in the data but is marked as unusable (see
:doc:`trials`). In a chain, it also does not contribute to the next node. Unlike static trial makers, chains keep a participant's completed trials
when the participant fails a performance check. Failing a trial that already
shaped later nodes can also invalidate everything downstream of it, which
could destroy much of a chain. See
:doc:`/guides/trials/participant_and_trial_failure` for the full rules.

Where the data goes
-------------------

Every node is exported with its definition and its position in the chain
(its **degree**: 0 for the start node, 1 for the next, and so on), and every
trial with the node it was made on. Following a chain from degree 0 upwards
shows how the state changed over the course of the experiment.

.. seealso::

   :doc:`in_code/chains` shows how each of these ideas appears in
   ``experiment.py``, using the ``demos/experiments/chain_trial_maker`` demo.
