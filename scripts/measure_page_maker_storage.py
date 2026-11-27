"""Measure generated PageMaker payloads and their physical PostgreSQL footprint.

Run in a PsyNet development environment: PGDATABASE=postgres python scripts/measure_page_maker_storage.py
The connection uses libpq's normal settings. Only a temporary table is written.
"""

import random
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg2
from psycopg2.extras import execute_values

from psynet import deployment_info
from psynet.modular_page import AudioPrompt, ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.page_maker_visit import PageMakerVisit
from psynet.timeline import PageMaker


def audio_page():
    return ModularPage(
        "melody",
        AudioPrompt("/static/item.wav", "Which melody differs?"),
        PushButtonControl([1, 2, 3]),
        time_estimate=5,
    )


def measure(cursor, name, make_pages, participants):
    maker = PageMaker(make_pages, time_estimate=5)
    path = ["main", 2]
    rows = []
    for pid in range(participants):
        p = SimpleNamespace(
            id=pid, module_state=None, elt_id=path, _page_maker_visits={}
        )
        PageMakerVisit.enter(maker, None, p)
        rows.append((pid, 2, '["main", 2]', p._page_maker_visits[2].payload))

    cursor.execute("TRUNCATE pg_temp.visit_size")
    cursor.execute("SELECT pg_total_relation_size('pg_temp.visit_size')")
    empty = cursor.fetchone()[0]
    insert = (
        "INSERT INTO pg_temp.visit_size(participant_id,depth,path,payload) VALUES %s"
    )
    execute_values(cursor, insert, rows)
    cursor.execute("""SELECT avg(octet_length(payload))::bigint,
                      pg_total_relation_size('pg_temp.visit_size') FROM pg_temp.visit_size""")
    payload, allocated = cursor.fetchone()
    cursor.execute("DELETE FROM pg_temp.visit_size")
    cursor.execute(
        "SELECT count(*), pg_total_relation_size('pg_temp.visit_size') FROM pg_temp.visit_size"
    )
    remaining, after_exit = cursor.fetchone()
    cursor.execute("VACUUM (TRUNCATE FALSE) pg_temp.visit_size")
    execute_values(cursor, insert, rows)
    cursor.execute("SELECT pg_total_relation_size('pg_temp.visit_size')")
    refilled = cursor.fetchone()[0]
    print(
        f"{name:25} {participants:5} {payload:10} {allocated - empty:11} "
        f"{remaining:7} {after_exit - empty:11} {refilled - empty:11}"
    )


def main():
    # Keep this benchmark's deployment metadata apart from any live experiment.
    with (
        tempfile.TemporaryDirectory() as directory,
        closing(psycopg2.connect("")) as connection,
    ):
        connection.autocommit = True
        deployment_info.path = str(Path(directory) / "deployment_info.json")
        deployment_info.write_all({"secret": uuid4()})
        media = random.Random(17).randbytes(1024 * 1024)

        def captured_media():
            page = audio_page()
            page.bot_response = lambda: len(media)
            return page

        with connection.cursor() as cursor:
            cursor.execute("""CREATE TEMP TABLE visit_size (
                id serial PRIMARY KEY, participant_id integer NOT NULL, depth integer NOT NULL,
                path json NOT NULL, payload bytea NOT NULL, UNIQUE (participant_id, depth))""")
            print(
                "case                       users    B/visit   DB growth    rows  after exit      refill"
            )
            for name, factory, n in [
                ("information", lambda: InfoPage("Welcome"), 100),
                ("audio URL + choices", audio_page, 100),
                (
                    "100 generated pages",
                    lambda: [InfoPage(str(i), time_estimate=1) for i in range(100)],
                    100,
                ),
                ("1 MiB captured bytes", captured_media, 10),
            ]:
                measure(cursor, name, factory, n)


if __name__ == "__main__":
    main()
