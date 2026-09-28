Web servers
===========

PsyNet experiments currently support two main modes of deployment:

- SSH to a custom server
- Local computer

SSH to a custom server
----------------------

This is the preferred option in most cases.
The experimenter acquires some kind of Linux server to which they have SSH access,
perhaps by purchasing a physical server
that can be connected to the internet, or by acquiring a cloud server via a service
such as `Digital Ocean <https://www.digitalocean.com/>`_
or `Amazon Web Services <https://aws.amazon.com/>`_.
It's recommended to find a server with at least 16 GB of RAM.
There is then a built-in Dallinger command that connects to this server and
makes it ready for hosting experiments: ``dallinger docker-ssh servers add``.

Local computer
--------------

If you are collecting data in person it is also possible to run experiments on your local
machine, e.g. a laptop you bring to participants. We have not tested this workflow so much
and so would generally recommend the online server approach for now, though.
Watch this space!
