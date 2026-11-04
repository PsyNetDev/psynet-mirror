# README

This demo records the participant's camera in the background while they answer
ordinary button pages, using `background_recording=VideoRecordConfig(...)`. It
runs one trial whose clip is optional and one whose clip is required: a missing
optional clip is stored as unavailable without affecting the trial, whereas a
missing required clip fails its trial. Answers are saved immediately in both
cases; on a slow connection, a later recording page may wait for earlier
uploads. After taking part, open the Recordings dashboard to see each clip's
outcome.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
