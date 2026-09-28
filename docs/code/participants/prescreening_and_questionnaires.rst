================================
Pre-screening and questionnaires
================================

Pre-screening tasks
-------------------

PsyNet provides the following ready-to-use pre-screening tasks:

* `Color blindness test`_
* `Color vocabulary test`_
* `Headphone check`_
* `Audio forced choice check`_

:doc:`/reference/api/prescreen` lists further tests, such as
:class:`~psynet.prescreen.AttentionTest`. Custom pre-screening tasks are
covered in :ref:`Creating pre-screening tasks <Creating pre-screening tasks>`.

Color blindness test
~~~~~~~~~~~~~~~~~~~~

:class:`~psynet.prescreen.ColorBlindnessTest` checks the participant's ability
to perceive colors. Each trial shows an image containing a number, and the
participant types the number into a text box. The image disappears after
three seconds by default; set ``hide_after`` to change this.

.. image:: ../../_static/images/color_blindness.png
  :alt: Color blindness test

Color vocabulary test
~~~~~~~~~~~~~~~~~~~~~

:class:`~psynet.prescreen.ColorVocabularyTest` checks the participant's
ability to name colors. Each trial shows a colored box, and the participant
chooses its name from a set of color names. Set ``colors`` to choose which
colors are presented.

.. image:: ../../_static/images/color_vocabulary.png
  :alt: Color vocabulary test

Headphone check
~~~~~~~~~~~~~~~

:class:`~psynet.prescreen.HugginsHeadphoneTest` checks that the participant is
wearing headphones. Each trial plays three sounds separated by silences, and
the participant judges which sound was the softest.

.. image:: ../../_static/images/headphone_test.png
  :alt: Headphone check

Audio forced choice check
~~~~~~~~~~~~~~~~~~~~~~~~~

:class:`~psynet.prescreen.AudioForcedChoiceTest` checks that the participant
can classify a sound correctly. Each trial plays one sound, and the participant
picks one answer from a list.

Questionnaires
--------------

The ``psynet.demography`` package contains demographic questionnaires in three
modules: general demography, the Goldsmiths Musical Sophistication Index
(GMSI), and the PEI confidence scale (see :doc:`/reference/api/demography`).
Individual questions are page classes and can be placed in the timeline in any
order. The ``demos/features/demography`` demo uses all of them.

General demography
~~~~~~~~~~~~~~~~~~

:py:mod:`~psynet.demography.general` contains the following groups of
questions:

* :class:`~psynet.demography.general.BasicDemography`
* :class:`~psynet.demography.general.Language`
* :class:`~psynet.demography.general.BasicMusic`
* :class:`~psynet.demography.general.HearingLoss`
* :class:`~psynet.demography.general.Dance`
* :class:`~psynet.demography.general.SpeechDisorders`
* :class:`~psynet.demography.general.Income`
* :class:`~psynet.demography.general.ExperimentFeedback`

The questions in each group are defined in its source code.

Goldsmiths Musical Sophistication Index (GMSI)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Background on the GMSI is available at
https://www.gold.ac.uk/music-mind-brain/gold-msi and
https://shiny.gold-msi.org/gmsi_toplevel/, which also provides complementary
tools and resources.

:class:`~psynet.demography.gmsi.GMSI` adds the full questionnaire to the
timeline:

.. code-block:: python

    from psynet.demography.gmsi import GMSI

    timeline = Timeline(
        GMSI(),
        SuccessfulEndPage(),
    )

At the end of the questionnaire, PsyNet saves the scores in the participant
variable named after the module's ``label`` (``"gmsi"`` by default). The value
contains ``response_scores`` (the score for each question) and
``mean_scores_per_scale``. Give each instance a different ``label`` when the
timeline contains more than one GMSI.

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
