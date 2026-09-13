Stopped ``SAWarning: This declarative base already contains a class`` and
``SAWarning: Reassigning polymorphic association`` appearing when PsyNet loads
``experiment.py`` more than once in a process, which happens during
``psynet debug`` and ``psynet deploy`` and when Dallinger's config loader reads
the experiment's extra parameters. Any experiment that defines a ``Trial``
subclass or a custom table saw these warnings, which described PsyNet's own
reloading rather than anything an experimenter could act on. Experiment test
suites that run pytest with ``-W error`` no longer fail because of them.
