Installing PsyNet in a virtual environment (Windows)
====================================================

Installing PsyNet on a Windows machine depends on the “Windows Subsystem for Linux” (WSL).
All code you run using your the installation needs to be run within the Linux subsystem.

Step 0: Install WSL
^^^^^^^^^^^^^^^^^^^

.. include:: ../wsl_installation.rst

Once you've installed WSL, you probably will need to restart your computer before continuing.
If you need to reopen Ubuntu later, you can run ``wsl -d Ubuntu`` from Command Prompt or PowerShell.
Then open your Ubuntu terminal and follow the below instructions.
We recommend working from your Linux home directory (``cd ~``) rather than ``/mnt/c`` to avoid
permission and performance issues when cloning repositories or creating virtual environments.

.. note::

   If you create a virtual environment manually (i.e., using ``python -m venv``),
   use the specific Python version you installed (for example ``python3.12 -m venv .venv``)
   to avoid accidental version mismatches.

Step 1: Perform Linux  installation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. include:: linux_dev_installation.rst

Optional: install an IDE
^^^^^^^^^^^^^^^^^^^^^^^^
You can develop on Windows (for example, PyCharm on Windows using a WSL interpreter),
or install a Linux IDE inside WSL. If you want to install PyCharm inside WSL and have
systemd enabled, you can run:

.. code-block:: bash

   sudo snap install pycharm-educational --classic

You can then launch it with ``pycharm-educational``.

Troubleshooting
^^^^^^^^^^^^^^^

.. include:: ../wsl_troubleshooting.rst
