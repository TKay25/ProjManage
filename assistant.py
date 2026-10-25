"""The in-app assistant: the same intents the WhatsApp bot understands.

This answers from the signed-in person's own rows using the same reads the
pages use, so a reply can never quote a figure the page would contradict. It
runs entirely in-process -- no model call, no network -- which is why it opens
instantly on a slow connection.

detect_intent is shared with the WhatsApp bot so the two cannot drift: if a
phrase works in a chat it works in the window, and vice versa.
"""

from auth import accessible_projects, runs_build
from db import query
import queries
import updates
from whatsapp import detect_intent

SUGGESTIONS = (
    "What is my balance?",
    "Where is the build?",
    "Show my documents",
    "What needs attention?",
)

MANAGER_SUGGESTIONS = (
    "How are my clients doing?",
    "What needs attention?",
    "Show my documents",
    "How do I take over a chat?",
)


def suggestions_for(user) -> tuple:
    return MANAGER_SUGGESTIONS if runs_build(user) else SUGGESTIONS


def _money(cents: int) -> str:
    return "$%s" % format(cents / 100, ",.2f")


def _reply(text: str, links=(), suggestions=None) -> dict:
    return {"reply": text, "links": list(links), "suggestions": list(suggestions or ())}


def _projects(user):
    return accessible_projects(user) or []


def _help(user) -> dict:
    if runs_build(user):
        body = (
            "I can read your portfolio back to you. Ask about a balance, a stage, "
            "pending approvals, documents, or your clients. For anything that needs "
            "a person, open WhatsApp and take the conversation over."
        )
    else:
        body = (
            "I can read your build back to you. Ask about your balance, what stage "
            "the work has reached, your documents, or anything that needs attention. "
            "For anything that needs a person, ask to speak to your build manager."
        )
    return _reply(body, [("Open the dashboard", "/app")], suggestions_for(user))


def _balance(user) -> dict:
    projects = _projects(user)
    if not projects:
        return _reply(
            "There is nothing in the ledger yet, so there is no balance to report. "
            "A balance only means something once a project exists.",
            [("Create a project", "/app/projects/new")],
        )

    totals = queries.totals_for_projects([p["id"] for p in projects])
    body = (
        "Across %d project%s you have funded %s and spent %s, leaving %s available."
        % (
            len(projects),
            "" if len(projects) == 1 else "s",
            _money(totals["funded"]),
            _money(totals["spent"]),
            _money(totals["balance"]),
        )
    )
    if len(projects) > 1:
        biggest = max(projects, key=lambda p: queries.money_totals(p["id"])["funded"])
        body += " The largest is %s." % biggest["name"]
    return _reply(body, [("Open the ledger", "/app/money")])


def _status(user) -> dict:
    projects = _projects(user)
    if not projects:
        return _reply(
            "No project is set up yet, so there is no stage to report.",
            [("Create a project", "/app/projects/new")],
        )

    lines, links = [], []
    for project in projects[:3]:
        stages = queries.stage_rows(project["id"])
        upcoming = queries.next_stage(stages)
        done = len([s for s in stages if s["status"] == "complete"])
        if upcoming:
            lines.append(
                "%s is %d of %d stages in; next is %s."
                % (project["name"], done, len(stages), upcoming["name"])
            )
        else:
            lines.append("%s has all %d stages complete." % (project["name"], len(stages)))
        links.append((project["name"], "/app/projects/%s" % project["id"]))
    if len(projects) > 3:
        lines.append("(%d more not listed.)" % (len(projects) - 3))
    return _reply(" ".join(lines), links)


def _project_list(user) -> dict:
    projects = _projects(user)
    if not projects:
        return _reply("You have no projects yet.", [("Create a project", "/app/projects/new")])
    links = [(p["name"], "/app/projects/%s" % p["id"]) for p in projects]
    return _reply(
        "You have %d project%s you can open."
        % (len(projects), "" if len(projects) == 1 else "s"),
        links,
    )


def _documents(user) -> dict:
    projects = _projects(user)
    if not projects:
        return _reply(
            "There is nowhere to file a document yet.",
            [("Create a project", "/app/projects/new")],
        )

    total = 0
    for project in projects:
        row = query(
            "SELECT COUNT(*) AS total FROM attachments WHERE project_id = ?",
            (project["id"],),
            one=True,
        )
        total += int(row["total"] or 0)
    if not total:
        return _reply(
            "No documents are filed yet. Receipts, plans and agreements all live in "
            "the same vault, filed against the build rather than a phone.",
            [("Open documents", "/app/documents")],
        )
    return _reply(
        "There %s %d %s filed against your builds. Every one can be opened or "
        "downloaded."
        % (
            "is" if total == 1 else "are",
            total,
            "document" if total == 1 else "documents",
        ),
        [("Open documents", "/app/documents")],
    )


