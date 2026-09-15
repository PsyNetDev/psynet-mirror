.. _ModularPage:

=============
Modular Pages
=============

Modular pages are the recommended way to implement custom pages in PsyNet.
They work by splitting page design into two main components:
the `Prompts`_, constituting the information or stimulus that is presented
to the listener, and the `Controls`_, constituting the participant's
way of responding to the information or stimulus.

Prompts
-------

The following subclasses of :class:`~psynet.modular_page.Prompt` exist:

* :class:`~psynet.modular_page.AudioPrompt`

* :class:`~psynet.modular_page.ImagePrompt`

* :class:`~psynet.modular_page.ColorPrompt`

* :class:`~psynet.modular_page.VideoPrompt`

* :class:`~psynet.graphics.GraphicPrompt`



Controls
--------

A wide range of controls all of which inherit from :class:`~psynet.modular_page.Control` are available:

Audio/Video controls
~~~~~~~~~~~~~~~~~~~~

* :class:`~psynet.modular_page.AudioMeterControl`

.. image:: ../_static/images/audio_meter_control.png
  :width: 560
  :alt: AudioMeterControl

* :class:`~psynet.modular_page.AudioRecordControl`

.. image:: ../_static/images/audio_record_control_recording.png
  :width: 600
  :alt: AudioRecordControl (recording)

.. image:: ../_static/images/audio_record_control_uploading.png
  :width: 600
  :alt: AudioRecordControl (uploading)

.. image:: ../_static/images/audio_record_control_finished.png
  :width: 600
  :alt: AudioRecordControl (finished)

* :class:`~psynet.modular_page.TappingAudioMeterControl`

.. image:: ../_static/images/tapping_audio_meter_control.png
  :width: 560
  :alt: TappingAudioMeterControl


* :class:`~psynet.modular_page.AudioSliderControl`


* :class:`~psynet.modular_page.VideoRecordControl`

.. image:: ../_static/images/video_record_control_waiting.png
  :width: 600
  :alt: VideoRecordControl (waiting)

.. image:: ../_static/images/video_record_control_recording.png
  :width: 600
  :alt: VideoRecordControl (recording)

.. image:: ../_static/images/video_record_control_finished.png
  :width: 580
  :alt: VideoRecordControl (finished)


* :class:`~psynet.modular_page.VideoSliderControl`

.. image:: ../_static/images/video_slider_control.png
  :width: 580
  :alt: VideoSliderControl

* :class:`~psynet.graphics.GraphicControl`

Option controls
~~~~~~~~~~~~~~~

These classes inherit from :class:`~psynet.modular_page.OptionControl`.

* :class:`~psynet.modular_page.CheckboxControl`

.. image:: ../_static/images/checkbox_control.png
  :width: 800
  :alt: CheckboxControl

* :class:`~psynet.modular_page.DropdownControl`

.. image:: ../_static/images/dropdown_control.png
  :width: 800
  :alt: DropdownControl

* :class:`~psynet.modular_page.PushButtonControl`

.. image:: ../_static/images/push_button_control.png
  :width: 800
  :alt: PushButtonControl

* :class:`~psynet.modular_page.TimedPushButtonControl`

.. image:: ../_static/images/timed_push_button_control.png
  :width: 800
  :alt: TimedPushButtonControl

* :class:`~psynet.modular_page.RadioButtonControl`

.. image:: ../_static/images/radiobutton_control.png
  :width: 800
  :alt: RadioButtonControl


Other controls
~~~~~~~~~~~~~~

* :class:`~psynet.modular_page.NullControl`

.. image:: ../_static/images/null_control.png
  :width: 800
  :alt: NullControl

* :class:`~psynet.modular_page.NumberControl`

.. image:: ../_static/images/number_control.png
  :width: 800
  :alt: NumberControl

* :class:`~psynet.modular_page.SliderControl`

.. image:: ../_static/images/slider_control.png
  :width: 800
  :alt: SliderControl

* :class:`~psynet.modular_page.TextControl`

.. image:: ../_static/images/text_control.png
  :width: 800
  :alt: TextControl

* :class:`~psynet.modular_page.SurveyJSControl`

For the full API reference, see :doc:`/api/modular_page`.
