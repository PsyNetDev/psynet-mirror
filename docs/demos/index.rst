.. _demos_catalog:

Demos
=====

The ``demos`` directory of the
`PsyNet repository <https://gitlab.com/PsyNetDev/PsyNet>`_ holds three kinds
of runnable demo: ``demos/features`` shows one building block per demo,
``demos/pipelines`` holds end-to-end pipelines for common paradigms, and
``demos/experiments`` holds fuller experiments. Each demo runs with
``psynet debug local``, either in place in a PsyNet source checkout or as a
copy, as described in :doc:`/code/project/creating_an_experiment`.

.. _demos_catalog_pipelines:

Pipelines
---------

Each pipeline takes a directory of audio files and collects one kind of
judgment on them. To use your own stimuli, copy the pipeline, put the files in
its ``static/`` directory, and change ``STIMULUS_DIR`` and
``STIMULUS_PATTERN`` at the top of ``experiment.py``. Paths are relative to
the experiment directory. Changes to the stimuli need a restart of
``psynet debug local``. :doc:`/code/using_stimuli` describes how the files
reach the participant, and :doc:`/code/stimuli_on_s3` covers stimulus sets
too large to deploy with the experiment.

`pipelines/simple_rating <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/pipelines/simple_rating>`__
    Participants rate each sound on several 1–5 scales.
    :doc:`/code/writing_a_trial_maker`.

`pipelines/similarity <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/pipelines/similarity>`__
    Participants hear pairs of sounds and rate their similarity from 1 to 5.

`pipelines/timed_push_buttons <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/pipelines/timed_push_buttons>`__
    While a piece of music plays, participants press a button at interesting
    moments, then describe each moment.

`pipelines/step_tag <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/pipelines/step_tag>`__
    Participants write emotion tags for music clips and rate each other's tags
    until the tags for each clip settle.

`pipelines/tapping <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/pipelines/tapping>`__
    Participants tap along to metronomes and to music, with REPP volume,
    recording and tapping calibration. Stimuli are ``.wav`` files in
    ``data/music_stimuli``, each with an onset file of the same name ending
    in ``.txt``.

Timelines
---------

`experiments/hello_world <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/hello_world>`__
    The smallest experiment: a single info page.

`features/timeline <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/timeline>`__
    Page makers, code blocks, ``conditional``, ``switch``, ``while_loop`` and
    ``for_loop`` on deliberately simple pages. :doc:`/design/timeline`,
    :doc:`/code/writing_a_timeline`.

`experiments/timeline <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/timeline>`__
    A longer walk through the same constructs, with consent, forms, modules
    and participant variables.

`features/for_loop <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/for_loop>`__
    Nested ``for_loop`` constructs that show one page per item.

`features/page_maker <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/page_maker>`__
    ``PageMaker`` building pages, code blocks and loops from earlier answers.

`features/randomize <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/randomize>`__
    ``randomize`` shuffling 100 info pages into a different order for each
    participant.

`features/randomize_2 <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/randomize_2>`__
    ``randomize`` shuffling the order of two whole trial makers.

`features/accumulate_answers <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/accumulate_answers>`__
    ``accumulate_answers=True`` collecting the answers from several pages
    into one dictionary, in a page maker, a trial and a loop.

`features/async_codeblock <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/async_codeblock>`__
    ``AsyncCodeBlock`` running server-side work in the background, with and
    without waiting for the result.

`features/wait <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/wait>`__
    ``wait_while`` holding the participant on a waiting indicator until a
    condition becomes false.

`features/pre_deploy_constant <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/pre_deploy_constant>`__
    ``pre_deploy_constant`` recording values from your own computer at deploy
    time, such as a list of local data files, so the deployed experiment can
    read them.

`features/website <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/website>`__
    A small multi-page website built from ``while_loop`` and ``switch``,
    with the reward and progress bar turned off.

Pages and controls
------------------

`features/pages <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/pages>`__
    Info pages and modular pages combining text, image and audio prompts
    with buttons, text boxes and audio recording. :doc:`/design/pages`,
    :doc:`/code/writing_pages`.

`features/modular_page <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/modular_page>`__
    A gallery of prompt and control combinations, ending with custom
    ``Prompt`` and ``Control`` classes. :doc:`/code/pages/control_gallery`.

