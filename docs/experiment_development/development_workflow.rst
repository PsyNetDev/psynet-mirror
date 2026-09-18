.. _development_workflow:

Development workflow
====================

Let's imagine we are working on a particular experiment implementation.
Perhaps we initialized our implementation by copying a demo from the PsyNet ``demos`` directory,
and have been converting the code to our needs.
This tutorial will cover various tips and tricks for making your development process
efficient and effective.


Version control
^^^^^^^^^^^^^^^

It's important to have some system for tracking changes to your code over time.
We recommend using Git alongside some Git host such as GitHub or GitLab.
There are lots of good Git tutorials available online;
see `version control with Git <../tutorials/version_control_with_git.html>`_
for a PsyNet-oriented introduction to Git.


IDE Setup
^^^^^^^^^

Interactive development environments (IDE)
help you to manage and run your source files. We recommend using **VSCode** or **Cursor** for PsyNet development.
Both are free and work well with PsyNet.

**PyCharm** is also supported as an alternative IDE, but note that PyCharm remote debugging is currently not working (as of February 2025).
If you choose to use PyCharm, you will need to configure it yourself; we do not provide detailed setup instructions as they may become outdated.

Setting up your IDE generally involves two steps.
First, you should open the experiment directory as a project in your IDE.
Second, you should configure your Python interpreter.
This should involve creating a virtual environment for your project (typically installed in the ``.venv`` directory),
and then install the experiment's dependencies into this virtual environment.
This list of dependencies is stored in the ``requirements.txt`` and ``constraints.txt`` files.

PsyNet supports Python 3.11 through 3.14 and recommends Python 3.13 for
experiment development.

To create the environment and install the dependencies, run the following in your terminal:

.. code-block:: bash

    uv venv  # you can specify a particular Python version if you want, e.g. uv venv --python 3.13
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate
    uv pip install psynet
    psynet setup

``psynet setup`` scaffolds any missing boilerplate, reuses ``constraints.txt``
when it is already up to date with ``requirements.txt`` (otherwise regenerates
it), and synchronizes the environment with ``uv pip sync``.

.. note::

    If you haven't got uv installed, you can install it by running ``pip install uv``.

Once setup has completed, you should be able to use ``psynet`` commands in your terminal.
See `Command line <../introduction/command_line.html>`_ for an overview of PsyNet commands.


Local debug mode
^^^^^^^^^^^^^^^^

The most important PsyNet command for local development is the following:

.. code:: bash

    psynet debug local

This ``psynet debug local`` command creates a local development server that you can use
to prototype your experiment. This server recreates all the services (web nodes, worker nodes,
clock nodes, database) that would be running in a real experiment.

The local development server should take about 10-15 seconds to spin up.
Once it has spun up, you should see in your console a link to the experiment dashboard.
Open that link in Chrome and you should see the dashboard. On the default dashboard page
you will see a button that allows you to create a new participant session.
Click that link and you can take the experiment.

Though the development server takes a while to spin up, it has the special feature
that you can preview edits to your code without having to restart the server from scratch.
For example, you can change the UI components of a given PsyNet page, save the source file,
then refresh the page in Chrome; the server processes should refresh and you should see
the changes to your page. You can likewise add new components to the timeline, change
code block logic, and so on; changes should be manifested immediately once you refresh
the page.

Certain changes need a full refresh of the development server to propagate. For example,
if you are making changes to assets included in the timeline, you will normally need
to close the debug session and create a new one for those assets to be incorporated
into the experiment. You can close a debug session by entering Ctrl-C into the bash terminal.


Breakpoints
^^^^^^^^^^^

Breakpoints are an essential tool for debugging experiments. They allow you to drop into
the Python environment at a particular point in your code, inspect local variables,
and try executing arbitrary code.

Setting breakpoints in PsyNet is a little bit more complicated that setting breakpoints
in simple Python scripts. This is because PsyNet makes heavy use of subprocesses,
which cannot easily be accessed using standard IDE breakpoints.
Nonetheless, with a little of extra work, we can achieve the same functionality.

For debugging, we recommend using the ``psynet.debugger()`` function,
which works with VSCode and Cursor. This is documented below:

.. autofunction:: psynet.debugger

