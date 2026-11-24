"""Shared hooks for components that contribute page JavaScript and CSS."""

import warnings


def _warn_renamed(cls, old, new):
    warnings.warn(
        f"{cls.__name__}.{old} has been renamed to {new}.",
        DeprecationWarning,
        stacklevel=3,
    )


_RENAMED_HOOKS = [
    ("get_js_vars", "get_page_config"),
    ("get_participant_js_vars", "get_participant_page_config"),
]


def _bridge(cls, name, target, warn):
    # Bound to cls rather than looked up on self, so that a subclass bridging
    # in the other direction can't make the two hooks call each other forever.
    def bridged(self, *args, **kwargs):
        if warn:
            _warn_renamed(cls, name, target)
        return getattr(cls, name)(self, *args, **kwargs)

    bridged.__name__ = target
    bridged.__doc__ = getattr(cls, name).__doc__
    return bridged


class JavaScriptContributor:
    """Default empty hooks for managed page JavaScript and CSS contributions."""

    def __init_subclass__(cls, **kwargs):
        # The page_config hooks replaced the js_vars hooks in PsyNet 15. A class
        # that overrides only the old name gets the new one, with a warning,
        # and a class that defines only the new name answers super() calls to
        # the old one from subclasses that haven't been updated.
        super().__init_subclass__(**kwargs)
        for old, new in _RENAMED_HOOKS:
            if old in cls.__dict__ and new not in cls.__dict__:
                setattr(cls, new, _bridge(cls, old, new, warn=True))
            elif new in cls.__dict__ and old not in cls.__dict__:
                setattr(cls, old, _bridge(cls, new, old, warn=False))

    def get_js_dependencies(self):
        """JavaScript dependencies loaded once per browser document."""
        return []

    def get_js_page_modules(self):
        """Lifecycle-managed JavaScript activated for each hosting page."""
        return []

    def get_js_page_code(self):
        """Inline JavaScript activation code contributed to the hosting page."""
        return []

    def get_css(self):
        """Inline CSS snippets contributed to the hosting page."""
        return []

    def get_css_links(self):
        """Stylesheet URLs contributed to the hosting page."""
        return []

    def get_page_config(self):
        """Page configuration this component contributes, read in the browser
        as ``psynet.pageConfig``. It stays fixed while the page is shown.

        Keys must be unique across the page's components and its
        ``page_config``.
        """
        return {}

    def get_participant_page_config(self, experiment, participant):
        """Page configuration for ``participant``, contributed each time the
        page renders for them, such as something stored for the participant.
        Keys must be unique across the page's configuration.
        """
        return {}

    def get_js_vars(self):
        """Deprecated: override :meth:`get_page_config` instead."""
        return {}

    def get_participant_js_vars(self, experiment, participant):
        """Deprecated: override :meth:`get_participant_page_config` instead."""
        return {}
