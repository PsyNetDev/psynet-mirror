Exclude the experiment-root ``audit/`` review packet from the stock
``deploy.toml`` template. Existing experiments keep their current
``deploy.toml``; add ``audit`` to ``[exclude].paths`` if it is missing.
