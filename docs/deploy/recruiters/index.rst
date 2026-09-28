Choosing a recruiter
====================

A recruiter is the service that invites participants to your experiment
and pays them. Choose it before you finalize the experiment
configuration, because each has its own payment, consent, and
qualification requirements.

.. list-table::
   :header-rows: 1
   :widths: 16 28 28 28

   * -
     - Prolific
     - CINT (Lucid)
     - Lab Recruiter
   * - Participants
     - High-quality, diverse online pool; suits most academic studies
     - Large pool across many countries and languages; suits
       cross-cultural studies
     - Your lab's own participant pool
   * - Account
     - Your own or your lab's Prolific account
     - A CINT account, usually held by the lab
     - A Lab Recruiter instance run by your institution
   * - Payment
     - Through Prolific, with automatic bonuses and screen-out payments
     - EUR, set by ``get_lucid_settings()``; wage at the target country's
       minimum
     - According to your lab's payment policy
   * - Consent
     - Any consent page
     - ``LucidConsent`` required
     - Any consent page; the group's consent form is set in Lab Recruiter
   * - Recruiter setting
     - ``recruiter = prolific``
     - ``get_lucid_settings()``
     - ``recruiter = lab-recruiter``

For piloting without a recruitment platform, use ``recruiter = generic``
(see :doc:`/deploy/running_a_study`).

Configuration keys shared by all recruiters, such as ``wage_per_hour``,
``base_payment``, and ``initial_recruitment_size``, are listed in the
:doc:`configuration reference </reference/configuration>`. The spending
cap ``soft_max_experiment_payment`` is an experiment variable, not a
configuration key; see :doc:`/code/participants/payment_limits`.

.. toctree::
   :maxdepth: 2

   prolific
   cint
   lab_recruiter
