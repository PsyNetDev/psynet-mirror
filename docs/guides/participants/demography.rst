==========
Demography
==========

PsyNet contains various questionnaires for doing demographic research including an implementation of the `Goldsmiths Musical Sophistication Index` questionnaire (GMSI).

The ``demos/features/demography`` directory contains a demo illustrating the available demographic questions.

Questions are grouped into the three main modules `General`, `GMSI`, and `PEI`, whereby `General` has an additional level of grouping, see below.

Depending on the experiment setup, though, single questions can be arranged in whatever order necessary.

General demography
------------------

The :py:mod:`~psynet.demography.general` module contains the following `PsyNet` modules:

* :class:`~psynet.demography.general.BasicDemography`
* :class:`~psynet.demography.general.Language`
* :class:`~psynet.demography.general.BasicMusic`
* :class:`~psynet.demography.general.HearingLoss`
* :class:`~psynet.demography.general.Dance`
* :class:`~psynet.demography.general.SpeechDisorders`
* :class:`~psynet.demography.general.Income`
* :class:`~psynet.demography.general.ExperimentFeedback`

See the source code of these modules for the specific questions contained within each submodule by clicking on the submodule links above.

A demo containing all general demography questions can be found at ``demos/features/demography``.


Goldsmiths Musical Sophistication Index (GMSI)
----------------------------------------------

For background information on the GMSI, see https://www.gold.ac.uk/music-mind-brain/gold-msi and
https://shiny.gold-msi.org/gmsi_toplevel/ the latter of which contains an extensive set of resources and also tools which complement the PsyNet's documentation.

Full version
++++++++++++

The complete set of questions contained in :class:`~psynet.demography.gmsi.GMSI` can be inserted into an experiment timeline using below code snippet:

::

    gmsi_questionnaire = GMSI()

    timeline = Timeline(
        gmsi_questionnaire,
        gmsi_questionnaire.save_scores,
        SuccessfulEndPage(),
    )

The ``save_scores`` property of :class:`~psynet.demography.gmsi.GMSI` has to be called subsequently in order to calculate and save the scores.

See the source code for the full set of questions contained within :class:`~psynet.demography.gmsi.GMSI`.

Short version
+++++++++++++

There also exists a short version of the GMSI questionnaire which comprises only 29 questions. It can be added to an experiment timeline using following code snippet:

::

    gmsi_questionnaire = GMSI(short_version=True)

    timeline = Timeline(
        gmsi_questionnaire,
        gmsi_questionnaire.save_scores,
        SuccessfulEndPage(),
    )

This 'short version' corresponds to the short version as implemented in the psyquest/psychTestR project, see https://github.com/fmhoeger/psyquest. All subscales are included and from each one a certain subset of questions is selected.


Subscales
+++++++++

There are six subscales contained within the GMSI questionnaire which are:

* Active Engagement
* Perceptual Abilities
* Musical Training
* Singing Abilites
* Emotions
* General

and the three additional items (subscales):

* Instrument
* Start Age
* Absolute Pitch

See ``demos/features/demography`` for a demo.


PEI (Confidence scale)
----------------------

For measuring the confidence of a participant use the :class:`~psynet.demography.pei.PEI` module:
Visit the source code for the specific questions contained in this module.

Check out ``demos/features/demography`` for a demo.


Introductionary page
--------------------

Both :class:`~psynet.demography.gmsi.GMSI` and :class:`~psynet.demography.pei.PEI` have an introductionary page by default the content of which can be found in the source code. To override it, an experimenter can provide an :class:`~psynet.page.InfoPage` object using the ``info_page`` argument.
