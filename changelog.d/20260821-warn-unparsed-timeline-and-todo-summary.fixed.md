``psynet audit validate`` now warns when ``TIMELINE.md`` lines look like
entries but were ignored (for example an actor tag other than
``agent-start`` / ``agent`` / ``agent-stop`` / ``manual`` / ``system``), and
when ``implementation.summary`` is still the starter TODO. The rendered page
omits that TODO so it is not the subtitle under the experiment title.
