Glossary
========

.. glossary::
   :sorted:

   Archive
      A saved copy of an experiment's database. Redeploying from an
      archive continues data collection with an existing experiment; see
      :doc:`/running_studies/reference/deploy_from_archive`.

   Auto-recruit
      A recruitment mode that invites a new participant each time one
      finishes, keeping the number of active participants roughly
      constant at :term:`initial_recruitment_size`. You can toggle it from
      the experiment dashboard; switch it off before ending a study.

   Docker
      Container software that runs an experiment in a fixed environment.
      Some deployment routes build and pull Docker images from a registry.

   Experiment hosting
      The server that runs your experiment during data collection: either
      a server you manage yourself or an EC2 server provisioned on AWS.
      See :doc:`/running_studies/reference/web_servers`.

   Hotair
      A recruiter that recruits nobody and prints a participant link
      instead. Use it for pilot runs you share with colleagues before
      recruiting real participants.

   initial_recruitment_size
      The experiment setting that controls how many participants are
      invited when recruitment starts. Avoid inviting more participants
      than your server can handle.

   Launch
      Deploying an experiment with ``psynet deploy ssh`` using a live
      recruiter, so that real participants are invited.

   Provisioning
      Setting up a server to host experiments, typically an EC2 server;
      see :doc:`/running_studies/reference/aws_automatic_provisioning`.

   Recruiter
      The service that invites and pays participants, optionally
      filtering them by demographic requirements. Examples include
      Prolific, CINT (formerly Lucid), and Lab Recruiter.

   Remote debug
      Running ``psynet debug ssh`` against a server to test an experiment
      in its deployment environment. Unlike a launch, it does not recruit
      real participants.

   Teardown
      Shutting down a server once data collection is finished, typically
      terminating an EC2 instance so it stops incurring costs.