`features/option_controls <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/option_controls>`__
    Push buttons, dropdowns, checkboxes and radio buttons, with their layout
    and selection options.

`features/slider <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/slider>`__
    ``SliderControl`` options: range, steps, snapping, circular sliders,
    ``minimal_interactions`` and ``random_wrap``.

`features/rhythm_slider <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/rhythm_slider>`__
    ``AudioSliderControl`` playing a different rhythm for each slider
    position.

`features/simple_multimedia_slider <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/simple_multimedia_slider>`__
    ``MediaSliderControl`` playing a different audio or video clip for each
    slider position.

`features/progress_display <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/progress_display>`__
    ``ProgressDisplay`` and ``ProgressStage`` labeling the stages of a timed
    page, and events that trigger messages and alerts.
    :doc:`/code/pages/event_management`.

`features/validate <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/validate>`__
    Page-level and control-level validation that keeps the participant on the
    page until the answer is acceptable.

`features/music_notation <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/music_notation>`__
    ``MusicNotationPrompt`` showing a chord in staff notation.

`experiments/survey_js <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/survey_js>`__
    A questionnaire built with ``SurveyJSControl``. To design one, use the
    `SurveyJS Creator <https://surveyjs.io/create-free-survey>`_, copy the
    JSON from its JSON Editor tab into the control's ``design`` argument, and
    change JSON literals such as ``true`` to Python ones such as ``True``.

`experiments/graphics <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/graphics>`__
    Graphic prompts and controls with shapes, paths, images, text and
    animations. :doc:`/code/pages/graphics`.

`features/custom_theme <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/custom_theme>`__
    Styling an experiment with a CSS file in ``css_links`` and inline rules
    in ``css``. :doc:`/code/pages/theming`.

`features/api <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/api>`__
    ``expose_to_api`` letting a page's JavaScript call Python functions
    without leaving the page. :doc:`/code/pages/custom_front_ends`.

`experiments/jspsych <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/jspsych>`__
    A jsPsych reaction-time task embedded with ``JsPsychPage``.

`experiments/unity_autoplay <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/unity_autoplay>`__
    A Unity WebGL game embedded with ``UnityPage``, with participants
    randomly assigned to scoring conditions.
    :doc:`/code/pages/unity_integration`.

Trials
------

`experiments/trial <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/trial>`__
    A ``Trial`` class shown with ``Trial.cue`` inside a ``for_loop``, without
    a trial maker: participants rate how happy some words feel.
    :doc:`/design/trials`, :doc:`/code/writing_a_trial_maker`.

`experiments/trial_2 <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/trial_2>`__
    The same task with a fixed set of nodes, each with a synthesized audio
    stimulus generated at launch.

`experiments/trial_3 <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/trial_3>`__
    The same task with stimulus parameters sampled from a continuous range
    and audio synthesized when the trial needs it.

`experiments/static <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/static>`__
    ``StaticTrialMaker`` with blocks, keyboard responses, repeat trials and a
    performance check.

`experiments/simple_audio_rating <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/simple_audio_rating>`__
    Participants rate a fixed list of instrument sounds on several 1–5
    scales, six trials each. For your own stimuli, start from
    ``pipelines/simple_rating``, which reads a folder of files.

`experiments/audio_similarity <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/audio_similarity>`__
    Participants rate the similarity of pairs from a fixed list of instrument
    sounds from 1 to 5. For your own stimuli, start from
    ``pipelines/similarity``, which reads a folder of files.

`experiments/audio_stimulus_set_from_dir <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/audio_stimulus_set_from_dir>`__
    ``compile_nodes_from_directory`` turning folders of audio files into
    practice and main trial makers. :doc:`/code/using_stimuli`.

`experiments/static_audio_3 <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/static_audio_3>`__
    Participants rate how much they like existing sound files.

`features/dense_color <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/dense_color>`__
    ``DenseTrialMaker`` sampling colors from continuous hue, saturation and
    lightness dimensions for participants to rate.

`features/trial_cue_adaptive <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/trial_cue_adaptive>`__
    A 1-up/1-down staircase written with ``Trial.cue`` and ``while_loop``,
    with the adaptive rule in a separate, testable module.

Chains
------

`experiments/chain_trial_maker <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/chain_trial_maker>`__
    A custom ``ChainTrialMaker`` in which each participant retells the
    previous participant's story. :doc:`/design/chains`,
    :doc:`/code/writing_a_chain_experiment`.

