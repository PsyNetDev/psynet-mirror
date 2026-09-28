================================
Pre-screening and questionnaires
================================

Pre-screening tasks
-------------------

A pre-screening task is a module in the timeline, usually placed before the
main task. The ``color_blindness`` demo runs one test and then continues:

.. literalinclude:: ../../../demos/features/color_blindness/experiment.py
   :start-at: timeline = Timeline(
   :end-before: def test_check_bot
   :dedent: 4

Most built-in tests are trial makers with a performance check at the end.
Each trial is scored, and the participant passes if the total score reaches
``performance_threshold``. :class:`~psynet.prescreen.ColorBlindnessTest`,
for example, has six trials and passes at 4 correct answers by default. A
participant who fails is shown an :class:`~psynet.page.UnsuccessfulEndPage`,
is marked as failed, and is paid for the time spent so far (see
:doc:`payment`). By default their trials in the test are failed too; set
``fail_trials_on_participant_performance_check=False`` on your own tests to
keep them.

To write your own test, see :doc:`creating_prescreening_tasks`.

Built-in tests
~~~~~~~~~~~~~~

Vision:

- :class:`~psynet.prescreen.ColorBlindnessTest`: the participant types the
  number shown in an Ishihara image. The image disappears after
  ``hide_after`` seconds (default 3).
- :class:`~psynet.prescreen.ColorVocabularyTest`: the participant names the
  color of a box. ``colors`` sets the colors presented.

.. image:: ../../_static/images/color_blindness.png
  :alt: Color blindness test

.. image:: ../../_static/images/color_vocabulary.png
  :alt: Color vocabulary test

Headphones and audio:

- :class:`~psynet.prescreen.HugginsHeadphoneTest` (recommended): each trial
  plays three noises, and the participant picks the one with a hidden beep.
- :class:`~psynet.prescreen.AntiphaseHeadphoneTest`: the participant picks the
  softest of three sounds.
- ``BeepHeadphoneTest``: the participant picks the sound that differs from the
  other two.
- :class:`~psynet.prescreen.AudioForcedChoiceTest`: the participant
  classifies sounds listed in a CSV file.

Place :class:`~psynet.page.VolumeCalibration` before a headphone test, as in
the ``headphone_test`` demo.

.. image:: ../../_static/images/headphone_test.png
  :alt: Headphone check

Language:

- :class:`~psynet.prescreen.LexTaleTest`: an English lexical decision task.
- :class:`~psynet.prescreen.LanguageVocabularyTest`: the participant matches a
  spoken word to one of four images, in five languages.
- ``WikiVocab`` and ``BibleVocab`` (in ``psynet.prescreen.vocabtest``):
  vocabulary tests for many languages.

Attention:

- :class:`~psynet.prescreen.AttentionTest`: two instruction-following pages.

Tapping, for experiments that use REPP:

- :class:`~psynet.prescreen.REPPVolumeCalibrationMusic` and
  :class:`~psynet.prescreen.REPPVolumeCalibrationMarkers`: volume
  calibration.
- :class:`~psynet.prescreen.REPPTappingCalibration`: tapping instructions and
  calibration.
- :class:`~psynet.prescreen.REPPMarkersTest` and ``FreeTappingRecordTest``:
  check that the participant's hardware records valid tapping data.

Parameters and defaults for each test are in :doc:`/reference/api/prescreen`.

Questionnaires
--------------

The ``psynet.demography`` package contains demographic questionnaires in three
modules: general demography, the Goldsmiths Musical Sophistication Index
(GMSI), and the PEI confidence scale (see :doc:`/reference/api/demography`).
Questionnaires and individual questions are timeline elements and can be
placed in any order. The ``demography`` demo uses all of them:

.. literalinclude:: ../../../demos/features/demography/experiment.py
   :start-at: timeline = Timeline(
   :dedent: 4

General demography
~~~~~~~~~~~~~~~~~~

:py:mod:`~psynet.demography.general` contains these groups of questions:

* :class:`~psynet.demography.general.BasicDemography`
* :class:`~psynet.demography.general.Language`
* :class:`~psynet.demography.general.BasicMusic`
* :class:`~psynet.demography.general.Dance`
* :class:`~psynet.demography.general.SpeechDisorders`
* :class:`~psynet.demography.general.Income`
* :class:`~psynet.demography.general.ExperimentFeedback`

It also contains single-question pages, such as
:class:`~psynet.demography.general.HearingLoss`,
:class:`~psynet.demography.general.MotherTongues` and
:class:`~psynet.demography.general.LanguagesInOrderOfProficiency`. The
questions in each group are defined in its source code.

Goldsmiths Musical Sophistication Index (GMSI)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Background on the GMSI is available at
https://www.gold.ac.uk/music-mind-brain/gold-msi and
https://shiny.gold-msi.org/gmsi_toplevel/, which also provides complementary
tools and resources.

:class:`~psynet.demography.gmsi.GMSI` adds the full questionnaire to the
timeline. At the end of the questionnaire, PsyNet saves the scores in the
participant variable named after the module's ``label`` (``"gmsi"`` by
default). The value contains ``response_scores`` (the score for each question)
and ``mean_scores_per_scale``. Give each instance a different ``label`` when
the timeline contains more than one GMSI.

``GMSI(short_version=True)`` uses a short version with 29 questions. It
corresponds to the short version implemented in the
`psyquest <https://github.com/fmhoeger/psyquest>`_ psychTestR package and
includes a subset of questions from every subscale.

The GMSI has six subscales:

* Active Engagement
* Perceptual Abilities
* Musical Training
* Singing Abilities
* Emotions
* General

and three additional items: Instrument, Start Age, and Absolute Pitch. Pass a
list of these names as ``subscales`` to include only those subscales; this
overrides ``short_version``.

PEI (confidence scale)
~~~~~~~~~~~~~~~~~~~~~~

:class:`~psynet.demography.pei.PEI` measures the participant's confidence. The
questions are listed in its source code.

Introductory page
~~~~~~~~~~~~~~~~~

:class:`~psynet.demography.gmsi.GMSI` and :class:`~psynet.demography.pei.PEI`
begin with a default introductory page. To replace it, pass an
:class:`~psynet.page.InfoPage` as ``info_page``.
