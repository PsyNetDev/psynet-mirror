"""Shared hooks for components that contribute page JavaScript and CSS."""

import warnings


def _warn_renamed(obj, old, new):
    warnings.warn(
        f"{type(obj).__name__}.{old} has been renamed to {new}.",
        DeprecationWarning,
        stacklevel=3,
    )


class JavaScriptContributor:
    """Default empty hooks for managed page JavaScript and CSS contributions."""

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
        if type(self).get_js_vars is not JavaScriptContributor.get_js_vars:
            _warn_renamed(self, "get_js_vars", "get_page_config")
            return self.get_js_vars()
        return {}

    def get_participant_page_config(self, experiment, participant):
        """Page configuration for ``participant``, contributed each time the
        page renders for them, such as something stored for the participant.
        Keys must be unique across the page's configuration.
        """
        if (
            type(self).get_participant_js_vars
            is not JavaScriptContributor.get_participant_js_vars
        ):
            _warn_renamed(
                self, "get_participant_js_vars", "get_participant_page_config"
            )
            return self.get_participant_js_vars(experiment, participant)
        return {}

    def get_js_vars(self):
        """Deprecated: override :meth:`get_page_config` instead."""
        return {}

    def get_participant_js_vars(self, experiment, participant):
        """Deprecated: override :meth:`get_participant_page_config` instead."""
        return {}
