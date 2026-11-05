from psynet.data import SQLBase, SQLMixin, sql_base_classes


def test_every_dallinger_table_has_a_base_class():
    """Database templates and exports can contain any Dallinger table."""
    dallinger_tables = {
        mapper.local_table.name
        for mapper in SQLBase.registry.mappers
        if mapper.class_.__module__ == "dallinger.models"
    }
    assert dallinger_tables <= sql_base_classes().keys()


class CustomTableWithImportableNameLongerThanFiftyCharacters(SQLBase, SQLMixin):
    __tablename__ = "custom_table_with_long_importable_name"


def test_sqlmixin_type_column_supports_long_importable_names():
    polymorphic_identity = CustomTableWithImportableNameLongerThanFiftyCharacters.__mapper__.polymorphic_identity

    assert len(polymorphic_identity) > 50
    assert (
        CustomTableWithImportableNameLongerThanFiftyCharacters.type.type.length is None
    )
