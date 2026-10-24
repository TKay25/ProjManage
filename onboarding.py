"""A first-run checklist, shaped by who the account is.

New accounts used to land on a dashboard of zeroes with no obvious next step.
The checklist names the four or five things that make a workspace useful, ticks
itself off from real data, and disappears once it is done or dismissed.
"""

from auth import accessible_projects, runs_build
from db import query


def _count(sql: str, args) -> int:
    row = query(sql, args, one=True)
    return int((row or {}).get("total") or 0)


def steps_for(user) -> list[dict]:
    if not user:
        return []

    projects = accessible_projects(user)
    ids = [project["id"] for project in projects]
    has_projects = bool(ids)

    if not has_projects:
        transactions = documents = agreements = managers = 0
        placeholders = None
    else:
        placeholders = ",".join("?" for _ in ids)
        transactions = _count(
            f"SELECT COUNT(*) AS total FROM transactions WHERE project_id IN ({placeholders})",
            ids,
        )
        documents = _count(
            f"SELECT COUNT(*) AS total FROM attachments WHERE project_id IN ({placeholders})",
            ids,
        )
        agreements = _count(
            f"""SELECT COUNT(*) AS total FROM agreements
                WHERE project_id IN ({placeholders}) AND status = 'signed'""",
            ids,
        )
        managers = _count(
            f"""SELECT COUNT(*) AS total FROM projects
                WHERE id IN ({placeholders}) AND manager_id IS NOT NULL""",
            ids,
        )

    does_build = runs_build(user)
    steps = []

    if does_build:
        steps.append(
            {
                "key": "project",
                "title": "Create your first project",
                "hint": "Stand, budget and target date. The 19 build stages are laid out for you.",
                "href": "/app/projects",
                "cta": "New project",
                "done": has_projects,
            }
        )
        steps.append(
            {
                "key": "team",
                "title": "Put a person on the build",
                "hint": "Assign yourself or invite the manager who will run it on the ground.",
                "href": "/app/settings#team",
                "cta": "Manage team",
                "done": managers > 0,
            }
        )
        steps.append(
            {
                "key": "money",
                "title": "Record the first deposit or expense",
                "hint": "The balance only means something once real movements are in the ledger.",
                "href": "/app/money",
                "cta": "Record money",
                "done": transactions > 0,
            }
        )
        steps.append(
            {
                "key": "documents",
                "title": "Upload a plan or a receipt",
                "hint": "Proof filed against the build, not lost in a camera roll.",
                "href": "/app/documents",
                "cta": "Upload",
                "done": documents > 0,
            }
        )
        steps.append(
            {
                "key": "agreement",
                "title": "Agree the scope and payment milestones",
                "hint": "One signed record both sides can point at.",
                "href": "/app/agreements",
                "cta": "Build an agreement",
                "done": agreements > 0,
            }
        )
    else:
        steps.append(
            {
                "key": "project",
                "title": "Your build appears here",
                "hint": "Your build manager files the project against your email; it shows up the moment they do.",
                "href": "/app/projects",
                "cta": "Open projects",
                "done": has_projects,
            }
        )
        steps.append(
            {
                "key": "team",
                "title": "Know who is running it",
                "hint": "A linked build manager sees your projects and posts progress as it happens.",
                "href": "/app/settings#team",
                "cta": "See your team",
                "done": managers > 0,
            }
        )
        steps.append(
            {
                "key": "money",
                "title": "Send your first deposit",
                "hint": "Report it here and your manager matches it to the bank or EcoCash entry.",
                "href": "/app/money",
                "cta": "Report a deposit",
                "done": transactions > 0,
            }
        )
        steps.append(
            {
                "key": "documents",
                "title": "Read the proof behind a payment",
                "hint": "Plans, council receipts and site photos your manager uploads land here.",
                "href": "/app/documents",
                "cta": "Open documents",
                "done": documents > 0,
            }
        )
        steps.append(
            {
                "key": "agreement",
                "title": "Sign the agreement",
                "hint": "Scope, value and milestones in one place, before the money moves.",
                "href": "/app/agreements",
                "cta": "Open agreements",
                "done": agreements > 0,
            }
        )

    return steps


def should_show(user) -> dict | None:
    """The checklist, or None when it is finished or already dismissed."""
    if not user or user.get("onboarded_at"):
        return None

    steps = steps_for(user)
    if not steps:
        return None

    completed = sum(1 for step in steps if step["done"])
    if completed == len(steps):
        return None

    return {
        "steps": steps,
        "completed": completed,
        "total": len(steps),
        "percent": round((completed / len(steps)) * 100),
    }
