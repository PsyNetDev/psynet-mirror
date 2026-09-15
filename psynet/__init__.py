"""PsyNet – complex psychological experiments made easy.

Importing this package is intentionally lightweight so that the minimal
``psynet`` distribution (without the ``[experiment]`` extra) can be used for
bootstrap commands such as ``psynet setup`` and ``psynet scripts …`` without
pulling in dallinger, flask, or other heavy runtime dependencies.

Full experiment-runtime initialisation (dominate patch, gevent env var, etc.)
is deferred to :func:`psynet.runtime_init.ensure_runtime`, which is called
automatically when ``psynet.command_line`` is imported (i.e. for every
experiment-runtime CLI command).
"""

from psynet.version import psynet_version

__version__ = psynet_version


def __getattr__(name):
    if name == "debugger":
        from psynet.runtime_init import ensure_runtime

        ensure_runtime()
        # Cache in module globals so every call site shares one callable, and
        # hence one debugpy listener; a fresh closure per access would re-run
        # ``debugpy.listen`` and fail at the second breakpoint.
        debugger = _make_debugger()
        globals()["debugger"] = debugger
        return debugger
    raise AttributeError(f"module 'psynet' has no attribute {name!r}")


def _make_debugger():
    """Return the debugger callable, initialising debugpy on first use."""
    import debugpy

    _state = {"listening": False}

    def debugger():
        """
        Create a breakpoint using debugpy.

        Standard IDE breakpoints don't work out of the box with PsyNet because it makes
        heavy use of subprocesses, which cannot easily be accessed using standard IDE breakpoints.
        This function provides a breakpoint that should work well in these contexts,
        specifically when running `psynet debug local`.
        It uses debugpy, which is the default debugger for VSCode/Cursor.
        The following instructions assume you are using one of these two IDEs.
        If you are using PyCharm, you should use PyCharm's remote Python debugger instead.

        Before you can use this functionality, you need to make sure your IDE workspace directory contains
        an appropriate launch.json file. In VSCode/Cursor, this file should be placed in the .vscode directory.
        We recommend the following:

        .. code:: bash

            {
                "version": "0.2.0",
                "configurations": [

                    {
                        "name": "Breakpoints in psynet debug local",
                        "type": "debugpy",
                        "request": "attach",
                        "connect": {
                            "host": "localhost",
                            "port": 5678
                        },
                        "pathMappings": [
                            {
                                "localRoot": "${fileDirname}",
                                "remoteRoot": "/tmp/dallinger_develop"
                            }
                        ]
                    }
                ]
            }

        Once you have this file, you simply place ``psynet.debugger()`` in the code where you want to create a breakpoint.
        Once you run ``psynet debug local``, you should see a message in your console that says "Press F5 to start debugging".
        Pressing F5 should start the debugger. For instructions on how to use the debugger,
        see the `VSCode documentation <https://code.visualstudio.com/docs/debugtest/debugging#_debug-actions>`_.
        """
        if not _state["listening"]:
            debugpy.listen(5678)
            _state["listening"] = True
            print("Press F5 to start debugging")
            debugpy.wait_for_client()
        debugpy.breakpoint()

    return debugger