`experiments/imitation_chain <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/imitation_chain>`__
    An imitation chain in which participants remember a number and type it
    back.

`experiments/imitation_chain_video <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/imitation_chain_video>`__
    An imitation chain of gestures recorded with the camera.

`experiments/tapping_iterated <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/tapping_iterated>`__
    An audio imitation chain of rhythms: participants tap along to a rhythm,
    and the server extracts the tap times to make the next rhythm.

`experiments/tapping_memory <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/tapping_memory>`__
    The same chain, but participants tap the rhythm from memory after it
    stops.

`experiments/gibbs <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/gibbs>`__
    Gibbs Sampling with People: participants adjust one dimension of a color
    at a time to match a word, in across-participant chains with two
    participant groups. See :ref:`gibbs_participant_groups`.

`experiments/gibbs_within <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/gibbs_within>`__
    The same task with within-participant chains.

`experiments/gibbs_audio <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/gibbs_audio>`__
    ``AudioGibbsTrialMaker``: participants move through a space of
    synthesized voices to make a word sound as dominant or trustworthy as
    possible.

`experiments/gibbs_audio_complex <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/gibbs_audio_complex>`__
    Audio Gibbs sampling over several prosodic dimensions, with emotion
    targets.

`experiments/gibbs_image <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/gibbs_image>`__
    ``ImageGibbsTrialMaker`` with generated images of colored squares.

`experiments/gibbs_svg <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/gibbs_svg>`__
    ``HtmlGibbsTrialMaker`` with animated SVG stimuli, locking the slider
    while the animation plays.

`experiments/gibbs_svg_zipped <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/gibbs_svg_zipped>`__
    The same task, synthesizing all slider positions in one batch and
    delivering them as one zipped file.

`experiments/gibbs_video <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/gibbs_video>`__
    ``VideoGibbsTrialMaker`` with synthesized video clips.

`experiments/mcmcp <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/mcmcp>`__
    Markov Chain Monte Carlo with People: participants choose which of two
    ages better fits an occupation, and the choice becomes the chain's next
    state.

`experiments/staircase_pitch_discrimination <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/staircase_pitch_discrimination>`__
    ``GeometricStaircaseTrialMaker``: a 2-up/1-down pitch discrimination
    staircase.

`experiments/graph <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/graph>`__
    ``GraphChainTrialMaker`` with chains on a lattice, using necklaces of
    colored beads.

`experiments/create_and_rate/basic <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/create_and_rate/basic>`__
    Create and rate: participants describe a dog image, and others rate the
    descriptions or choose the best one. :doc:`/code/trials/create_and_rate`.

`experiments/create_and_rate/picnic <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/create_and_rate/picnic>`__
    Participants guess a hidden rule from examples, and others rate the
    guesses.

`experiments/create_and_rate/robot_voice <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/create_and_rate/robot_voice>`__
    Participants create a robot voice with audio Gibbs sampling, and others
    rate or choose the best match.

`experiments/create_and_rate/gap <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/create_and_rate/gap>`__
    Participants record a sentence for an imagined situation, and separate
    raters choose the most emotional recording.

Stimuli, media and recording
----------------------------

`experiments/audio <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/audio>`__
    JSSynth chords, audio and video prompts, audio meters, and audio and
    video recording. :doc:`/code/writing_pages`.

`features/video <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/video>`__
    ``VideoPrompt`` and ``VideoRecordControl``: clipped playback, separate
    soundtracks, and recording from the camera and screen.

`features/assets <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/assets>`__
    ``asset`` declaring remote files, local files, folders and generated
    files, and saving participant input as a new asset.
    :doc:`/code/trials/assets`.

`experiments/static_audio <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/static_audio>`__
    Participants hear a synthesized word, record themselves repeating it, and
    listen back. :doc:`/code/using_stimuli`.

`experiments/static_audio_2 <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/static_audio_2>`__
    The same task with a stimulus parameter drawn from a continuous range.

`features/volume_calibration <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/volume_calibration>`__
    ``VolumeCalibration``, a page for setting a comfortable listening level.

`experiments/tapping_static <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/tapping_static>`__
    Tapping to a metronome and to music with REPP, with calibration and
    recording checks.

