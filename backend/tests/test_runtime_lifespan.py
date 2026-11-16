"""Ensure SQLite handles are released on normal and failed app lifespans."""
import asyncio

import pytest

from backend.app import main


@pytest.mark.parametrize("failure", [None, "startup", "lifespan"])
def test_database_pool_disposed_when_lifespan_ends(tmp_path, monkeypatch, failure):
    app = main.create_app(tmp_path / "lifecycle.sqlite")
    engine = app.state.engine
    disposed = []
    original = engine.dispose

    def dispose():
        disposed.append(True)
        original()

    monkeypatch.setattr(engine, "dispose", dispose)
    if failure == "startup":
        def failed_migration(_):
            raise RuntimeError("startup failed")
        monkeypatch.setattr(main, "migrate", failed_migration)

    async def run():
        async with app.router.lifespan_context(app):
            if failure == "lifespan":
                raise RuntimeError("lifespan failed")

    if failure:
        with pytest.raises(RuntimeError, match=f"{failure} failed"):
            asyncio.run(run())
    else:
        asyncio.run(run())
    assert disposed == [True]
