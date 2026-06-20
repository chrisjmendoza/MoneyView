import sqlite3
from pathlib import Path

from flask import Flask, current_app, g

from .seeds import seed_defaults


def dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return {column[0]: row[index] for index, column in enumerate(cursor.description)}


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        database_path = Path(current_app.config["DATABASE_PATH"])
        database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database_path)
        connection.row_factory = dict_factory
        connection.execute("pragma foreign_keys = on")
        g.db = connection
    return g.db


def close_db(_: BaseException | None = None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db() -> None:
    schema_path = Path(current_app.root_path).parent / "db" / "schema" / "001_foundation.sql"
    database = get_db()
    database.executescript(schema_path.read_text(encoding="utf-8"))
    ensure_integrity_columns(database)
    ensure_support_tables(database)
    seed_defaults(database)
    database.commit()


def ensure_integrity_columns(database: sqlite3.Connection) -> None:
    transaction_columns = {
        row["name"]
        for row in database.execute("pragma table_info(transactions)").fetchall()
    }
    import_profile_columns = {
        row["name"]
        for row in database.execute("pragma table_info(import_profiles)").fetchall()
    }

    if "merchant" not in transaction_columns:
        database.execute("alter table transactions add column merchant text")
    if "matched_rule_id" not in transaction_columns:
        database.execute("alter table transactions add column matched_rule_id text references categorization_rules(id)")
    if "matched_rule_pattern" not in transaction_columns:
        database.execute("alter table transactions add column matched_rule_pattern text")
    if "account_column" not in import_profile_columns:
        database.execute("alter table import_profiles add column account_column text")
    if "type_column" not in import_profile_columns:
        database.execute("alter table import_profiles add column type_column text")


def ensure_support_tables(database: sqlite3.Connection) -> None:
        database.execute(
                """
                create table if not exists contacts (
                    id text primary key,
                    name text not null,
                    relationship_type text not null,
                    default_category_id text references categories(id),
                    auto_apply integer not null default 0,
                    active integer not null default 1,
                    notes text,
                    created_at text not null default current_timestamp,
                    updated_at text not null default current_timestamp,
                    check(relationship_type in ('roommate', 'friend', 'family', 'buyer_seller', 'other'))
                )
                """
        )


def init_app(app: Flask) -> None:
    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db()