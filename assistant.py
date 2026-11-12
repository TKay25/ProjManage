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
import portals
import queries
import rentals
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

# Rental management is the bonus module inside Property Management, so an
# account standing in that workspace is asked about rent, not about stages.
PROPERTY_SUGGESTIONS = (
    "What rent is due?",
    "Which tenants are behind?",
    "Show my leases",
    "When is the next property check?",
)


def property_context(user) -> bool:
    """True when the person is working in the property workspace."""
    if not user:
        return False
    try:
        from flask import g, request

        # The window names its door on every question, which is the only signal
        # that survives the POST to /api/assistant/ask.
        declared = getattr(g, "assistant_portal", None)
        if declared:
            return declared == portals.PROPERTY
        if request.path.startswith("/property"):
            return True
    except RuntimeError:
        pass
    return portals.for_user(user) == [portals.PROPERTY]


def suggestions_for(user) -> tuple:
    if not user:
        return PUBLIC_SUGGESTIONS
    if property_context(user):
        return PROPERTY_SUGGESTIONS
    return MANAGER_SUGGESTIONS if runs_build(user) else SUGGESTIONS


def _money(cents: int) -> str:
    return "$%s" % format(cents / 100, ",.2f")


def _reply(text: str, links=(), suggestions=None) -> dict:
    return {"reply": text, "links": list(links), "suggestions": list(suggestions or ())}


def _projects(user):
    return accessible_projects(user) or []


def _help(user) -> dict:
    if property_context(user):
        return _reply(
            "I can read your rental portfolio back to you. Ask about rent due, tenants, "
            "leases, receipts or the next property check. Anything that needs a person "
            "is better asked of your property manager.",
            [("Open the property dashboard", "/property")],
            PROPERTY_SUGGESTIONS,
        )
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
    if property_context(user):
        return _rent_due(user)

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
    if property_context(user):
        return _reply(
            "I did not follow that one. In this workspace I can answer questions about "
            "rent due, tenants, leases, receipts and property checks — anything else is "
            "better asked of your property manager.",
            [("Open the property dashboard", "/property")],
            suggestions_for(user),
        )
    return _reply(
        "I did not follow that one. I can answer questions about a balance, a stage, "
        "documents, pending approvals or updates -- anything else is better asked of "
        "your build manager.",
        [("Open the dashboard", "/app")],
        suggestions_for(user),
    )


# ----------------------------------------------------------------------
# Rental management (the bonus module inside Property Management)
# ----------------------------------------------------------------------


def _rental_scope(user):
    return None if user["role"] == "admin" else user["id"]


def _rent_not_enabled(user) -> dict:
    return _reply(
        "Rental management is the bonus module inside Property Management, and this "
        "account signs in to Project Management. Add the Property Management door in "
        "Settings, then sign in there to work with tenants, leases and rent.",
        [("Open settings", "/app/settings"), ("Property Management sign-in", "/property/login")],
        suggestions_for(user),
    )


def _rent_due(user) -> dict:
    if not portals.has(user, portals.PROPERTY):
        return _rent_not_enabled(user)

    totals = rentals.dashboard_totals(_rental_scope(user))
    if not totals["properties"]:
        return _reply(
            "No property is on your record yet, so there is no rent to report. Add the "
            "building you rent out and the rent starts being tracked against it.",
            [("Add a property", "/property/properties")],
            PROPERTY_SUGGESTIONS,
        )
    return _reply(
        "%d propert%s, %s a month on signed leases. %s came in during %s and %s is "
        "still outstanding."
        % (
            totals["properties"],
            "y" if totals["properties"] == 1 else "ies",
            _money(totals["rent_roll"]),
            _money(totals["collected"]),
            totals["month_label"],
            _money(totals["outstanding"]),
        ),
        [
            ("Open rent invoices", "/property/invoices"),
            ("Open receipts", "/property/payments"),
        ],
    )


def _rent_arrears(user) -> dict:
    if not portals.has(user, portals.PROPERTY):
        return _rent_not_enabled(user)

    rows = rentals.arrears(_rental_scope(user), limit=5)
    if not rows:
        return _reply(
            "Nobody is behind on rent. Every issued invoice is paid or not yet due.",
            [("Open rent invoices", "/property/invoices")],
        )
    lines = []
    for row in rows:
        lines.append(
            "%s — %s owes %s (due %s)."
            % (
                row["property_name"],
                row["tenant_name"] or "the tenant",
                _money(row["balance_cents"]),
                str(row["due_date"] or "")[:10],
            )
        )
    if len(rows) == 5:
        lines.append("(The five oldest are listed.)")
    return _reply(
        " ".join(lines),
        [("Open rent invoices", "/property/invoices")],
    )


def _rent_collected(user) -> dict:
    if not portals.has(user, portals.PROPERTY):
        return _rent_not_enabled(user)

    totals = rentals.dashboard_totals(_rental_scope(user))
    if not totals["properties"]:
        return _reply(
            "There is no property on the record yet, so nothing has been collected.",
            [("Add a property", "/property/properties")],
        )
    return _reply(
        "%s has been receipted in %s against %s a month in rent."
        % (
            _money(totals["collected"]),
            totals["month_label"],
            _money(totals["rent_roll"]),
        ),
        [("Open receipts", "/property/payments")],
    )


