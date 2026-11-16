"""Exercise real task data on a copy while preserving personal work evidence."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verify_daily_limits_migration import TABLES, readonly, rows  # noqa: E402

OUT = ROOT / 'test-results/task-relationships'
baseline = json.loads((OUT / 'baseline-summary.json').read_text(encoding='utf-8'))
backup = Path(baseline['backup'])
target = OUT / f'integrated-{datetime.now():%Y%m%d-%H%M%S}.sqlite'
with readonly(backup) as source, sqlite3.connect(target) as destination:
    source.backup(destination)
os.environ['SCHEDULE_BUILDER_OFFLINE'] = '1'
os.environ['SCHEDULE_BUILDER_ROUTE_CACHE'] = str(target.with_suffix('.routes.sqlite'))
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.database import LogicalSession, TaskChunk, TaskWeek  # noqa: E402
from backend.app.task_library import assignment_value  # noqa: E402
from backend.app.task_schemas import TaskDefinition  # noqa: E402


def body(value, **changes):
    return {**{key: item for key, item in value.items() if key in TaskDefinition.model_fields}, **changes}


def ledger(db):
    return {'sessions': sorted((s.id, s.assignment_id, s.target_minutes, s.completed_minutes,
                               s.baseline_completed_minutes, s.status) for s in db.scalars(select(LogicalSession))),
            'chunks': sorted((c.id, c.logical_session_id, c.start, c.end, c.credited_minutes, c.status)
                             for c in db.scalars(select(TaskChunk)))}


with TestClient(create_app(target)) as client:
    state = client.get('/api/state').json()
    definitions = state['task_definitions']
    before = json.loads((OUT / 'before-state.json').read_text(encoding='utf-8'))
    for old in before['task_definitions']:
        current = next(task for task in definitions if task['id'] == old['id'])
        assert (current['course'], current['related_activity_id']) == (old['course'], old['related_activity_id'])
    legacy_text = next(task for task in definitions if task.get('course') and task.get('related_activity_id'))
    edit = body(legacy_text)
    edit.pop('course')
    response = client.put(f"/api/task-definitions/{legacy_text['id']}", json=edit)
    response.raise_for_status()
    assert response.json()['course'] == legacy_text['course']
    assert response.json()['related_activity_id'] == legacy_text['related_activity_id']

    response = client.post('/api/schedules/generate', json={'date': '2026-11-13'})
    response.raise_for_status()
    linked = [item for item in response.json()['task_week_context']['definitions'] if item.get('related_activity_id')]
    assert linked and all(item['related_activity']['id'] == item['related_activity_id'] for item in linked)
    assert any(item['related_activity']['occurrences'] for item in linked)

    gym = next(task for task in definitions if task['title'] == 'Gym')
    response = client.post('/api/task-weeks', json={'task_definition_id': gym['id'], 'week_start': '2026-11-15', 'min_sessions_per_week': 1})
    response.raise_for_status()
    assignment_id = response.json()['id']
    response = client.post('/api/schedules/generate', json={'date': '2026-11-21'})
    response.raise_for_status()
    assert not response.json()['conflicts']
    week = client.get('/api/task-week?week_start=2026-11-15').json()
    allocation = next(item for item in week['assignments'] if item['id'] == assignment_id)
    assert allocation['allocated_sessions'] >= 1 and allocation['target_met']
    assert allocation['completed_sessions'] == 0 and allocation['completed_minutes'] == 0
    assert allocation['effective_definition']['status'] == 'active'
    with client.app.state.session_factory() as db:
        row = db.get(TaskWeek, assignment_id)
        elapsed = assignment_value(row, list(db.scalars(select(LogicalSession))), list(db.scalars(select(TaskChunk))),
                                   now=datetime(2031, 1, 1, tzinfo=timezone.utc))
        evidence_before = ledger(db)
    assert elapsed['elapsed_scheduled_minutes'] >= gym['session_minutes']
    assert elapsed['completed_minutes'] == 0 and elapsed['status'] != 'completed'
    for status in ('completed', 'active'):
        response = client.put(f"/api/task-definitions/{gym['id']}", json=body(gym, status=status))
        response.raise_for_status()
        assert response.json()['status'] == status
        with client.app.state.session_factory() as db:
            assert ledger(db) == evidence_before

with readonly(backup) as original, readonly(ROOT / 'data/schedule_builder.db') as current:
    for table in TABLES:
        assert rows(original, table) == rows(current, table), f'Personal data changed: {table}'
    assert current.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not current.execute('PRAGMA foreign_key_check').fetchall()
evidence = {'database_copy': str(target), 'preserved_course_records': baseline['course_records'],
            'preserved_related_records': baseline['related_records'], 'linked_context_count': len(linked),
            'allocated_sessions': allocation['allocated_sessions'], 'target_met': allocation['target_met'],
            'elapsed_minutes_at_test_clock': elapsed['elapsed_scheduled_minutes'], 'verified_completion_minutes': 0,
            'explicit_lifecycle_preserved_ledger': True, 'personal_data_unchanged': True}
(OUT / 'integration-summary.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
print(json.dumps(evidence, indent=2))
