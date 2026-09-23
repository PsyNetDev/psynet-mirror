.. _shell_completion:

PsyNet shell completion
=======================

This page explains how to enable shell tab completion for the ``psynet`` command.
It provides automatic completion for commands, subcommands, and options.

Files
-----

- ``.psynet-completion.bash`` – bash completion script (installed in ``~/.local/bin/``)
- ``.psynet-completion.zsh`` – zsh completion script (installed in ``~/.local/bin/``)

.. note::

   Completion files are generated dynamically during installation.

Installation
------------

Installation using the PsyNet command (recommended)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   psynet install autocomplete

.. note::

   This method works for both editable and non-editable PsyNet installations. It will automatically detect your shell,
   generate the appropriate completion files, and add the appropriate setup to your shell configuration file.

Installation using the installation script
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Run the installation script from the root of the PsyNet directory:

.. code-block:: bash

   ./psynet/resources/scripts/install-completion.sh

.. note::

   This method *only* works for editable PsyNet installations. It will automatically detect your shell,
   generate the appropriate completion files, and add them to your shell configuration file.

Activate completion
-------------------

After installation, either restart your terminal or source the completion file directly:

.. code-block:: bash

   source ~/.local/bin/.psynet-completion.bash  # for bash
   source ~/.local/bin/.psynet-completion.zsh   # for zsh

Usage
-----

Basic command completion
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   psynet <TAB>

This shows all available commands like e.g. ``debug``, ``deploy``, ``estimate``, etc.

Subcommand completion
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   psynet debug <TAB>

Shows available subcommands, e.g. ``local``, ``ssh``, etc.

Option completion
^^^^^^^^^^^^^^^^^

.. code-block:: bash

   psynet debug local --<TAB>

Shows available options for the specific command, e.g. ``--docker``, ``--archive``, etc.

Partial completion
^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   psynet d<TAB>

Completes to ``psynet debug`` (or shows other commands starting with ``d``).

Examples
--------

.. code-block:: bash

   # Complete to debug command
   psynet d<TAB>  # → psynet debug

   # Complete to debug local
   psynet debug l<TAB>  # → psynet debug local

   # Complete to debug local with docker option
   psynet debug local --d<TAB>  # → psynet debug local --docker

   # Complete to deploy ssh with app
   psynet deploy s<TAB>  # → psynet deploy ssh
   psynet deploy ssh --a<TAB>  # → psynet deploy ssh --app

   # Complete to lucid commands
   psynet lucid <TAB>  # shows all lucid subcommands

   # Complete to lucid estimate with options
   psynet lucid estimate --l<TAB>  # → psynet lucid estimate --language-code

Troubleshooting
---------------

If completion doesn't work:

1. Make sure the completion script is properly sourced.
2. Try restarting your terminal.
3. Verify that the completion files exist:

   .. code-block:: bash

      ls -la ~/.local/bin/.psynet-completion.*

4. Verify the ``~/.local/bin/`` directory exists and is in your ``PATH``.
5. Verify that ``psynet`` is in your ``PATH``: ``which psynet``.
6. Check that your shell configuration file (``~/.bashrc`` or ``~/.zshrc``) contains the completion source line.
7. If you need to fix the shell configuration, add the following to your shell configuration file:

   .. code-block:: bash

      source ~/.local/bin/.psynet-completion.bash  # for bash
      source ~/.local/bin/.psynet-completion.zsh   # for zsh
