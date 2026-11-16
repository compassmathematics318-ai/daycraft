"""Replay personal data in isolation and verify the original remains unchanged."""
import json
import os
from datetime import datetime
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verify_daily_limits_migration import TABLES, readonly, rows  # noqa: E402

OUT = ROOT / 'test-results/semantic-location'
snapshot = json.loads((OUT / 'baseline-summary.json').read_text(encoding='utf-8'))
backup = Path(snapshot['backup'])
target = OUT / f'integrated-{datetime.now():%Y%m%d-%H%M%S}.sqlite'
with readonly(backup) as source, sqlite3.connect(target) as destination:
    source.backup(destination)
os.environ['SCHEDULE_BUILDER_OFFLINE'] = '1'
os.environ['SCHEDULE_BUILDER_ROUTE_CACHE'] = str(target.with_suffix('.routes.sqlite'))
from fastapi.testclient import TestClient  # noqa: E402
from backend.app.main import create_app  # noqa: E402

with TestClient(create_app(target)) as client:
    old = next(plan for plan in client.get('/api/schedules').json() if plan['date'] == '2026-11-13')
    assert old['status'] == 'stale' and old['needs_regeneration']
    response = client.post('/api/schedules/generate', json={'date': '2026-11-13', 'reoptimize': False})
    response.raise_for_status()
    plan = response.json()
    assert plan['location_intelligence_version'] == 1
    assert not plan['conflicts'], plan['conflicts']
    work = [b for b in plan['blocks'] if b['kind'] in {'task', 'project', 'personal'}]
    productive = sum((datetime.fromisoformat(b['end']) - datetime.fromisoformat(b['start'])).total_seconds() / 60 for b in work)
    assert productive == 315, productive
    assert min(b['start'] for b in work) < '2026-11-13T12:00:00-05:00'
    gym = next(b for b in work if b['title'] == 'Gym')
    assert gym['location_id'] == gym['resolved_location_id'] == 'b93f270f-a8c3-49c5-aad0-aedc56780aa5'
    for block in work:
        if block.get('location_mode') == 'required':
            assert block['resolved_location_id'] == block['location_id']
        elif block.get('location_mode') == 'preferred':
            assert block['resolved_location_id'] in [c['location_id'] for c in block['location_suitability']['candidates']]
    stored = next(item for item in client.get('/api/schedules').json() if item['id'] == plan['id'])
    assert stored['blocks'] == plan['blocks']
    evidence = {'first_work': min(b['start'] for b in work), 'productive_minutes': productive,
                'gym': gym, 'stats': plan.get('stats'), 'solver_status': plan['solver_status'],
                'travel': [b for b in plan['blocks'] if b['kind'] == 'travel'], 'database_copy': str(target)}
    (OUT / 'integrated-plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')

with readonly(backup) as original, readonly(ROOT / 'data/schedule_builder.db') as current:
    for table in TABLES:
        assert rows(original, table) == rows(current, table), f'Personal records changed: {table}'
    assert current.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not current.execute('PRAGMA foreign_key_check').fetchall()
evidence['personal_data_unchanged'] = True
(OUT / 'integrated-summary.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
print(f"Integrated personal-data copy: first work {evidence['first_work']}, {productive:g} productive minutes, Gym at PAC, personal database unchanged.")
