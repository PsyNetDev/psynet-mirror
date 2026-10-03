Data exports no longer include empty table CSVs. An experiment that never used
chat, Lucid, or barriers therefore no longer has header-only files such as
`chat_message.csv` in `database/`. `manifest.json` still lists every table under
`table_row_counts`, with a count of `0` for the omitted files, and `psynet load`
and `--archive` skip tables whose CSV is absent. Analysis code that loops over
table names and reads `database/<table>.csv` unconditionally should consult
`table_row_counts` first, or tolerate a missing file.