def _attention(user) -> dict:
    projects = _projects(user)
    if not projects:
        return _reply(
            "Nothing needs attention because nothing is running yet.",
            [("Create a project", "/app/projects/new")],
        )

    counts = queries.attention_counts([p["id"] for p in projects])
    if not counts.get("total"):
        return _reply(
            "Nothing is flagged right now: no blocked stages, no missing receipts, "
            "no approvals waiting.",
            [("Open attention", "/app/attention")],
        )
    reasons = []
    for key, one, many in (
        ("blocked", "blocked stage", "blocked stages"),
        ("approvals", "approval waiting", "approvals waiting"),
        ("receipts", "payment without a receipt", "payments without a receipt"),
        ("agreements", "unsigned agreement", "unsigned agreements"),
    ):
        if counts.get(key):
            reasons.append(
                "%d %s" % (counts[key], one if counts[key] == 1 else many)
            )
    return _reply(
        "%d thing%s need a look: %s."
        % (counts["total"], "" if counts["total"] == 1 else "s", ", ".join(reasons)),
        [("Open attention", "/app/attention")],
    )


def _clients(user) -> dict:
    if not runs_build(user):
        return _reply(
            "You do not manage anyone else's build, so there are no client accounts "
            "under you. Your own project is on the Projects page.",
            [("Open projects", "/app/projects")],
        )
    projects = _projects(user)
    owners = {p["owner_id"] for p in projects}
    return _reply(
        "You are on %d build%s across %d client%s. Their messages and the assistant's "
        "replies are all stored, so you can pick a conversation up where it stopped."
        % (
            len(projects),
            "" if len(projects) == 1 else "s",
            len(owners),
            "" if len(owners) == 1 else "s",
        ),
        [("Open WhatsApp", "/app/whatsapp")],
    )


def _receipt(user) -> dict:
    return _reply(
        "Records are written where they belong, not sent to me as a message. A payment "
        "goes on the ledger and the receipt is filed against it, so the balance and the "
        "proof stay in one place.",
        [("Record money", "/app/money"), ("Upload a document", "/app/documents")],
    )


def _deposit(user) -> dict:
    return _reply(
        "I cannot take an amount here -- writing money to the wrong project is worse "
        "than not writing it at all. Open the ledger and record it against the build "
        "it belongs to.",
        [("Record money", "/app/money")],
    )


def _escalate(user) -> dict:
    if runs_build(user):
        return _reply(
            "You are the build manager, so there is nobody above you in the app. Answer "
            "the client from WhatsApp and the assistant stays quiet for that thread "
            "until you hand it back.",
            [("Open WhatsApp", "/app/whatsapp")],
        )
    return _reply(
        "Ask your build manager to take the conversation over -- they see the same "
        "thread you do. If no manager is on the build, use Contact on the site and a "
        "person will pick it up.",
        [("Open WhatsApp", "/app/whatsapp"), ("Contact us", "/contact")],
    )


def _update(user) -> dict:
    latest = updates.feed(user["id"], limit=3)
    if not latest:
        return _reply(
            "Nothing has changed on your builds yet.",
            [("Open updates", "/app/updates")],
        )
    links = [(item["title"], item["href"]) for item in latest]
    return _reply("Here is the most recent activity on your builds.", links)


def _fallback(user) -> dict:
    return _reply(
        "I did not follow that one. I can answer questions about a balance, a stage, "
        "documents, pending approvals or updates -- anything else is better asked of "
        "your build manager.",
        [("Open the dashboard", "/app")],
        suggestions_for(user),
    )


HANDLERS = {
    "help": _help,
    "balance": _balance,
    "status": _status,
    "projects": _project_list,
    "documents": _documents,
    "receipt": _receipt,
    "approvals": _attention,
    "clients": _clients,
    "escalate": _escalate,
    "update": _update,
    "deposit": _deposit,
}


def answer(user, question: str) -> dict:
    """Route one question to a reply. Never raises on unexpected phrasing."""
    intent, _argument = detect_intent(question)
    handler = HANDLERS.get(intent)
    if handler is None:
        return _fallback(user)
    return handler(user)
