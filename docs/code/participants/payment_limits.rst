.. _payment_limits:

==============
Payment limits
==============

To increase robustness regarding payments, e.g. in the case of coding errors, two default payment limits exist in PsyNet:

* :attr:`~psynet.experiment.Experiment.var.max_participant_payment` which limits how much an individual participant can be paid, the default of which is $25.00, and

* :attr:`~psynet.experiment.Experiment.var.soft_max_experiment_payment` which sets a soft limit on how much the experiment can cost overall. Once :meth:`~psynet.experiment.Experiment.amount_spent` (recorded ``base_payment`` and delivered ``bonus``, including in-progress participants) exceeds the limit the recruiting process stops. It is a soft limit in the sense that the limit can still be exceeded to a certain extent. The default is $1000.00.

* :attr:`~psynet.experiment.Experiment.var.hard_max_experiment_payment` which sets a hard, absolute limit on the amount spent in an experiment. A bonus that would exceed this value is clipped to remaining room (or not paid if that remainder is below $0.01). ``planned_bonus`` stays the decided amount, delivered ``bonus`` is what was sent, and bonus status is `capped`. Additionally, the experimenter is notified about the issue. Default: `1100.0`.

These experiment-level limits use :meth:`~psynet.experiment.Experiment.amount_spent`, which already includes the study base payment reserved for participants who have started but not yet finished.

All limits are implemented as `class attributes` and can be overridden in the definition of the ``Experiment`` class of an experiment by assigning some ``float`` value, e.g.:

::

    class Exp(psynet.experiment.Experiment):
        variables = {
            "max_participant_payment": 10.0,
            "hard_max_experiment_payment": 550.0,
            "soft_max_experiment_payment": 500.0,
        }

Also, in all cases emails are sent out should the limit be exceeded notifying the user about the reduction of the payment for a participant or about the termination of the recruiting process.
