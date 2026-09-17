# README

`wait_while` preserves the current page with a compact waiting indicator until
its condition becomes false. Framework events wake the browser promptly;
`check_interval` remains the fallback for arbitrary conditions such as the
time-based example here. `expected_wait` controls progress estimation, while
actual visible waiting time determines time credit by default.

Pass `wait_page=WaitPage` explicitly when a dedicated waiting screen is
preferred.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
