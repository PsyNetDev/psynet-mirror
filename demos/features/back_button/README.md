# Back button

Run `psynet debug local` in this directory. Click through three instruction pages, going back and forth with Back and Next. The question after them can go back to the instructions too, but the page after the question can't go back to it.

## How it works

[experiment.py](experiment.py) is a plain timeline of `InfoPage` and `ModularPage` pages. A page with a Next button gets a Back button when the page before it comes straight before it in the timeline, with no code block, condition or page maker in between, both pages show every participant the same thing, and the earlier page collects no answer. So participants can reread instructions but never change an answer. The browser already has the previous page, so Back shows it at once and tells the server in the background.

The welcome page has no page before it, and the last page hides its Back button with `show_back_button=False`. See "Going back to the previous page" in the timeline documentation.
