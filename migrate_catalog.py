"""Apply the additive schema required after merging the two repositories."""
import os
from sqlalchemy import create_engine, inspect, text
from config.settings import DATABASE_URL
from routers.catalog import CatalogEntry


SOCIAL_COLUMNS = {
    "products": ("facebook_post_id", "instagram_post_id"),
    "settings": (
        "facebook_page_id", "facebook_page_name", "facebook_page_access_token",
        "facebook_app_id", "facebook_app_secret", "instagram_business_account_id",
    ),
}


def migrate(connection):
    """Create missing objects only; existing rows and columns are preserved."""
    changes = []
    if not inspect(connection).has_table("catalog_entries"):
        CatalogEntry.__table__.create(connection)
        changes.append("catalog_entries")
    for table, required in SOCIAL_COLUMNS.items():
        inspector = inspect(connection)
        if not inspector.has_table(table):
            continue
        columns = {c["name"] for c in inspector.get_columns(table)}
        for column in required:
            if column not in columns:
                connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" TEXT'))
                changes.append(f"{table}.{column}")
    return changes


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Validate PostgreSQL DDL and roll it back")
    args = parser.parse_args()
    url = os.getenv("DATABASE_URL_UNPOOLED") or DATABASE_URL.replace("-pooler.", ".", 1)
    migration_engine = create_engine(url, connect_args={"connect_timeout": 10} if url.startswith("postgresql") else {})
    with migration_engine.connect() as connection:
        transaction = connection.begin()
        try:
            if connection.dialect.name == "postgresql":
                connection.execute(text("SET LOCAL lock_timeout = '5s'"))
                connection.execute(text("SET LOCAL statement_timeout = '30s'"))
            changes = migrate(connection)
            if args.dry_run:
                transaction.rollback()
                print("Validated and rolled back:", ", ".join(changes) or "schema already current")
            else:
                transaction.commit()
                print("Schema ready:", ", ".join(changes) or "already current")
        except BaseException:
            transaction.rollback()
            raise
    migration_engine.dispose()
