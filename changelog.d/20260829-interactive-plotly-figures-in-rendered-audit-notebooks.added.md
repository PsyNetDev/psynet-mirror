Added interactive Plotly figures to rendered audit notebooks. Plotly MIME
outputs render with a vendored Plotly.js runtime, so audit sites remain
self-contained and work offline. The runtime is copied into a rendered site
only when that audit actually contains a figure.