def _tenants(user) -> dict:
    if not portals.has(user, portals.PROPERTY):
        return _rent_not_enabled(user)

    scope = _rental_scope(user)
    rows = query(
        """SELECT t.name, t.status, p.name AS property_name, p.id AS property_id
           FROM property_tenants t
           JOIN properties p ON p.id = t.property_id
           WHERE t.status IN ('active', 'notice') AND (? IS NULL OR t.owner_id = ?)
           ORDER BY p.name LIMIT 5""",
        (scope, scope),
    )
    if not rows:
        return _reply(
            "No tenant is in place. Add one on the property page, then draft the lease.",
            [("Open properties", "/property/properties")],
        )
    links = [
        ("%s — %s" % (row["property_name"], row["name"]), "/property/properties/%s" % row["property_id"])
        for row in rows
    ]
    return _reply(
        "You have %d tenant%s in place%s."
        % (
            len(rows),
            "" if len(rows) == 1 else "s",
            " (five shown)" if len(rows) == 5 else "",
        ),
        links,
    )


def _leases(user) -> dict:
    if not portals.has(user, portals.PROPERTY):
        return _rent_not_enabled(user)

    scope = _rental_scope(user)
    rows = query(
        """SELECT status, COUNT(*) AS total FROM property_leases
           WHERE (? IS NULL OR owner_id = ?) GROUP BY status""",
        (scope, scope),
    )
    seen = {row["status"]: int(row["total"] or 0) for row in rows}
    if not seen:
        return _reply(
            "No lease has been produced yet. A lease is drafted from a property and its "
            "tenant, then signed on screen.",
            [("Open leases", "/property/leases")],
            PROPERTY_SUGGESTIONS,
        )
    return _reply(
        "%d signed, %d awaiting signature and %d ended."
        % (
            seen.get("signed", 0),
            seen.get("awaiting_signature", 0),
            seen.get("ended", 0),
        ),
        [("Open leases", "/property/leases")],
    )


def _property_checks(user) -> dict:
    if not portals.has(user, portals.PROPERTY):
        return _rent_not_enabled(user)

    scope = _rental_scope(user)
    due = rentals.open_checks(scope, limit=1)
    done = rentals.recent_checks(scope, limit=1)

    if not due and not done:
        return _reply(
            "No property check is booked or recorded. A periodic look at the building "
            "is what keeps small repairs small — schedule one on the property page.",
            [("Open properties", "/property/properties")],
        )
    parts = []
    if due:
        parts.append(
            "The next check is %s on %s."
            % (due[0]["property_name"], str(due[0]["scheduled_for"] or "an unrecorded date")[:10])
        )
    if done:
        parts.append(
            "The last one was %s on %s: %s."
            % (
                done[0]["property_name"],
                str(done[0]["conducted_at"] or done[0]["created_at"] or "")[:10],
                (done[0]["rating"] or "not rated"),
            )
        )
    return _reply(
        " ".join(parts),
        [("Open properties", "/property/properties")],
    )


def _rent_receipt(user) -> dict:
    if not portals.has(user, portals.PROPERTY):
        return _rent_not_enabled(user)
    return _reply(
        "Rent is receipted against an invoice, so the tenant ends up with a numbered "
        "receipt and the invoice shows part paid or settled. Record it on the Receipts "
        "page rather than sending it to me.",
        [("Open receipts", "/property/payments")],
    )



# ----------------------------------------------------------------------
# Visitors who have not signed in
# ----------------------------------------------------------------------

# What the site itself can answer. These are product facts - no project data,
# nothing that depends on an account - so a stranger can get a real answer
# instead of being told to sign up.
PUBLIC_SUGGESTIONS = (
    "What is YaVaKa?",
    "How does it work?",
    "What are the 19 stages?",
    "Do you manage rentals after the build?",
)

