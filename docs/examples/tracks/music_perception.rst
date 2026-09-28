======================
Music perception track
======================

The music perception track is tailored towards people who want to run online behavioral studies
about how people perceive music.

The first step is to :doc:`install PsyNet </install>`.
Also install PsyNet and Dallinger in editable mode, following
:ref:`additional_developer_installation`, so that you have the demos locally.

Next you should read the
:doc:`introduction to the demos section </examples/demos/introduction>`,
and then explore the first two demos,
:doc:`Hello world </examples/demos/hello_world>`,
and :doc:`Timeline </examples/demos/timeline>`.
These demos introduce you to the basics of PsyNet experiments.
You should approach each demo in the following way:

- Copy and paste the demo from the PsyNet source code location into another location on your computer.
- Open the demo as a new project in your IDE.
- Run the demo following the standard approach (``psynet debug local``).
- Read the source code in the demo and relate it to the behavior of the demo.
- Try making some changes to the demo and see how they change the experiment. Note that minor changes will be
  reflected if you just save the code and refresh the page, but major changes (e.g. adding pages) may require
  you to restart the experiment (hit CTRL-C to stop the experiment, then rerun the original command to relaunch it).

Now read the following pages:

- :doc:`Classes in PsyNet </code/project/classes_and_sqlalchemy>`
- :doc:`Timeline </design/timeline>`
- :doc:`Modular pages </code/pages/modular_page>`

Take the :doc:`timeline exercise </examples/exercises/timeline>`.

Explore the :doc:`audio demo </examples/demos/audio>`, then take the :doc:`JSSynth exercises </examples/exercises/js_synth>`.

Explore the following trial demos:

- :doc:`Trial (1) </examples/demos/trial>`
- :doc:`Trial (2) </examples/demos/trial_2>`
- :doc:`Trial (3) </examples/demos/trial_3>`
- :doc:`Audio trial maker </examples/demos/static_audio>`
