Trials (3)
==========

Source: ``demos/experiments/trial_3``

This demo follows on from the previous Trial demo. Like the previous demo, it uses programmatically
generated audio stimuli. However, instead of generating these stimuli in advance of deployment,
these stimuli are instead generated on-demand when the participant requests them.
This approach is particularly useful when your experiment involves a high degree of randomness
such that it would be impractical to generate all possible stimuli in advance.


Source: ``demos/experiments/trial_3/experiment.py``

.. literalinclude:: ../../demos/experiments/trial_3/experiment.py
   :language: python
