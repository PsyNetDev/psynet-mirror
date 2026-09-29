Agent skills
============

PsyNet ships **Agent Skills**: instructions that tell a coding agent how to
carry out common PsyNet tasks, such as implementing an experiment, simulating
participants or preparing a deployment. ``psynet setup`` and
``psynet scripts update`` install them into the experiment's
``.cursor/skills/psynet/`` folder. PsyNet manages that folder, so edit the
canonical skills in the PsyNet repository rather than the copies in an
experiment; skills elsewhere in ``.cursor/skills/`` belong to the experiment
and are left alone.

In Cursor, agents pick skills up automatically from their descriptions, and
you can run one directly by typing ``/`` and its name, for example
``/implement-experiment``. Other agents can be pointed at the skill's
``SKILL.md`` file.

Skills describe *how* to do a task. The facts they rely on live in this
documentation: each skill starts by telling the agent which pages to read,
and the table below lists the main one for each skill.

.. list-table::
   :header-rows: 1
   :widths: 28 44 28

   * - Skill
     - Use it to
     - Main documentation
   * - **Planning and building**
     -
     -
   * - ``implement-experiment``
     - Turn a natural-language description into a planned, built, tested and
       audited experiment. It calls the other skills as needed.
     - :doc:`agentic_programming`
   * - ``explore-psynet-repository``
     - Find the closest demo and the relevant PsyNet source.
     - :doc:`creating_an_experiment`
   * - ``develop-experiment-back-end``
     - Write the timeline, trial makers and experiment logic.
     - :doc:`/code/writing_a_timeline`, :doc:`/code/writing_a_trial_maker`
   * - ``develop-experiment-front-end``
     - Build participant-facing pages, controls and custom prompts.
     - :doc:`/code/writing_pages`
   * - ``make-experiment-adaptive``
     - Make later trials depend on earlier responses.
     - :doc:`/design/adaptive_experiments`, :doc:`/code/adaptive_experiments`
   * - ``synchronous-experiments``
     - Group participants and keep them in step with barriers.
     - :doc:`/code/multiplayer/synchronization`
   * - ``realtime-synchronous-experiments``
     - Build live interactions between participants over websockets.
     - :doc:`/code/multiplayer/realtime_interaction`
   * - ``psychophysics``
     - Get precise visual displays, timing and responses.
     - :doc:`/code/pages/graphics`
   * - ``tapping-experiments``
     - Build tapping and sensorimotor synchronization experiments.
     - :doc:`/code/writing_a_trial_maker`
   * - ``filter-participants``
     - Add pre-screening that matches the recruiter's own filters.
     - :doc:`/code/participants/prescreening_and_questionnaires`
   * - ``prepare-for-translation``
     - Mark participant-facing text for translation and check it.
     - :doc:`/code/participants/internationalization`
   * - ``participant-quality-telemetry``
     - Record signals of participant quality and AI assistance.
     - :doc:`/design/participants`
   * - ``turn-pure-experiment-to-ai-hybrid``
     - Let AI participants take part alongside, or instead of, humans.
     - :doc:`/design/participants`
   * - ``verify-ai-model-usability``
     - Check that the AI models an experiment relies on are reachable.
     - :doc:`/reference/configuration`
   * - ``upgrade-to-psynet-14``
     - Move an existing experiment through the PsyNet 14 breaking changes.
     - :doc:`/whats_new/upgrading_to_psynet_14`
   * - **Testing and auditing**
     -
     -
   * - ``simulate-participants``
     - Write bots that take the experiment, for tests and practice data.
     - :doc:`/test/backend`
   * - ``participant-response-models``
     - Model how participants respond, for simulations.
     - :doc:`/test/design_simulation`
   * - ``power-analysis``
     - Choose participant, stimulus and trial counts before collecting data.
     - :doc:`/test/design_simulation`
   * - ``precision-estimation``
     - Run the default simulation method for ``power-analysis``.
     - :doc:`/test/design_simulation`
   * - ``playwright-testing``
     - Write browser tests and layout checks for participant pages.
     - :doc:`/test/frontend`
   * - ``record-participant-video``
     - Capture screenshots and a video of a participant's session.
     - :doc:`/test/frontend`
   * - ``produce-experiment-audit``
     - Assemble and validate the experiment's audit.
     - :doc:`/test/audits`
   * - **Deploying and data**
     -
     -
   * - ``prepare-for-cint``
     - Make an experiment ready for recruitment through Cint.
     - :doc:`/deploy/recruiters/cint`
   * - ``deploy-experiment``
     - Check deployment readiness and run deployments safely.
     - :doc:`/deploy/running_a_study`
   * - ``monitor-experiment``
     - Watch a running study's participant flow and data.
     - :doc:`/deploy/running_a_study`
   * - ``basic-data``
     - Define the experiment's basic data for analysis.
     - :doc:`/data/basic_data`
   * - ``basic-data-dyadic-experiment``
     - Flatten data from two-participant experiments for analysis.
     - :doc:`/data/basic_data`
   * - **Previewing**
     -
     -
   * - ``prepare-experiment-tunnel``
     - Share a running local experiment through a temporary public link.
     - :doc:`running_and_debugging`
   * - ``public-tunnel``
     - Open a temporary public HTTPS tunnel to any local service.
     - :doc:`running_and_debugging`
