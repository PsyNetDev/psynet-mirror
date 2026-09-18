# README

This demo shows how to expose Python functions and page methods to front-end
JavaScript with `@expose_to_api`. Custom APIs are useful when the browser needs
to call server-side logic mid-page — for example validation, random generation,
or fetching dynamic content — without advancing the timeline. In this example, a
custom page asks the server for a random digit and checks the participant's
response against it. Similar logic could be used for live feedback, partial
form validation, or any interactive page that needs a round-trip to Python.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
