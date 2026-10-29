import dallinger.data

from psynet.data import sql_base_classes


def test_every_dallinger_table_has_a_model():
    """Launching loads the database template, which holds every table Dallinger exports."""
    classes = sql_base_classes()
    assert set(dallinger.data.table_names) <= set(classes)
    for name in dallinger.data.table_names:
        assert classes[name].__tablename__ == name
