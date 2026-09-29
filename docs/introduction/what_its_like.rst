.. _what_its_like:

What's it like to use PsyNet?
=============================

Nowadays coding agents (e.g. ChatGPT, Cursor) make it straightforward to design
and run complex experiments in minutes. Your workflow might look something like
this:

.. rst-class:: study-step

1. Describe what you want
-------------------------

.. grid:: 1 1 2 2
   :gutter: 4

   .. grid-item::
      :columns: 12 12 4 4

      .. image:: /_static/images/what_its_like/describe.svg
         :alt: A chat between a researcher and a coding agent

   .. grid-item::
      :columns: 12 12 8 8

      You set up an experiment folder with ``psynet setup``, open it in your
      coding agent, and describe the study the way you would brief a
      research assistant, for example: 40 synthesized chords, each rated
      for pleasantness on a seven-point scale,
      about 20 ratings per chord, participants from Prolific. The agent
      asks a couple of questions, such as whether everyone should hear
      every chord, then proposes a plan before writing anything.

.. rst-class:: study-step

2. Build it
-----------

.. grid:: 1 1 2 2
   :gutter: 4

   .. grid-item::
      :columns: 12 12 4 4

      .. image:: /_static/images/what_its_like/build.svg
         :alt: A code editor with a small file tree

   .. grid-item::
      :columns: 12 12 8 8

      The agent writes the experiment, runs it, reads the errors and
      fixes them. A few minutes later you have a short folder of
      ordinary files, and ``experiment.py`` reads from top to bottom
      like the plan you agreed. Anything PsyNet doesn't provide, the agent
      writes in Python or JavaScript alongside it.

.. rst-class:: study-step

3. Try it yourself
------------------

.. grid:: 1 1 2 2
   :gutter: 4

   .. grid-item::
      :columns: 12 12 4 4

      .. raw:: html

         <img class="demo-phone study-step-phone" src="../_static/images/gallery/pipelines__simple_rating.png" alt="A rating page on a phone">

   .. grid-item::
      :columns: 12 12 8 8

      One command opens the experiment in your browser, and you take part as
      a participant would, on a laptop or a phone. When an instruction reads
      badly or a button sits in the wrong place, you tell the agent, and
      the change is there when you refresh.

.. rst-class:: study-step

4. Check it without anyone real
-------------------------------

.. grid:: 1 1 2 2
   :gutter: 4

   .. grid-item::
      :columns: 12 12 4 4

      .. image:: /_static/images/what_its_like/check.svg
         :alt: A checklist of passing checks next to a plot of practice data

   .. grid-item::
      :columns: 12 12 8 8

      The agent sends a crowd of simulated participants through the
      whole experiment and load-tests the server with many participants
      arriving at once. The simulated answers form a practice
      dataset, so you can write your analysis now. Everything is
      collected into an audit, a small website that you, or a
      supervisor, read before signing off.

.. rst-class:: study-step

5. Launch
---------

.. grid:: 1 1 2 2
   :gutter: 4

   .. grid-item::
      :columns: 12 12 4 4

      .. image:: /_static/images/what_its_like/launch.svg
         :alt: A terminal command that puts the experiment live

   .. grid-item::
      :columns: 12 12 8 8

      One command puts the experiment on your server and creates a draft
      study on Prolific, which you check and publish.

.. rst-class:: study-step

6. Watch it run
---------------

.. grid:: 1 1 2 2
   :gutter: 4

   .. grid-item::
      :columns: 12 12 4 4

      .. image:: /_static/images/what_its_like/watch.svg
         :alt: A dashboard showing participants arriving and progress toward the target

   .. grid-item::
      :columns: 12 12 8 8

      Participants start arriving within minutes. The dashboard shows who is
      part-way through, who has finished and what each has been paid. You add
      places on Prolific in batches while you watch the first data, or let
      PsyNet recruit automatically until every chord has its 20 ratings;
      ratings from participants who fail its checks don't count towards them.

.. rst-class:: study-step

7. Download the data
--------------------

.. grid:: 1 1 2 2
   :gutter: 4

   .. grid-item::
      :columns: 12 12 4 4

      .. image:: /_static/images/what_its_like/download.svg
         :alt: A data folder containing tables and files

   .. grid-item::
      :columns: 12 12 8 8

      When the last rating arrives, one command downloads everything, with
      a table for each kind of record. You run
      the analysis you wrote against the practice data, and take the server
      down.
