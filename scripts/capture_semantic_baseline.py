"""Capture equivalent real inputs and replay the preserved pre-change solver."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'test-results/semantic-location'
summary = json.loads((OUT / 'baseline-summary.json').read_text(encoding='utf-8'))
target = OUT / 'baseline-replay.sqlite'
with sqlite3.connect(f'file:{Path(summary["backup"]).as_posix()}?mode=ro', uri=True) as source, sqlite3.connect(target) as destination:
    source.backup(destination)
os.environ['SCHEDULE_BUILDER_OFFLINE'] = '1'
os.environ['SCHEDULE_BUILDER_ROUTE_CACHE'] = str(OUT / 'baseline-routes.sqlite')

from fastapi.testclient import TestClient  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app import scheduler  # noqa: E402

spec = importlib.util.spec_from_file_location('backend.app.semantic_baseline', ROOT / 'test-results/semantic-baseline/scheduler.py')
baseline = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = baseline
spec.loader.exec_module(baseline)
places = json.loads((OUT / 'before-state.json').read_text(encoding='utf-8'))['locations']


def capture(date, settings, classes, tasks, blocks, route_minutes, mode='balanced', now=None):
    routes = [{'origin': a['id'], 'destination': b['id'], 'minutes': route_minutes(a['id'], b['id'])} for a in places for b in places if a['id'] != b['id']]
    values = dict(date=date, settings=settings, classes=classes, tasks=tasks, blocks=blocks, mode=mode, now=now, routes=routes)
    (OUT / 'actual-solver-inputs.json').write_text(json.dumps(values, indent=2), encoding='utf-8')
    result = baseline.generate_schedule(date, settings, classes, tasks, blocks, route_minutes, mode, now)
    (OUT / 'actual-baseline-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


scheduler.generate_schedule = capture
with TestClient(create_app(target)) as client:
    response = client.post('/api/schedules/generate', json={'date': '2026-11-13', 'reoptimize': False})
    response.raise_for_status()
    result = response.json()
    (OUT / 'actual-baseline-plan.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'status': result.get('solver_status'), 'first_event': result['blocks'][0]['start'], 'first_work': next(b['start'] for b in result['blocks'] if b['kind'] in {'task', 'project'}), 'work_minutes': result.get('summary', {})}, indent=2))
