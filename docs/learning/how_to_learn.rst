.. _how_to_learn:

How to learn
============

.. note::

    See also the work-in-progress :doc:`Tracks <tracks/index>` section, which will provide learning programmes
    for various uses of PsyNet.

Before you start learning PsyNet there are a few general-purpose programming tools you should
familiarize yourself with, such as Python and Git; see :doc:`Prerequisites <prerequisites>`
for details.

Once you're happy with the prerequisites, the next thing you should do is skim a few
`example PsyNet experiments <../example_experiments/index.html>`_
to get a feel for the way that real-life experiments can be implemented using PsyNet.
A good starting point is the repository's ``experiment.py`` file, but it's worth exploring other `.py` files in the
repository too.

You should now spend some time reading about essential PsyNet principles. This online documentation website contains
lots of material here. Have a read through the `Tutorials <../tutorials/index.html>`_ section and see what catches your
eye. Some tutorials will not be relevant to you, depending on what kinds of experiments you're planning on running;
feel free to skip them.

Now you can start playing with PsyNet yourself. A good starting point is to start playing with some demos.
Start off by downloading the PsyNet repository to your local machine; I normally do this by going to a terminal
and typing the following:

.. code-block:: bash

   cd # Navigates to your home directory
   git clone git@gitlab.com:PsyNetDev/psynet

Open the resulting folder (``~/PsyNet``) in your IDE (we recommend VSCode or Cursor).
You can then navigate to the ``demos`` folder to see all the demos contained in PsyNet.
In your IDE's terminal, you can navigate to a particular demo you want to run like this:

.. code-block:: bash

   # The precise path will depend on where you downloaded PsyNet.
   cd ~/PsyNet/demos/experiments/timeline

Then you can run the demo using the standard PsyNet debug command:

.. code-block:: bash

   psynet debug local

You can try changing parts of the demo now to test your understanding of PsyNet, for example modifying the page
display, changing the stimuli, and so on. Note that some changes will manifest correctly as soon as you save your
code and refresh the page; others will only manifest when you start a new participant session via the dashboard;
others still will require you to start a new debug session by cancelling the debug command (Ctrl-C)
and running it again.

Once you are ready to develop your own experiment, you will want to move outside the PsyNet repository and create
your own repository. A good way to start is by copying an existing demo, or an existing experiment implementation,
to a new location on your computer. If you're going to use Git for version control, you can then initialize
a Git repository in this location and link it to a remote repository on GitHub or similar. Then you
can start changing code more wholesale.

Often you will only need to understand a particular subset of PsyNet's features for implementing a particular
experiment. Some of these features will be described in this website's `Tutorials <../tutorials/index.html>`_
section. Many of them will be illustrated in one or more of the PsyNet demos. It's worth having a look
through these demos to identify which of them provide relevant examples, and try to repurpose them for
your own experiment.

When writing specific bits of PsyNet code you will often need to consult lower-level documentation
for individual classes and functions. One way to do this is to search the class/function name in this
website's search box, or to look it up in the `API documentation <../api/index.html>`_ section.
Alternatively, most IDEs will let you right click on PsyNet classes/functions and follow the link to the
PsyNet source code, where you can see the documentation directly in the code. The latter approach is often
more powerful as it allows you to see the underlying code itself, which is often the best way of
understanding its functioning.

Learning PsyNet takes a while, but it pays off handsomely. Give it a few months, and you'll be implementing
fresh experiments in no time at all!