PUBLIC_TOPICS = (
    (
        ("what is yavaka", "what's yavaka", "who are you", "about yavaka"),
        "YaVaKa is build management for Zimbabweans building at home from "
        "abroad. You get the stages, the money and the proof in one record, so "
        "you are not relying on phone calls and photographs.",
        [("How it works", "/#how")],
    ),
    (
        ("how does", "how it works", "how do you", "process", "work"),
        "Three things happen in order. A project is set up with a stand, budget "
        "and target date across the 19-stage Zimbabwe sequence. Money moves "
        "against approved stages, with a receipt against each payment. Progress "
        "and balance updates reach you by email and WhatsApp.",
        [("See the stages", "/#stages"), ("Money controls", "/#money")],
    ),
    (
        ("stage", "stages", "sequence", "nineteen", "19"),
        "The build follows nineteen stages, from land and title due diligence "
        "through council plans, footings, superstructure, roofing and finishes "
        "to snag list and handover. Each stage has an owner, a budget and a "
        "decision, and the statutory gates are called early rather than "
        "discovered late.",
        [("Build stages", "/#stages")],
    ),
    (
        ("cost", "price", "pricing", "how much", "fee", "charge"),
        "Pricing depends on what you are building and who runs it on the ground. "
        "Create a free account to set up a project record and see where you "
        "stand, then talk to us about managing the build itself.",
        [("Create an account", "/register"), ("Sign in", "/login")],
    ),
    (
        ("whatsapp", "chat", "message", "bot"),
        "There is a WhatsApp assistant on the same project record. Clients and "
        "managers get different menus, it answers in English, Shona or Ndebele, "
        "and a build manager can take a conversation over from it at any point.",
        [("WhatsApp updates", "/#whatsapp")],
    ),
    (
        ("receipt", "proof", "document", "upload", "download", "invoice"),
        "Receipts, plans, agreements, photos, voice notes and video all file "
        "against the build rather than a phone. Every one can be opened or "
        "downloaded again later, including from a WhatsApp notification.",
        [("Money controls", "/#money")],
    ),
    (
        ("manager", "contractor", "builder", "supplier", "vet", "vetted"),
        "Build managers and contractors are referenced before work is awarded, "
        "and work is priced against measured quantities rather than a round "
        "number. There is a supplier directory covering Zimbabwe building "
        "suppliers.",
        [("Supplier directory", "/suppliers")],
    ),
    (
        ("sign up", "signup", "register", "create", "account", "start", "begin"),
        "Create an account, then set up your first project with its stand, "
        "budget and target date. If someone else runs the build, you invite them "
        "or hand it to a manager; either way the record is yours.",
        [("Create an account", "/register")],
    ),
    (
        ("sign in", "log in", "login", "password", "forgot"),
        "Sign in from the button at the top of the page. If you cannot get in, "
        "use Forgot your password on the sign-in form and a reset link is "
        "emailed to you.",
        [("Sign in", "/login"), ("Reset a password", "/forgot-password")],
    ),
    (
        ("rent", "rental", "rentals", "tenant", "lease", "landlord", "property management"),
        "When the build is finished, YaVaKa Property Management takes over: the tenant, "
        "the lease, rent invoices and numbered receipts, plus periodic property checks "
        "with photos and video that reach you on the system and on WhatsApp. Rental "
        "management is a bonus module inside Property Management — Project Management "
        "remains the main system.",
        [("Property Management sign-in", "/property/login"), ("Read the site", "/")],
    ),
    (
        ("contact", "talk", "human", "person", "call", "email", "support"),
        "Email hello@yavaka.co.zw and a person will pick it up. Once you have an "
        "account, the WhatsApp tab puts you in a conversation with whoever runs "
        "your build.",
        [("Email us", "mailto:hello@yavaka.co.zw")],
    ),
    (
        ("safe", "secure", "security", "privacy", "data"),
        "Your record is private to you and the people you put on the build. "
        "Documents are stored with the project rather than on a phone, and links "
        "sent over WhatsApp expire.",
        [("Read the site", "/")],
    ),
)


def _looks_personal(text: str) -> bool:
    """True when the question is about the asker's own build.

    Without this, "what is my balance" matches a "what is" keyword and gets a
    product blurb, which is worse than saying plainly that it needs a sign-in.
    """
    owns = any(word in text.split() for word in ("my", "our", "me", "mine"))
    project_words = (
        "balance", "project", "stage", "receipt", "document", "payment",
        "budget", "money", "account", "build", "invoice", "agreement",
        "rent", "tenant", "lease", "property",
    )
    return owns and any(word in text for word in project_words)


def answer_public(question: str) -> dict:
    """Answer from published product facts. Never touches project data."""
    text = str(question or "").strip().lower()

    if not _looks_personal(text):
        best = None
        for keywords, reply, links in PUBLIC_TOPICS:
            hits = sum(1 for word in keywords if word in text)
            if hits and (best is None or hits > best[0]):
                best = (hits, reply, links)
        if best:
            return _reply(best[1], best[2], PUBLIC_SUGGESTIONS)

    return _reply(
        "I can explain how YaVaKa works, the nineteen stages, money controls, "
        "WhatsApp updates and how to start. Questions about your own build need "
        "a signed-in account, because I read those figures from your record.",
        [("Create an account", "/register"), ("Sign in", "/login")],
        PUBLIC_SUGGESTIONS,
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
    # Rental management, answered from the property side of the account.
    "rent_due": _rent_due,
    "rent_invoices": _rent_due,
    "rent_arrears": _rent_arrears,
    "rent_collected": _rent_collected,
    "rent_receipt": _rent_receipt,
    "tenants": _tenants,
    "leases": _leases,
    "property_checks": _property_checks,
}


def answer(user, question: str) -> dict:
    """Route one question to a reply. Never raises on unexpected phrasing."""
    intent, _argument = detect_intent(question)
    handler = HANDLERS.get(intent)
    if handler is None:
        return _fallback(user)
    return handler(user)
