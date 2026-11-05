# README

An ultimatum game played in teams. Players wait in a lobby until a team
forms, or start in a smaller team if nobody else arrives in time. Every
round, the team is randomly re-paired into proposers and responders, an odd
player out sits out, and slow players miss a round rather than holding up
their partner or being failed. Players who switch to another tab are not
paired until they come back.

Good reference for nesting a `Regrouper` inside persistent teams made by a
`SimpleGrouper` with `start_short_after` and top-ups, with a custom
`form_groups` that avoids repeat partners and an `on_release` that counts the
team's rounds.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).
