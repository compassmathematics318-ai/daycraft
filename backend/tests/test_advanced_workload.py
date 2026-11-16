"""Independent hard-feasibility checks for advanced workload calibration."""
from datetime import datetime

import pytest

from backend.app.scheduler import generate_schedule, validate_blocks

DATE = '2026-11-13'
LEVELS = ('very_low', 'low', 'medium', 'high', 'very_high')
BASE = dict(timezone='America/Toronto', wake_time='07:00', sleep_time='00:00',
            work_start='08:00', work_end='23:30', break_minutes=0,
            travel_buffer_minutes=0, focus_minutes=50, default_location_id='home',
            meals=[], solver_seconds=2)


def task(split=False):
    return dict(id='work', title='Project session', kind='academic',
                remaining_minutes=120, duration_minutes=120, priority=5,
                splittable=split, min_session_minutes=30, max_session_minutes=120,
                dependencies=[], status='todo', location_id='home', weekly_value=1500,
                task_definition_id='definition', logical_session_id='session')


def minutes(block):
    return round((datetime.fromisoformat(block['end']) - datetime.fromisoformat(block['start'])).total_seconds() / 60)


@pytest.mark.parametrize('level', LEVELS)
def test_unsplittable_session_cannot_be_packed_into_two_short_gaps(level):
    settings = {**BASE, 'work_end': '11:00', 'workload_level': level}
    anchor = dict(id='middle', title='Fixed appointment', date=DATE,
                  start_time='09:00', end_time='10:00', location_id='home')
    unsplit = generate_schedule(DATE, settings, [anchor], [task()], [], lambda a, b: 0, 'balanced')
    split = generate_schedule(DATE, settings, [anchor], [task(True)], [], lambda a, b: 0, 'balanced')
    assert not [block for block in unsplit['blocks'] if block.get('task_id')]
    assert sum(minutes(block) for block in split['blocks'] if block.get('task_id')) == 120
    for result, candidate in ((unsplit, task()), (split, task(True))):
        assert not validate_blocks(result['blocks'], settings, lambda a, b: 0, [candidate])
        fixed = [block for block in result['blocks'] if block.get('class_id') == 'middle']
        assert fixed and sum(minutes(block) for block in fixed) == 60


@pytest.mark.parametrize('cutoff, expected', [('22:30', 60), ('23:30', 120)])
@pytest.mark.parametrize('level', ['high', 'very_high'])
def test_explicit_cutoff_changes_usable_evening_capacity(cutoff, expected, level):
    settings = {**BASE, 'work_start': '21:30', 'work_end': cutoff, 'workload_level': level}
    candidate = task(True)
    result = generate_schedule(DATE, settings, [], [candidate], [], lambda a, b: 0, 'balanced')
    blocks = [block for block in result['blocks'] if block.get('task_id')]
    assert sum(minutes(block) for block in blocks) == expected
    assert all(block['end'] <= f'{DATE}T{cutoff}:00-05:00' for block in blocks)
    assert not validate_blocks(result['blocks'], settings, lambda a, b: 0, [candidate])


def test_ambitious_profiles_offer_future_work_without_rewriting_task_facts():
    """Capacity forecasting must not hide feasible optional work from today's solver."""
    from copy import deepcopy

    from backend.app.weekly_scheduler import prepare_weekly_tasks

    definitions = [dict(id=f'd{i}', title=f'Project {i}', task_type='academic',
                        session_minutes=60, importance=10-i, difficulty=5,
                        allow_splitting=False, dependencies=[], location_id='home',
                        min_sessions_per_day=0) for i in range(3)]
    assignments = [dict(id=f'a{i}', task_definition_id=f'd{i}', week_start='2026-11-08',
                        min_sessions_per_week=2, status='todo') for i in range(3)]
    context = {'days': [{'date': DATE, 'capacity_minutes': 900},
                        {'date': '2026-11-14', 'capacity_minutes': 900}], 'chunks': []}
    original = deepcopy((definitions, assignments, context))
    amounts = []
    for level in ('medium', 'high', 'very_high'):
        prepared = prepare_weekly_tasks(DATE, {**BASE, 'workload_level': level},
                                        definitions, assignments, [], context)
        amounts.append(sum(unit['remaining_minutes'] for unit in prepared['tasks']))
        if level != 'medium':
            opportunities = [unit for unit in prepared['tasks'] if unit.get('weekly_opportunity')]
            assert opportunities
            assert all(unit['remaining_minutes'] >= unit['weekly_planned_minutes'] for unit in opportunities)
            assert all(unit['session_target_minutes'] == 60 for unit in opportunities)
        assert (definitions, assignments, context) == original
    assert amounts[0] < amounts[1] < amounts[2]


def test_default_search_policy_scales_only_for_complex_days(monkeypatch):
    """Default UI generation reports its bounded portfolio; explicit budgets stay separate."""
    monkeypatch.setattr('backend.app.scheduler.os.cpu_count', lambda: 2)
    settings = {key: value for key, value in BASE.items() if key != 'solver_seconds'}
    settings.update(work_end='12:00', workload_level='very_high')
    simple = generate_schedule(DATE, settings, [], [task()], [], lambda a, b: 0, 'balanced')
    assert simple['stats']['configured_solver_seconds'] == 8
    assert simple['stats']['search_workers'] == 1
    assert simple['stats']['solver_budget_policy'] == 'simple_day'
    tasks = [{**task(), 'id': f't{i}', 'logical_session_id': f's{i}',
              'task_definition_id': f'd{i}', 'duration_minutes': 30,
              'remaining_minutes': 30, 'max_session_minutes': 30} for i in range(5)]
    anchors = [dict(id=f'a{i}', title=f'Fixed {i}', date=DATE,
                    start_time=f'08:{i*10:02}', end_time=f'08:{i*10+5:02}',
                    location_id='home') for i in range(5)]
    complex_day = generate_schedule(DATE, settings, anchors, tasks, [], lambda a, b: 0, 'balanced')
    assert complex_day['stats']['configured_solver_seconds'] == 20
    assert complex_day['stats']['search_workers'] == 2
    assert complex_day['stats']['solver_budget_policy'] == 'interactive_portfolio'
    assert complex_day['stats']['parallel_search_nondeterministic']
    assert not validate_blocks(complex_day['blocks'], settings, lambda a, b: 0, tasks)
