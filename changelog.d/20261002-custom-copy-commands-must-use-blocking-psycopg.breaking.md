Experiment code that runs PostgreSQL `COPY` (for example `cursor.copy_expert`, `dallinger.postgres_copy.copy_from`, or a pandas `to_sql` COPY recipe) in a web request or background job must now wrap it in `psynet.db.blocking_psycopg()`. Otherwise psycopg2 raises `ProgrammingError`, because these processes now let other requests run during database waits. PsyNet's own export and import already do this.

```python
from psynet.db import blocking_psycopg

with blocking_psycopg():
    cursor.copy_expert("COPY my_table TO STDOUT WITH CSV HEADER", out)
```
