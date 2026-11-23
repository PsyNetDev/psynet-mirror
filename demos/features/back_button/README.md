# Back button

Run `psynet debug local` in this directory. Click through three instruction pages, going back and forth with Back and Next. Then answer two questions, and go back from the second to change your first answer. The last page shows the answers that were kept.

## How it works

[experiment.py](experiment.py) is a plain timeline of `InfoPage` and `ModularPage` pages. A page gets a Back button when the page before it comes straight before it in the timeline, with no code block, condition or page maker in between, and both pages show every participant the same thing. The browser already has the previous page, so Back shows it at once and tells the server in the background. Answering a page again replaces its saved answer.

The welcome page has no page before it, the summary is built by a `PageMaker`, and the page before it hides its Back button with `show_back_button=False`. See "Going back to the previous page" in the timeline documentation.