.. note::

    If the above options don't work for you, you can fall back to a simpler option,
    the rpdb package (https://pypi.org/project/rpdb/).
    To use this with a virtual environment, you need first to install it with ``pip install rpdb``.
    To insert a breakpoint, you put the following code in your Python script:

    .. code:: python

        import rpdb; rpdb.set_trace()

    To start a debug server, you then run the following code in your terminal:

    .. code:: bash

        nc 127.0.0.1 4444

    As before, when the breakpoint is encountered, you will then be able to interact with the local
    Python process via your debug server terminal. This allows you to, for example, view the state
    of local variables and execute custom code. Using rpdb requires more expertise because of the lack
    of a user interface; for instructions you can see the general instructions for pdb (the non-remote version)
    available here: https://docs.python.org/3/library/pdb.html#debugger-commands


Debugging tips
^^^^^^^^^^^^^^

Everyone runs into errors and bugs when they are programming. This is part of the normal process.
Your ability to efficiently resolve errors and bugs is an essential part of being an effective programmer.

PsyNet experiments take some care to debug because there are many moving parts. It can be intimidating at
first working out how to resolve problems.

Most errors and bugs have their first symptom in an error message that is printed to your bash console.
This error message will typically contain a traceback that tells you where in the code the error occurred.
Examine this carefully to work out where the error is being flagged. It might be in the code you wrote,
or it might be in the PsyNet library code. If the latter, you may want to find the corresponding part of the
PsyNet source code so you can get a better idea of the logical context of the error.

Often you can learn more about the origin of the error by inserting a breakpoint at the point just before
the error occurs. With this breakpoint, you can explore the local state of the environment, and work
out if a particular variable is taking an unexpected value, or a particular function is returning an unexpected output.

If an error is particularly hard to isolate, one trick is to progressively simplify your implementation to find
a minimal code example that still produces the error. The simpler the implementation, the less there is to understand,
and the clearer the bug will become. A minimal code example can be very good for sharing with others so that
they can help you to understand what's going on. A useful trick here can be to simply 'comment out' bits of your
experiment timeline. There is a useful PyCharm shortcut for this, CMD-/.


Dashboard
^^^^^^^^^

The PsyNet dashboard provides various useful tools for understanding the state of your experiment.
You should explore this as you develop your experiment. In particular the database tab is helpful
for showing you the state of the current database objects; this is complemented by the monitor tab,
which visualizes network structures in the experiment.


Tests
^^^^^

PsyNet experiments now come with built-in tests. These tests help you to validate that your experiment logic
works correctly. They focus on the back-end Python logic, rather than the front-end user interface;
however it is perfectly possible to write your own front-end tests too.

The PsyNet experiment's tests are defined in the experiment directory's ``test.py`` file.
The built-in test simply runs a simulated participant (a 'bot') through your experiment.
The way this works is that each PsyNet page comes with a ``bot_response`` attribute that determines
how the bot responds to the page. Many pages come with default ``bot_response`` attributes;
for example, by default a bot will respond to a multiple-choice page by clicking a random option.
This behavior is fully customizable, and you can pass arbitraily complex functions to this ``bot_response`` attribute.

PsyNet provides several hooks for customizing these built-in experiment tests.
These hooks are accessed by customizing your ``Experiment`` class in ``experiment.py``.

The simplest customization is to change ``Experiment.test_n_bots``, which determines the number of bots that are run through
the experiment. By default this is set to 1.

Another common customization is to override ``Experiment.test_check_bot`` and add additional code that validates
the state of the bot once it has completed the experiment. For example, you might check that it has completed
a certain number of trials, or that a certain participant variable has been set effectievly.

For more complete customization, you can override ``Experiment.test_experiment`` itself, and have complete control
over the initialization of bots and the checking of their status.

To run the experiment's tests, you can enter the following into your bash terminal:

.. code:: bash

    psynet test local

.. warning::

    **PyCharm users**:

    At the time of writing (June 2024) there is a bug in PyCharm's test result parser
    that causes full tracebacks to be omitted from test results in some cases.
    To fix this problem we recommend editing your PyCharm's pytest run configurations to include
    the additional argument ``--tb=short``. To do this, click Run > Edit Configurations >
    Edit configuration templates > Python tests > pytest, and then insert ``--tb=short``
    under Additional Arguments. Then press OK, then remove any existing pytest configurations for your
    current project by pressing the minus symbol in the top left. Future tests should then run
    automatically using this option.


Local PsyNet and Dallinger installations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Writing PsyNet experiments often involves customizing underlying library code. This is part of the real power of
PsyNet: you can dig as deep as you want into the library classes and functions.

To take advantage of this capacity, you will normally want to have PsyNet (and perhaps also Dallinger)
source code libraries easily available on your computer. The recommended way to do this is to clone their
Git repositories into your home directory. Make sure to preserve the original capitalization of the repository
directory names, for example ``~/PsyNet`` and ``~/Dallinger``.
You can then open these libraries in your IDE and browse them when you are developing your experiment.

Sometimes you will want to trial particular changes to PsyNet or Dallinger library code. This can be useful for
debugging errors that occur within this code, or for proposing new features that you eventually contribute to
PsyNet or Dallinger. In order to test such changes, you need to link your local source libraries to your experiment
implementation.

.. code:: bash

    cd ~/PsyNet
    pip3 install -e .

    cd ~/Dallinger
    pip3 install -e .

Now you can make changes to the PsyNet/Dallinger repositories
and immediately see the impact of your changes in your experiment code.

You might well decide to contribute your changes back to the PsyNet/Dallinger repositories.
This is a great way to help improve the libraries for everyone.
To do this, you can fork the PsyNet/Dallinger repositories on GitHub/GitLab,
make your changes, and then submit a pull request.
Your pull request will be reviewed by the PsyNet/Dallinger maintainers,
and if accepted, your changes will be merged into the main repositories.

.. note::

    Forking is only required for people who are not members of the PsyNet/Dallinger repositories.
    Members can instead create branches on the main repository and submit pull requests from there.

However, you might not want to wait for your changes to be merged into the main repositories
before using them in your experiment.
To deploy an experiment using a custom PsyNet or Dallinger branch, you need to open ``requirements.txt``
and change the PsyNet/Dallinger dependency to point to your fork.
For example, if you are using a custom PsyNet branch, you would change the dependency to something like this:

.. code:: text

    psynet@git+https://gitlab.com/PsyNetDev/PsyNet@your-branch-name#egg=psynet

After making this change, you will need to run ``psynet generate-constraints`` to update the ``constraints.txt`` file
(see :ref:`dependencies` for more details).
