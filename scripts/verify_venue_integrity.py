"""Verify real Gym data on an isolated copy without changing personal plans."""
import json
import os
from pathlib import Path
import sqlite3
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verify_daily_limits_migration import TABLES, readonly, rows  # noqa: E402


def main():
    backup = ROOT / 'data/backups/pre-venue-integrity-20261112.sqlite'
    target = ROOT / 'test-results' / f'venue-clone-{datetime.now():%Y%m%d-%H%M%S}.sqlite'
    with readonly(backup) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    os.environ['SCHEDULE_BUILDER_OFFLINE'] = '1'
    os.environ['SCHEDULE_BUILDER_ROUTE_CACHE'] = str(target.with_suffix('.routes.sqlite'))
    from fastapi.testclient import TestClient
    from backend.app.main import create_app
    with TestClient(create_app(target)) as client:
        state = client.get('/api/state').json()
        gym = next(t for t in state['task_definitions'] if t['title'] == 'Gym')
        pac = next(p for p in state['locations'] if p['id'] == gym['location_id'])
        assert pac['name'] == 'Physical Activities Complex'
        before = next(s for s in state['schedules'] if s['date'] == '2026-11-13')
        assert before.get('needs_regeneration') or before.get('status') == 'stale', before
        response = client.post('/api/schedules/generate', json={'date': '2026-11-13', 'reoptimize': True})
        assert response.status_code == 200, response.text
        plan = response.json()
        blocks = [b for b in plan['blocks'] if b.get('task_definition_id') == gym['id']]
        assert blocks, plan
        assert all(b['location_id'] == pac['id'] and b.get('resolved_location_id') == pac['id'] for b in blocks), blocks
        stored = client.get('/api/schedules?date=2026-11-13').json()
        persisted = next(s for s in stored if s['id'] == plan['id'])
        assert [b for b in persisted['blocks'] if b.get('task_definition_id') == gym['id']] == blocks
        evidence = {'original_plan_status': before.get('status'), 'definition': gym,
                    'gym_blocks': blocks, 'travel': [b for b in plan['blocks'] if b['kind'] == 'travel'],
                    'solver_status': plan.get('solver_status'), 'clone': str(target)}
    with readonly(backup) as old, readonly(ROOT / 'data/schedule_builder.db') as current:
        for table in TABLES:
            assert rows(old, table) == rows(current, table), f'Personal data changed: {table}'
        assert current.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not current.execute('PRAGMA foreign_key_check').fetchall()
    evidence['personal_data_unchanged'] = True
    (ROOT / 'test-results/venue-integrity-after.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print('Real Gym clone: stale plan detected; regenerated Gym at PAC; personal records unchanged.')


if __name__ == '__main__':
    main()
