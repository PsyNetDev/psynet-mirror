Identifier separation no longer produces exports that fail to load. Removing a
recruiter identifier from a `NOT NULL` column used to leave a blank field, which
`COPY` reads back as NULL, so `psynet load` and `psynet deploy --archive` failed
on the resulting archive. Nullability is now read from the live schema:
`participant.entry_information` is written as `{}`, and an identifier belonging
to no exported participant (such as Dallinger's literal `unknown` assignment on
an error notification) is replaced by a `redacted-<table>-<row id>` placeholder
rather than blanked.
