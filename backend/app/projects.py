"""Project context and explicit, FK-backed task associations.

The project itself never creates work. Descriptions/goals are persisted context;
there is no semantic model or inferred duration in this module.
"""
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import schemas
from .database import Activity, Entity, Project, Schedule, TaskDefinition, TaskProject


def project_value(row):
    return {**row.payload, "legacy_task_id": row.legacy_snapshot.get("id", row.id) if row.legacy_snapshot else None}


def projects_list(db):
    return [project_value(row) for row in db.scalars(select(Project).order_by(Project.id))]


def task_project_ids(db):
    return {row.task_id: row.project_id for row in db.scalars(select(TaskProject))}


def enrich_tasks(db, tasks, include_inactive=False):
    by_id = {item["id"]: item for item in projects_list(db)}
    links = task_project_ids(db)
    return [{**task, "project_id": links.get(task["id"]), "project": by_id.get(links.get(task["id"])), "schedule_inactive_project": include_inactive} for task in tasks]


def context_for(db, tasks):
    links = task_project_ids(db)
    links.update({item.id: item.project_id for item in db.scalars(select(TaskDefinition))})
    return {"projects": [{**project, "task_ids": [task["id"] for task in tasks if links.get(task["id"]) == project["id"]]} for project in projects_list(db)], "interpretation": "Project metadata is planning context. Importance contributes to task priority; paused/archived projects require explicit inclusion. Project dates do not replace task deadlines. Difficulty never invents durations. Descriptions and goals are stored without AI interpretation."}


def mark_plans_stale(db, reason):
    for row in db.scalars(select(Schedule)):
        payload = dict(row.payload)
        payload.update(projects_dirty=True, status="stale")
        explanations = list(payload.get("explanations", []))
        if reason not in explanations:
            explanations.append(reason)
        payload["explanations"] = explanations
        row.payload = payload


def set_task_project(db, task_id, project_id):
    link = db.get(TaskProject, ("tasks", task_id))
    old_id = link.project_id if link else None
    if project_id == old_id:
        return
    if project_id:
        if not db.get(Project, project_id):
            raise HTTPException(422, "Selected project no longer exists")
        if link:
            link.project_id = project_id
        else:
            db.add(TaskProject(task_collection="tasks", task_id=task_id, project_id=project_id))
    elif link:
        db.delete(link)
    mark_plans_stale(db, "A task's project association changed. Regenerate this day to apply current project priorities and eligibility.")


def create_router(session):
    router = APIRouter(prefix="/api/projects", tags=["projects"])

    @router.get("")
    def list_projects(db: Session = Depends(session)):
        return projects_list(db)

    @router.get("/{project_id}")
    def get_project(project_id: str, db: Session = Depends(session)):
        row = db.get(Project, project_id)
        if not row:
            raise HTTPException(404, "Project not found")
        return project_value(row)

    def save(payload, project_id, db, row=None):
        try:
            value = schemas.Project.model_validate(payload).model_dump(mode="json")
        except ValidationError as exc:
            raise HTTPException(422, [{k: v for k, v in item.items() if k != "ctx"} for item in exc.errors()]) from exc
        if value.get("id") and value["id"] != project_id:
            raise HTTPException(422, "Project ID cannot be changed")
        value["id"] = project_id
        if row:
            related_commitments = any(item.payload.get("related_entity") == {"kind": "project", "id": project_id} for item in db.scalars(select(Activity)))
            if row.payload != value and (related_commitments or db.scalar(select(TaskProject).where(TaskProject.project_id == project_id).limit(1)) or db.scalar(select(TaskDefinition).where(TaskDefinition.project_id == project_id).limit(1))):
                mark_plans_stale(db, "Project information changed. Regenerate this day to use its current context, priority and status.")
            row.payload = value
        else:
            row = Project(id=project_id, payload=value)
            db.add(row)
        db.commit()
        return project_value(row)

    @router.post("", status_code=201)
    def add_project(payload: dict, db: Session = Depends(session)):
        if payload.get("id"):
            raise HTTPException(422, "New projects receive an ID from the server")
        return save(payload, str(uuid4()), db)

    @router.put("/{project_id}")
    def update_project(project_id: str, payload: dict, db: Session = Depends(session)):
        row = db.get(Project, project_id)
        if not row:
            raise HTTPException(404, "Project not found")
        return save(payload, project_id, db, row)

    @router.delete("/{project_id}", status_code=204)
    def delete_project(project_id: str, detach_tasks: bool = Query(default=False), db: Session = Depends(session)):
        row = db.get(Project, project_id)
        if not row:
            raise HTTPException(404, "Project not found")
        linked = list(db.scalars(select(TaskProject).where(TaskProject.project_id == project_id)))
        definitions = list(db.scalars(select(TaskDefinition).where(TaskDefinition.project_id == project_id)))
        if (linked or definitions) and not detach_tasks:
            raise HTTPException(409, "This project has linked tasks. Explicitly detach them before deleting the project; all tasks and their work will be preserved.")
        for link in linked:
            task = db.get(Entity, ("tasks", link.task_id))
            if task:
                task.payload = {**task.payload, "project_id": None}
            db.delete(link)
        for definition in definitions:
            definition.project_id = None
            definition.payload = {**definition.payload, "project_id": None}
        if linked or definitions:
            mark_plans_stale(db, "A project was deleted and its tasks were retained without a project. Regenerate this day to update priorities.")
        # Keep historical work blocks and their project snapshot intact.
        from .calendar import detach_related_entity
        detach_related_entity(db, "project", project_id)
        db.flush()
        db.delete(row)
        db.commit()
        return Response(status_code=204)

    return router
