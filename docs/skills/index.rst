Skills
======

PsyNet's **Agent Skills** describe recommended workflows for PsyNet users:
how to implement an experiment, simulate participants, plan a design
simulation, prepare a deployment, and more. They are written mainly for
coding agents, which follow them step by step, and they also work as
checklists for people. The documentation describes what PsyNet provides;
the skills describe how to use it well, and each one starts by listing the
documentation pages it relies on.

``psynet setup`` and ``psynet scripts update`` install the skills into the
experiment's ``.cursor/skills/psynet/`` folder. PsyNet manages that folder, so
edit the canonical skills in the PsyNet repository at
``.cursor/skills/experiment/`` rather than the copies in an experiment; skills
elsewhere in ``.cursor/skills/`` belong to the experiment and are left alone.
In Cursor, agents pick skills up automatically from their descriptions, and you
can run one directly by typing ``/`` and its name, for example
``/implement-experiment``. Other agents can be pointed at the skill's
``SKILL.md`` file.

.. toctree::
   :hidden:
   :glob:

   *

.. list-table::
   :header-rows: 1
   :widths: 28 44 28

   * - Skill
     - Use it to
     - Main PsyNet documentation
   * - **Planning and building**
     -
     -
   * - :doc:`implement-experiment`
     - Turn a natural-language description into a planned, built, tested and
       audited experiment. It calls the other skills as needed.
     - :doc:`/code/project/agentic_programming`
   * - :doc:`explore-psynet-repository`
     - Find the closest demo and the relevant PsyNet source.
     - :doc:`/code/project/creating_an_experiment`
   * - :doc:`develop-experiment-back-end`
     - Write the timeline, trial makers and experiment logic.
     - :doc:`/code/writing_a_timeline`, :doc:`/code/writing_a_trial_maker`
   * - :doc:`develop-experiment-front-end`
     - Build participant-facing pages, controls and custom prompts.
     - :doc:`/code/writing_pages`
   * - :doc:`make-experiment-adaptive`
     - Make later trials depend on earlier responses.
     - :doc:`/code/writing_a_trial_maker`, :doc:`/design/chains`
   * - :doc:`synchronous-experiments`
     - Group participants and keep them in step with barriers.
     - :doc:`/code/multiplayer/synchronization`
   * - :doc:`realtime-synchronous-experiments`
     - Build live interactions between participants over websockets.
     - :doc:`/code/multiplayer/realtime_interaction`
   * - :doc:`psychophysics`
     - Get precise visual displays, timing, responses and reaction times.
     - :doc:`/code/pages/graphics`, :doc:`/code/pages/event_management`
   * - :doc:`tapping-experiments`
     - Build tapping and sensorimotor synchronization experiments.
     - :doc:`/code/participants/prescreening_and_questionnaires`
   * - :doc:`filter-participants`
     - Add pre-screening that matches the recruiter's own filters.
     - :doc:`/code/participants/prescreening_and_questionnaires`
   * - :doc:`prepare-for-translation`
     - Mark participant-facing text for translation and check it.
     - :doc:`/code/participants/internationalization`
   * - :doc:`participant-quality-telemetry`
     - Record signals of participant quality and AI assistance.
     - :doc:`/design/participants`
   * - :doc:`turn-pure-experiment-to-ai-hybrid`
     - Let AI participants take part alongside, or instead of, humans.
     - :doc:`/design/participants`
   * - :doc:`verify-ai-model-usability`
     - Check that the AI models an experiment relies on are reachable.
     - :doc:`/reference/configuration`
   * - :doc:`upgrade-to-psynet-14`
     - Move an existing experiment through the PsyNet 14 breaking changes.
     - :doc:`/whats_new/upgrading_to_psynet_14`
   * - **Testing and auditing**
     -
     -
   * - :doc:`simulate-participants`
     - Write bots that take the experiment, for tests and practice data.
     - :doc:`/test/backend`
   * - :doc:`participant-response-models`
     - Model how participants respond, for simulations.
     - :doc:`/test/audits`
   * - :doc:`power-analysis`
     - Choose participant, stimulus and trial counts before collecting data.
     - :doc:`/test/audits`
   * - :doc:`precision-estimation`
     - Run the default simulation method for ``power-analysis``.
     - :doc:`/test/audits`
   * - :doc:`playwright-testing`
     - Write browser tests and layout checks for participant pages.
     - :doc:`/test/frontend`
   * - :doc:`record-participant-video`
     - Capture screenshots and a video of a participant's session.
     - :doc:`/test/frontend`
   * - :doc:`produce-experiment-audit`
     - Assemble and validate the experiment's audit.
     - :doc:`/test/audits`
   * - **Deploying and data**
     -
     -
   * - :doc:`prepare-for-cint`
     - Make an experiment ready for recruitment through Cint.
     - :doc:`/deploy/recruiters/cint`
   * - :doc:`deploy-experiment`
     - Check deployment readiness and run deployments safely.
     - :doc:`/deploy/running_a_study`
   * - :doc:`monitor-experiment`
     - Watch a running study's participant flow and data.
     - :doc:`/deploy/running_a_study`
   * - :doc:`basic-data`
     - Define the experiment's basic data for analysis.
     - :doc:`/data/basic_data`
   * - :doc:`basic-data-dyadic-experiment`
     - Flatten data from two-participant experiments for analysis.
     - :doc:`/data/basic_data`
   * - **Previewing**
     -
     -
   * - :doc:`public-tunnel`
     - Share a running local experiment, or any local service, through a
       temporary public link.
     - :doc:`/code/project/running_and_debugging`
