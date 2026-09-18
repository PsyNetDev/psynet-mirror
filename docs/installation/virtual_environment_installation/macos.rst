Installing PsyNet in a virtual environment (macOS)
==================================================

One-time setup
--------------

The following steps need to performed each time you setup a new computer
to run PsyNet experiments.

Check MacOS version
~~~~~~~~~~~~~~~~~~~

We recommend that you update MacOS to the latest version before proceeding.

Install Python
~~~~~~~~~~~~~~

PsyNet supports Python 3.11 through 3.14. Python 3.13 is the recommended version
for developing and deploying experiments.
To see the current version of Python 3 on your system, enter ``python3 --version`` in your terminal.
If your current version is lower than the minimum version, you should update your Python
to the recommended version.
We recommend doing this by going to the `Python website <https://www.python.org/downloads/>`_,
and downloading the installer corresponding to the latest patch of the recommended version.
For the recommended version, this means searching for Python version 3.13.x where
'x' is as high as possible.
At the time of writing this installer can be found by looking under the section
'Looking for a specific release?', clicking the desired Python version, then clicking
'macOS 64-bit universal2 installer'.

One installation is complete, try ``python3 --version`` again to ensure
that the correct version is found. To install old versions you might need to run ``brew uninstall python3``,
or go to the Applications folder and delete the appropriate version of Python.

Install uv
~~~~~~~~~~

.. code-block:: bash

   pip3 install uv

Install Homebrew
~~~~~~~~~~~~~~~~

.. code-block:: bash

   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

Install Google Chrome
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   brew install --cask google-chrome

Install and setup PostgreSQL
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   brew install postgresql@14
   brew services start postgresql@14
   createuser -P dallinger --createdb

When prompted, enter the follwing password: *dallinger*

.. code-block:: bash

   createdb -O dallinger dallinger
   createdb -O dallinger dallinger-import

   brew services restart postgresql@14

Install libpq
~~~~~~~~~~~~~

.. code-block:: bash

   brew install libpq

In the ensuing text, you should see something like this:

.. code-block:: bash

   For compilers to find libpq you may need to set:
     export LDFLAGS="-L/usr/local/opt/libpq/lib"
     export CPPFLAGS="-I/usr/local/opt/libpq/include"

Execute the following:

.. code-block:: bash

   touch ~/.zshrc
   open ~/.zshrc

Then paste those two lines beginning with "export" at the bottom of the file (as new lines).

.. warning::

   If you skip this step you might see error messages like "symbol not found in flat namespace '_PQbackendPID'"
   once you try and run PsyNet.

Install Heroku
~~~~~~~~~~~~~~

.. code-block:: bash

   brew install heroku/brew/heroku

Install Redis
~~~~~~~~~~~~~

.. code-block:: bash

   brew install redis
   brew services start redis

Install gettext
~~~~~~~~~~~~~~~

.. code-block:: bash

   brew install gettext

Gettext provides translation utilities (``xgettext``, ``msgfmt``) required for managing translations in PsyNet experiments.

Setup Git
~~~~~~~~~

If you don't have Git already, install it with the following commands,
inserting your name and email address as appropriate.

.. code-block:: bash

   brew install git
   git config --global user.email "you@example.com"
   git config --global user.name "Your Name"

.. include:: note_about_virtual_environments.rst

.. include:: ../download_psynet.rst

Disable AirPlay
~~~~~~~~~~~~~~~

macOS's 'AirPlay Receiver' functionality clashes with the default ports used by Dallinger and PsyNet.
You should disable this functionality before proceeding. To achieve this, go to System Preferences, then Sharing,
and then untick the box labeled 'Airplay Receiver'.

If you are interested in contributing to PsyNet, you should also complete
the :ref:`additional_developer_installation`.


Setting up a new project
------------------------

The following steps need to be performed each time you start a new project.

.. include:: ../identifying_a_project.rst

.. include:: opening_a_project_in_a_virtual_environment.rst
