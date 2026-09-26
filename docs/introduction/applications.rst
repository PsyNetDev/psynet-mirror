.. _applications:

What's PsyNet for?
==================

PsyNet runs behavioral experiments in the web browser, online or in the lab.
It's built for studies that are hard to run in survey tools or static
experiment builders: large or generated stimulus sets, procedures that adapt
as data come in, chains where one participant's response becomes the next
participant's stimulus, recordings analyzed as they arrive, and experiments
where participants interact.

Each card below describes one kind of experiment. Click through the
screenshots to see the demos, and follow the docs link to the page that
explains the idea.


.. card:: Rating large stimulus sets
   :class-card: sd-mb-4 sd-shadow-sm
   :class-title: sd-fs-5

   .. grid:: 1 1 2 2
      :gutter: 4

      .. grid-item::
         :columns: 12 12 4 4

         .. demo-carousel::

            pipelines/simple_rating
            pipelines/similarity

      .. grid-item::
         :columns: 12 12 8 8

         Participants rate or compare sounds, images or videos, each seeing a different subset of a stimulus set that can run to thousands of items.

         **PsyNet handles:** spreading ratings evenly across stimuli, serving media files, and screening out inattentive participants.

         **Docs:** :doc:`/designing/trials`

         **Research:** :ref:`papers <research-rating>`


.. card:: Adaptive procedures
   :class-card: sd-mb-4 sd-shadow-sm
   :class-title: sd-fs-5

   .. grid:: 1 1 2 2
      :gutter: 4

      .. grid-item::
         :columns: 12 12 4 4

         .. demo-carousel::

            experiments/staircase_pitch_discrimination
            features/trial_cue_adaptive

      .. grid-item::
         :columns: 12 12 8 8

         Each trial is chosen based on the participant's earlier answers, for example making a discrimination task harder after correct responses.

         **PsyNet handles:** running the adaptive logic on the server between trials, and recording each decision alongside the responses.

         **Docs:** :doc:`/designing/chains`

         **Research:** :ref:`papers <research-adaptive>`


.. card:: Sampling with people
   :class-card: sd-mb-4 sd-shadow-sm
   :class-title: sd-fs-5

   .. grid:: 1 1 2 2
      :gutter: 4

      .. grid-item::
         :columns: 12 12 4 4

         .. demo-carousel::

            experiments/gibbs
            experiments/gibbs_image
            experiments/mcmcp

      .. grid-item::
         :columns: 12 12 8 8

         Participants adjust a slider or choose between two stimuli, and each answer moves a shared chain towards the stimulus that best fits a description, such as "happy" or "beautiful".

         **PsyNet handles:** Gibbs sampling and Markov chain Monte Carlo with people, including synthesizing each new stimulus.

         **Docs:** :doc:`/designing/chains`

         **Research:** :ref:`papers <research-sampling>`


.. card:: Chains and cultural transmission
   :class-card: sd-mb-4 sd-shadow-sm
   :class-title: sd-fs-5

   .. grid:: 1 1 2 2
      :gutter: 4

      .. grid-item::
         :columns: 12 12 4 4

         .. demo-carousel::

            experiments/chain_trial_maker
            experiments/imitation_chain
            experiments/tapping_iterated

      .. grid-item::
         :columns: 12 12 8 8

         Participants reproduce what the previous participant produced: a story, a melody or a rhythm. Over many generations, the chains reveal the biases people bring to memory and perception.

         **PsyNet handles:** assigning participants to chains, creating each new stimulus from the previous response, and keeping every chain's history in the export.

         **Docs:** :doc:`/designing/chains`

         **Research:** :ref:`papers <research-chains>`


.. card:: Recording and production
   :class-card: sd-mb-4 sd-shadow-sm
   :class-title: sd-fs-5

   .. grid:: 1 1 2 2
      :gutter: 4

      .. grid-item::
         :columns: 12 12 4 4

         .. demo-carousel::

            pipelines/tapping
            experiments/vertical_processing

      .. grid-item::
         :columns: 12 12 8 8

         Participants sing, speak or tap into their microphone or camera. The recording is analyzed as soon as it arrives, so the result can drive feedback, scoring or the next stimulus.

         **PsyNet handles:** capturing and uploading recordings, running your analysis on the server, and exporting the files with the data.

         **Docs:** :doc:`/designing/stimuli`

         **Research:** :ref:`papers <research-recording>`


.. card:: Create and rate
   :class-card: sd-mb-4 sd-shadow-sm
   :class-title: sd-fs-5

   .. grid:: 1 1 2 2
      :gutter: 4

      .. grid-item::
         :columns: 12 12 4 4

         .. demo-carousel::

            experiments/create_and_rate

      .. grid-item::
         :columns: 12 12 8 8

         Some participants create stimuli, such as recordings or descriptions, and others rate them or pick the best. The winners can seed the next round of creation.

         **PsyNet handles:** matching creators with raters, collecting enough ratings per creation, and passing the selected creations on.

         **Docs:** :doc:`/guides/trials/create_and_rate`

         **Research:** :ref:`papers <research-create-and-rate>`


.. card:: Groups and interaction
   :class-card: sd-mb-4 sd-shadow-sm
   :class-title: sd-fs-5

   .. grid:: 1 1 2 2
      :gutter: 4

      .. grid-item::
         :columns: 12 12 4 4

         .. demo-carousel::

            experiments/chatroom_simple
            experiments/rock_paper_scissors
            experiments/unity_autoplay

      .. grid-item::
         :columns: 12 12 8 8

         Participants join the same session and interact in real time, by chatting, playing a game, or waiting for each other before moving on together.

         **PsyNet handles:** forming groups as participants arrive, keeping them in step, and passing messages between their browsers.

         **Docs:** :doc:`/guides/multiplayer/index`


.. card:: Across languages and countries
   :class-card: sd-mb-4 sd-shadow-sm
   :class-title: sd-fs-5

   .. grid:: 1 1 2 2
      :gutter: 4

      .. grid-item::
         :columns: 12 12 4 4

         .. demo-carousel::

            experiments/translation
            experiments/language_tests

      .. grid-item::
         :columns: 12 12 8 8

         Participants take the same experiment in their own language, recruited from many countries at once.

         **PsyNet handles:** translating participant-facing text, checking language proficiency, and recruiting through international panels.

         **Docs:** :doc:`/guides/participants/internationalization`

         **Research:** :ref:`papers <research-languages>`


When PsyNet isn't the right tool
--------------------------------

- A fixed questionnaire with no adaptive logic is quicker to build in a
  survey platform.
- Tasks that need millisecond-precise timing from dedicated hardware belong
  in lab software.
- PsyNet has no visual experiment builder: experiments are written as
  Python code, although a coding agent can write much of that code from a
  description.
