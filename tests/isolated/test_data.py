from psynet.data import SQLBase, SQLMixin


class CustomTableWithImportableNameLongerThanFiftyCharacters(SQLBase, SQLMixin):
    __tablename__ = "custom_table_with_long_importable_name"


def test_sqlmixin_type_column_supports_long_importable_names():
    polymorphic_identity = CustomTableWithImportableNameLongerThanFiftyCharacters.__mapper__.polymorphic_identity

    assert len(polymorphic_identity) > 50
    assert (
        CustomTableWithImportableNameLongerThanFiftyCharacters.type.type.length is None
    )
