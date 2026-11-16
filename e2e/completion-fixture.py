"""Insert explicitly labeled saved-plan fixtures into this run's isolated QA DB.

These are not generated schedules and provide no solver verification evidence.
Definitions and assignments are created through the real API first.
"""
import json
import sqlite3
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
database = Path(sys.argv[1]).resolve()
if database.parent != root / "test-results" or not database.name.startswith("completion-e2e-") or database.suffix != ".sqlite":
    raise SystemExit("Refusing a database outside the isolated completion QA run")
value = json.load(sys.stdin)
with sqlite3.connect(database) as connection:
    connection.execute("PRAGMA foreign_keys=ON")
    for plan in value["plans"]:
        if plan["solver_status"] != "SEEDED_QA_FIXTURE_NOT_GENERATED":
            raise SystemExit("Fixtures must explicitly identify their provenance")
        connection.execute("INSERT INTO schedules(id,date,payload) VALUES(?,?,?)", (plan["id"], plan["date"], json.dumps(plan)))
    for session in value["sessions"]:
        connection.execute('INSERT INTO logical_sessions(id,assignment_id,"index",target_minutes,completed_minutes,baseline_completed_minutes,status) VALUES(?,?,?,?,0,0,?)', (session["id"], session["assignment_id"], session["index"], session["target_minutes"], "todo"))
    for plan in value["plans"]:
        for block in plan["blocks"]:
            if block.get("logical_session_id"):
                connection.execute("INSERT INTO task_chunks(id,logical_session_id,schedule_id,start,end,status,credited_minutes) VALUES(?,?,?,?,?,?,0)", (block["id"], block["logical_session_id"], plan["id"], block["start"], block["end"], block["status"]))
