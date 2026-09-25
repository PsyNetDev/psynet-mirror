# The static directory

Files in the `static` directory are deployed with the experiment and served
to participants' browsers. A file at `static/{your-file-name}` is available
at the URL `/static/{your-file-name}`.

This is the recommended place for experiment stimuli. This demo keeps its
music in `static/global_music` and stores each file's URL in the node
definition, which the trial passes to `AudioPrompt`.
