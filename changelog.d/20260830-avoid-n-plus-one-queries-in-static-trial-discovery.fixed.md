Sped up trial candidate discovery by batching viable-trial counts, skipping
those counts for unlimited unbalanced static nodes, and pairing static nodes
with their already-loaded networks so assignment no longer issues a network
query per candidate. ``TrialNode.n_viable_trials`` is still readable on a node
and usable in SQLAlchemy filters and ordering, but it is no longer a mapped
column, so it is queried on access instead of loaded with every node. As a
result it no longer appears as a column in node data exports or in the
Dallinger dashboard; count the trials at a node directly if you need it in an
analysis.
