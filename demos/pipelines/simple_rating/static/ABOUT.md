# The static directory

Files in the `static` directory are deployed with the experiment and served
to participants' browsers. A file at `static/{your-file-name}` is available
at the URL `/static/{your-file-name}`.

This is the recommended place for experiment stimuli. This demo keeps its
sounds in `static/instrument_sounds` and stores each file's URL in the node
definition:

```python
StaticNode(
    definition={
        "stimulus_name": "clarinet",
        "audio_url": "/static/instrument_sounds/clarinet.mp3",
    },
)
```

The trial then passes that URL to the page, for example
`AudioPrompt(self.definition["audio_url"], ...)`.
