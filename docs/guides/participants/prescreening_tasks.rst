===================
Pre-screening tasks
===================

You can choose from the following ready-to-use pre-screening tasks:

* `Color blindness test`_
* `Color vocabulary test`_
* `Headphone check`_

If you need to build your own custom tasks, please have a look at the :ref:`Creating pre-screening tasks` for how to implement those.


Color blindness test
--------------------

The color blindness test checks the participant's ability to perceive colors. In each trial an image is presented which contains a number and the participant must enter the number that is shown into a text box. The image disappears after a certain time, the default of which is three seconds. This value can be adjusted by providing an optional ``hide_after`` argument. See the documentation for :class:`~psynet.prescreen.ColorBlindnessTest` for further details.

.. image:: ../../_static/images/color_blindness.png
  :alt: Color blindness test


Color vocabulary test
---------------------

The color vocabulary test checks the participant's ability to name colors. In each trial, a colored box is presented and the participant must choose from a set of color names which one is displayed in the box. The colors which are presented can be freely chosen by providing an optional ``colors`` parameter. See the documentation for :class:`~psynet.prescreen.ColorVocabularyTest` for further details.

.. image:: ../../_static/images/color_vocabulary.png
  :alt: Color vocabulary test

Headphone check
---------------

The headphone check makes sure that the participant is wearing headphones. In each trial, three sounds separated by silences are played and the participent's must judge which sound was the softest (quietest). See the documentation for :class:`~psynet.prescreen.HugginsHeadphoneTest` for further details.

.. image:: ../../_static/images/headphone_test.png
  :alt: Headphone check

Audio forced choice check
-------------------------

The audio forced choice test makes sure that the participant can correctly classify a sound. In each trial, the participant hears one sound and has to pick one answer from a list. See the documentation for :class:`~psynet.prescreen.AudioForcedChoiceTest` for further details.
