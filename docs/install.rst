.. _installation:

Install
=======

You install a few tools once per computer. After that, each experiment gets
its own folder and its own Python environment, which :doc:`quickstart`
sets up.

You will install:

- `uv <https://docs.astral.sh/uv/>`_, which installs Python and manages each
  experiment's packages;
- Git, for version control;
- `Docker <https://www.docker.com/>`_, which runs the database and cache
  that PsyNet uses on your computer;
- Google Chrome, the browser PsyNet is tested with;
- the PostgreSQL client library (libpq), which PsyNet's database driver is
  built against;
- the Heroku command-line tool, which ``psynet test local`` currently uses to
  run its processes. You don't need a Heroku account, and this step will go
  away in a future release.

Choose your operating system:

.. tab-set::
   :sync-group: os

   .. tab-item:: macOS
      :sync: macos

      Install `Homebrew <https://brew.sh/>`_ if you don't have it:

      .. code-block:: bash

         /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

      Then install the tools:

      .. code-block:: bash

         brew install uv git libpq heroku/brew/heroku
         brew install --cask docker google-chrome
         echo 'export PATH="$(brew --prefix libpq)/bin:$PATH"' >> ~/.zshrc

      Open **Docker** from your Applications folder once, so that it starts
      running, then open a new terminal window. On Apple Silicon, turn on
      **Use Rosetta for x86/amd64 emulation** in Docker Desktop's settings;
      otherwise tests that run in Docker can be very slow.

      Finally, turn off AirPlay Receiver, which uses the same port as
      PsyNet: open **System Settings**, go to **General** then
      **AirDrop & Handoff**, and turn off **AirPlay Receiver**.

   .. tab-item:: Linux
      :sync: linux

      These steps are tested on Ubuntu 22.04 and 24.04.

      .. code-block:: bash

         sudo apt update
         sudo apt install git curl build-essential libpq-dev
         curl -LsSf https://astral.sh/uv/install.sh | sh
         curl https://cli-assets.heroku.com/install-ubuntu.sh | sh

      Open a new terminal so that ``uv`` is on your ``PATH``.

      Install Google Chrome:

      .. code-block:: bash

         wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
         sudo apt install ./google-chrome-stable_current_amd64.deb

      Install Docker Engine by following
      `Docker's instructions for Ubuntu <https://docs.docker.com/engine/install/ubuntu/>`_,
      then let your user run Docker without ``sudo``:

      .. code-block:: bash

         sudo usermod -aG docker $USER

      Log out and back in for this to take effect.

   .. tab-item:: Windows
      :sync: windows

      PsyNet runs on Windows through the Windows Subsystem for Linux (WSL),
      which gives you an Ubuntu terminal alongside Windows.

      1. Open **Command Prompt** and run ``wsl --install``. This installs WSL 2
         and Ubuntu. Restart your computer if asked.
      2. Open **Ubuntu** from the Start menu and choose a username and
         password.
      3. Install `Docker Desktop for Windows <https://docs.docker.com/desktop/setup/install/windows-install/>`_.
         In its settings, under **Resources** then **WSL integration**, turn
         on integration for Ubuntu.
      4. In the Ubuntu terminal, follow the **Linux** steps, but skip
         installing Docker Engine and the ``usermod`` step, because Docker
         Desktop provides Docker.

      Work in your Linux home folder (``cd ~``) rather than under
      ``/mnt/c``; it is much faster. If WSL won't install, see
      :doc:`/wsl_troubleshooting`.

.. toctree::
   :hidden:

   troubleshooting
   wsl_troubleshooting
