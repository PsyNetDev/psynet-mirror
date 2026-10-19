# README

Bots automate participant responses so you can test timelines without a browser.
Responses can be a fixed `bot_response` value, a callable that samples randomly,
or a custom control that implements `get_bot_response`. This walkthrough shows
all three patterns on successive text pages, then ends "bad" participants via a
conditional (actual bot runs live in the associated tests).

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
