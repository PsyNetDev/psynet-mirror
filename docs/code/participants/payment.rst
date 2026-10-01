=======
Payment
=======

A participant's reward is the sum of a time reward and an optional
performance reward.
:meth:`~psynet.participant.Participant.calculate_reward` returns the reward
accumulated so far, in the currency set by the ``currency`` configuration key
(default ``$``).

Time reward
-----------

Every page and trial has a ``time_estimate`` in seconds. When a participant
completes part of the timeline, PsyNet adds its time estimate to their time
credit, and pays that credit at ``wage_per_hour`` (default ``9.0``). New
experiments set it in ``config.txt``:

.. code-block:: ini

    currency = £
    wage_per_hour = 12.0

A key can be set in ``config.txt`` or in the experiment class's ``config``
dictionary, but not both.

``psynet estimate`` reports the maximum time reward and the duration of the
longest route through the timeline:

.. code-block:: console

    psynet estimate

Performance reward
------------------

A performance reward can be allocated after each trial, at the end of a trial
maker, or both; the two add up.

:meth:`Trial.compute_performance_reward <psynet.trial.main.Trial.compute_performance_reward>`
runs after each trial. It receives the ``score`` returned by
:meth:`~psynet.trial.main.Trial.score_answer`. The ``static`` demo pays one
cent per point:

.. literalinclude:: ../../../demos/experiments/static/experiment.py
   :pyobject: AnimalTrial.compute_performance_reward

The trial maker's
:meth:`compute_performance_reward <psynet.trial.main.NetworkTrialMaker.compute_performance_reward>`
runs once at the end of the trial maker, after the final performance check.
It receives the check's ``score`` and ``passed`` values, and runs only if the
trial maker has ``check_performance_at_end=True``:

.. literalinclude:: ../../../demos/experiments/static/experiment.py
   :pyobject: AnimalTrialMaker.compute_performance_reward

Both methods return ``0.0`` by default. Code outside a trial maker can add to
the performance reward with
``participant.inc_performance_reward(amount)``.

Base payment and bonus
----------------------

The recruitment platform pays a fixed ``base_payment`` (default ``0.10``),
which you set in the configuration and which is advertised with the study.
When the participant finishes, the recruiter decides the payment and PsyNet
pays the rest as a bonus:

.. code-block:: text

    bonus = max(0, reward - base_payment)

A participant whose reward is at least the base payment receives exactly
their reward in total. A participant whose reward is below the base payment
still receives the full base payment and no bonus. Set ``base_payment`` at or
below the smallest reward you expect from a successful participant; for a
timeline without optional parts, that is the reward from
``psynet estimate``.

On Prolific, participants choose studies by the listed rate: ``base_payment``
for ``prolific_estimated_completion_minutes``. Bonuses aren't part of it, so
a low base payment makes a well-paid study look badly paid. When the recruiter
is Prolific, ``psynet estimate`` warns if the listed time is shorter than its
estimate, or if the listed rate is below ``wage_per_hour``.

To change how a recruiter computes the payment, subclass it and override
:meth:`~psynet.recruiters.PsyNetRecruiterMixin.decide_payment`,
:meth:`~psynet.recruiters.PsyNetRecruiterMixin.platform_base_for` or
:meth:`~psynet.recruiters.PsyNetRecruiterMixin.total_owed`.

Leaving early
-------------

Participants who fail a check, leave with the footer **Leave** button
(``show_early_exit_button``), or hit an error are paid for the parts they
completed. Paid Leave is offered only once their reward reaches
``min_reward_for_paid_early_exit`` (default ``0.20``). How the payment is
split depends on the recruiter:

- **Prolific** pays a fixed screen-out amount
  (``prolific_unsuccessful_base_payment``, default ``0.25``), and PsyNet tops
  the participant up to their reward with a bonus. With
  ``prolific_unsuccessful_topup = false``, the time reward is forfeited and
  the participant receives only the screen-out amount plus any performance
  reward. With ``prolific_pay_unsuccessful = false``, the participant is
  asked to return the submission instead, and their whole reward is paid as
  a bonus. See :doc:`/deploy/recruiters/prolific`.
- **CINT** (Lucid) pays participants through the panel; PsyNet pays no base
  payment or bonus. See :doc:`/deploy/recruiters/cint`.
- **Lab Recruiter** receives the outcome from PsyNet, and payment follows the
  lab's payment process. See :doc:`/deploy/recruiters/lab_recruiter`.

Payment limits
--------------

Three limits protect the budget. They are experiment variables, not
configuration keys:

``max_participant_payment`` (default ``25.0``)
    The most one participant can receive, base payment included. A bonus that
    would exceed it is reduced to the remaining amount.

``soft_max_experiment_payment`` (default ``1000.0``)
    Recruitment stops once
    :meth:`~psynet.experiment.Experiment.amount_spent` reaches this value.
    Participants already in the experiment can still finish and be paid, so
    the total can go past this limit.

``hard_max_experiment_payment`` (default ``1100.0``)
    No bonus is paid beyond this total. A bonus that would exceed it is
    reduced to the remaining amount, or not paid if less than 0.01 remains,
    and the participant's bonus status is recorded as ``capped``. The
    participant's ``planned_bonus`` keeps the amount decided before the cap,
    and ``bonus`` records what was paid.

:meth:`~psynet.experiment.Experiment.amount_spent` adds up the base payments
and bonuses of all participants, including the base payment reserved for
participants who have started but not finished. When a limit is reached,
PsyNet emails the experimenter.

Set the initial values in the ``variables`` dictionary of the experiment
class:

.. code-block:: python

    class Exp(psynet.experiment.Experiment):
        variables = {
            "max_participant_payment": 10.0,
            "soft_max_experiment_payment": 500.0,
            "hard_max_experiment_payment": 550.0,
        }

While the experiment runs, the soft and hard experiment limits can be changed
on the dashboard's **Monitor > Timeline** page.
