# README

Experiments can back up selected data to remote artifact storage (here S3) for
later analysis or dashboard use. This demo wires `S3ArtifactStorage`, enables
`automatic_backups` even in debug mode, and defines `get_basic_data` so trials
and participants are included in those snapshots. The timeline itself is a short
consent-plus-headphone-test stub so the focus stays on the storage setup.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
