# README

`AsyncCodeBlock` runs server-side work off the main request path. Use
`wait=True` when the next step depends on the result (as with the first block
here), or `wait=False` to fire work and continue immediately (as with the
second). The timing asserts in the bot test show the difference: the first block
adds about a second of wall time; the second barely does.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
