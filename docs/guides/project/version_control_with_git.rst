.. _developer:
.. highlight:: shell

.. |br| raw:: html

   <br />

.. _Version control with Git:

Version control with Git
========================

The collaborative development of PsyNet is underpinned by the version control system ‘Git’. Git is also used by the majority of open-source software projects across the world. It is a rather complex tool and can be legendarily frustrating for first-time users. However its functionality is indispensable in enabling multiple programmers to work on the same code-base simultaneously, each making their own modifications and feature implementations in their own workspaces, and progressively feeding the results into the common codebase.

.. figure:: ../../_static/images/version_control_with_git/xkcd_git.png
  :width: 300
  :align: center

  Credit: XKCD, `Creative Commons Attribution-NonCommercial 2.5 License <https://creativecommons.org/licenses/by-nc/2.5/>`_.

You will have probably installed Git already as part of the PsyNet installation process. If not, you can install it with the following command. Assuming you’re using a Mac, and assuming you’ve already installed `Homebrew <https://brew.sh/>`_:

.. code-block:: console

    brew install git

Git is a command-line tool. This means you work with it by entering text into the command-line (on Mac, this is the Terminal) application.

.. figure:: ../../_static/images/version_control_with_git/git_version.gif
  :width: 500
  :align: center

|br|
You use Git by writing various Git commands. Git commands always begin with the word ‘git’. For example:

.. code-block:: console

    git add README.txt
    git commit -m "Added a README file"
    git push

In the rest of this tutorial we’ll try to develop an understanding of the essential Git commands and how they are used when working with a software project. We’ll begin with an overview of essential concepts in Git, and will then move onto Git’s command-line syntax.

.. toctree::
   :maxdepth: 2
   :glob:

   version_control_with_git/essential_concepts
   version_control_with_git/experiment_implementation_workflow
