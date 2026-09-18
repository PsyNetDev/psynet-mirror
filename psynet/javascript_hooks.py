"""Shared hooks for components that contribute page JavaScript and CSS."""


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
