from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from db.address_repository import build_address_list_statement, constraint_name


def test_list_statement_is_user_scoped_searchable_and_stably_sorted():
    statement = build_address_list_statement(
        user_id="00000000-0000-0000-0000-000000000001",
        search="мой дом",
        limit=20,
        offset=0,
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "address.user_id =" in sql
    assert "address.normalized_name LIKE" in sql
    assert "address.last_used_at DESC NULLS LAST" in sql
    assert "address.updated_at DESC" in sql
    assert "LIMIT 20 OFFSET 0" in sql


def test_constraint_name_finds_asyncpg_name_through_sqlalchemy_wrapper():
    driver_error = SimpleNamespace(
        diag=SimpleNamespace(constraint_name="uq_address_user_normalized_name")
    )
    adapter_error = SimpleNamespace(orig=driver_error)
    sqlalchemy_error = SimpleNamespace(orig=adapter_error)

    assert constraint_name(sqlalchemy_error) == "uq_address_user_normalized_name"


def test_constraint_name_is_cycle_safe_and_ignores_unknown_errors():
    wrapper = RuntimeError("other integrity error")
    wrapper.__cause__ = wrapper

    assert constraint_name(wrapper) is None
