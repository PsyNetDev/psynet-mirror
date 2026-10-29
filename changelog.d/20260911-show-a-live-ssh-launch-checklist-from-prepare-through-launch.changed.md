``psynet debug ssh`` and ``psynet deploy ssh`` now show one live checklist
from preparing the experiment through launch, instead of a series of
unrelated status lines and spinners. Captured output can be followed with
``tail -f /tmp/dallinger-deploy.log``. The Ready summary is printed after
the checklist. This needs a Dallinger version that provides the checklist.
