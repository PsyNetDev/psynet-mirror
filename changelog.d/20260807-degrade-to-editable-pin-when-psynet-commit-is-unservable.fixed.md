Fixed ``psynet setup`` and ``psynet scripts scaffold`` failing in editable alpha
checkouts whose current commit cannot be served by ``origin`` (for example
unpushed work, or CI merge-result commits). These now record an editable PsyNet
requirement and warn that it only resolves locally; use ``psynet setup
--psynet-source commit`` to require a deployable commit pin.
