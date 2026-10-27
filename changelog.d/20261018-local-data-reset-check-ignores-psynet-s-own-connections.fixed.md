`psynet load` no longer counts database connections that PsyNet itself still holds as other clients of the local database, unless they lock a table that loading would drop.
