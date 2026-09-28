Fixed the consent pages in the deployment tests' vendored `consents_cococo` package, which
overrode the template's `stylesheets` block without calling `{{ super() }}` and so rendered
without the PsyNet participant theme, leaving the agree/decline buttons flush against the
bottom of the page. The pages now use the standard surface panel and spacing.
