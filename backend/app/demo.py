"""Explicit, repeatable additive demo data; never clears personal records."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .database import Configuration, Entity, Project, TaskProject
from sqlalchemy import select
from .schemas import Class, Location, Project as ProjectInput, Task


def seed_demo(db, settings):
    empty_workspace = db.scalar(select(Entity).limit(1)) is None
    tomorrow = (datetime.now(ZoneInfo(settings["timezone"])) + timedelta(days=1)).date()
    locations = [
        Location(id="demo-home", name="Home / residence", lat=43.4772, lon=-80.5489),
        Location(id="demo-dc", name="Davis Centre, University of Waterloo", lat=43.4728, lon=-80.5420),
        Location(id="demo-library", name="Dana Porter Library", lat=43.4698, lon=-80.5423),
    ]
    classes = [
        Class(id="demo-cs", title="CS 246 · Object-oriented software", class_type="Lecture", weekdays=[0, 2, 4], start_time="09:00", end_time="10:20", location_id="demo-dc", building="Davis Centre", room="1350"),
        Class(id="demo-math", title="MATH 239 · Combinatorics", class_type="Tutorial", weekdays=[1, 3], start_time="10:00", end_time="11:20", location_id="demo-library", building="Dana Porter", room="Study room"),
    ]
    tasks = [
        Task(id="demo-assignment", title="CS assignment · implementation", duration_minutes=120, remaining_minutes=120, priority=5, deadline=datetime.combine(tomorrow, datetime.min.time()).replace(hour=20, tzinfo=ZoneInfo(settings["timezone"])), location_id="demo-dc", notes="Implement and test the remaining requirements."),
        Task(id="demo-prep", title="Review lecture notes", duration_minutes=50, remaining_minutes=50, priority=4, location_id="demo-library"),
        Task(id="demo-project", title="Build my portfolio", kind="project", duration_minutes=90, remaining_minutes=90, priority=2, location_id="demo-home", notes="Ship one useful improvement."),
    ]
    for collection, records in [("locations", locations), ("classes", classes), ("tasks", tasks)]:
        for record in records:
            if not db.get(Entity, (collection, record.id)):
                db.add(Entity(collection=collection, id=record.id, payload=record.model_dump(mode="json")))
    db.flush()
    # This explicit additive demo includes a container and a real work task.
    if not db.get(TaskProject, ("tasks", "demo-project")):
        project_id = "demo-portfolio"
        if not db.get(Project, project_id):
            project = ProjectInput(id=project_id, name="Personal portfolio", category="software", importance=4, description="A home for selected work and useful experiments.")
            db.add(Project(id=project_id, payload=project.model_dump(mode="json")))
            db.flush()
        db.add(TaskProject(task_collection="tasks", task_id="demo-project", project_id=project_id))
        work = db.get(Entity, ("tasks", "demo-project"))
        work.payload = {**work.payload, "project_id": project_id}
    if empty_workspace and not settings.get("default_location_id"):
        row = db.get(Configuration, "settings")
        row.payload = {**settings, "default_location_id": "demo-home"}