`experiments/repp_prescreen <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/repp_prescreen>`__
    REPP volume calibration, tapping calibration and recording tests for use
    before a tapping task.

`experiments/vertical_processing <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/vertical_processing>`__
    A complete music experiment: participants hear a chord and sing back its
    notes, which the server scores. It includes practice trials, notation,
    synthesized audio and questionnaires.

Participants
------------

`features/demography <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/demography>`__
    The built-in demography and questionnaire modules, including the Gold-MSI.
    :doc:`/code/participants/prescreening_and_questionnaires`.

`features/attention_test <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/attention_test>`__
    ``AttentionTest`` placed between questionnaire items.

`features/headphone_test <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/headphone_test>`__
    ``HugginsHeadphoneTest`` and ``AntiphaseHeadphoneTest`` after volume
    calibration.

`features/color_blindness <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/color_blindness>`__
    ``ColorBlindnessTest``, an Ishihara-style screening test.

`features/color_vocabulary <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/color_vocabulary>`__
    ``ColorVocabularyTest``, which checks that participants know common
    color names.

`features/audio_forced_choice_test <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/audio_forced_choice_test>`__
    ``AudioForcedChoiceTest`` screening participants with audio stimuli and
    answers listed in a CSV file.

`experiments/language_tests <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/language_tests>`__
    ``LexTaleTest`` for English proficiency and ``LanguageVocabularyTest``
    for Spanish.

`experiments/vocabulary_test <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/vocabulary_test>`__
    ``WikiVocab`` and ``BibleVocab`` vocabulary tests in Dutch and English.

`features/monitor_information <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/monitor_information>`__
    ``MonitorInformation`` recording the participant's screen properties.

`experiments/translation <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/translation>`__
    An experiment translated into German and Dutch with ``_`` and ``_p``.
    :doc:`/code/participants/internationalization`.

Groups
------

`experiments/simple_sync_group <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/simple_sync_group>`__
    ``SimpleGrouper``, ``GroupBarrier`` and ``GroupCloser``: groups of three
    with roles, later regrouped into pairs. :doc:`/design/groups`,
    :doc:`/code/multiplayer/synchronization`.

`experiments/sync_quorum <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/sync_quorum>`__
    Participants do filler trials until enough people have joined.

`experiments/gibbs_within_sync <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/gibbs_within_sync>`__
    Gibbs sampling in which a group responds to each step together and the
    chain continues from the group's summarized answer.

`experiments/create_rate_sync <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/create_rate_sync>`__
    A live create-and-rate game for groups of three.

`experiments/chatroom_simple <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/chatroom_simple>`__
    Pairs of participants chat about a topic with ``EnableChatrooms`` and
    ``ChatRoom``. :doc:`/code/multiplayer/chatroom`.

`experiments/rock_paper_scissors <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/rock_paper_scissors>`__
    A two-player game with scored rounds and a chat after each round.

`features/websocket_chatroom <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/websocket_chatroom>`__
    A multi-room chat written directly on WebSockets rather than
    ``psynet.chatroom``. Clients exchange messages on one shared channel and
    filter them by room. The experiment's ``receive_message`` stores each
    message in a custom table, ``publish_to_subscribers`` sends room
    occupancy to every client, and a custom route returns a room's history
    to late joiners. ``config.txt`` sets ``num_chatrooms``,
    ``chatroom_max_occupancy`` and ``chatroom_show_history``.
    :doc:`/code/multiplayer/realtime_interaction`.
    :doc:`/code/pages/custom_routes`.

Database, bots and data
-----------------------

`features/custom_table_simple <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/custom_table_simple>`__
    A custom database table that stores a coin each time the participant
    collects one. :doc:`/code/project/classes_and_sqlalchemy`.

`features/custom_table_complex <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/custom_table_complex>`__
    A custom table with subclasses, each defining its own pages.

`features/bot <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/bot>`__
    Three ways to give bots responses: a fixed ``bot_response``, a function,
    and a custom control. :doc:`/test/backend`.

`features/bot_2 <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/bot_2>`__
    A scheduled task that starts a bot every 10 seconds in a running
    imitation chain.

`features/artifact_storage <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/features/artifact_storage>`__
    ``S3ArtifactStorage`` with automatic backups of the data defined in
    ``get_basic_data``. :doc:`/data/exporting_data`.
