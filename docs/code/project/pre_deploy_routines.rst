.. _pre_deploy_routines:

===================
Pre-deploy routines
===================

The idea behind :class:`~psynet.timeline.PreDeployRoutine` is to allow for the definition of tasks to be performed
before deployment and the start of the experiment.
PreDeployRoutines can be added (in any number) at any point in the experiment's timeline.
Below we give an example of a PreDeployRoutines that performs a configuration task on an Amazon S3 bucket.

::

  from psynet.media import prepare_s3_bucket_for_presigned_urls
  from psynet.timeline import PreDeployRoutine

  PreDeployRoutine(
      "prepare_s3_bucket_for_presigned_urls",
      prepare_s3_bucket_for_presigned_urls,
      {"bucket_name": "recordings_s3_bucket", "public_read": True, "create_new_bucket": True}
  )

The :class:`~psynet.timeline.PreDeployRoutine` expects three arguments:
A ``label`` describing the pre-deployment task,
the ``function`` to be executed,
and lastly the ``arguments`` of the function to be executed.
This function will then be run automatically as part of experiment launch.

Note: If you alter the database state during a PreDeployRoutine then this change will be propagated to the
deployed experiment. It can be useful for performing database setup tasks, therefore.
