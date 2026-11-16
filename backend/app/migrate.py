"""Run safe Alembic upgrades: python -m backend.app.migrate."""
from pathlib import Path

from alembic import command
from alembic.config import Config

from .database import build_database


def migrate(engine):
    configuration = Config()
    configuration.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    with engine.begin() as connection:
        configuration.attributes["connection"] = connection
        command.upgrade(configuration, "head")


if __name__ == "__main__":
    engine, _ = build_database()
    migrate(engine)
    engine.dispose()
    print("Database migrations complete.")
