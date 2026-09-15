============================================
Markov Chain Monte Carlo with People (MCMCP)
============================================

Markov Chain Monte Carlo with People (MCMCP) is an adaptive procedure related
to Gibbs Sampling with People (GSP). Like GSP, it is intended to map participants'
associations of a stimulus space. In each trial, the participant is presented with a
pair of stimuli: a 'current state' and a 'proposal state'. They are asked to decide
which stimulus best matches a given criterion. The chosen stimulus is then accepted
as the next state, and a new proposal is generated from that state by making a small
random jump in the stimulus space.


Source: ``demos/experiments/mcmcp``

.. literalinclude:: ../../demos/experiments/mcmcp/experiment.py
   :language: python
