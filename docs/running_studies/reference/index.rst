Deployment reference
====================

This section is the reference for deployment targets, server setup, data
export, monitoring tools, and troubleshooting. If you are looking for a
step-by-step lab workflow around these pieces, including recruiter
setup, piloting, monitoring participants, and teardown, see the
:doc:`Lab research workflow </running_studies/workflow/index>`.

.. warning::

   ``deploy.toml`` planning currently requires a POSIX filesystem and is not
   supported on Windows.

.. toctree::
   :maxdepth: 1

   web_servers
   aws_automatic_provisioning
   aws_server_setup
   physical_server_setup
   ssh_server
   deploy_from_archive
   deploy_tokens
   data
   deployment_monitor
   setting_up_slack
   errors
   troubleshooting
