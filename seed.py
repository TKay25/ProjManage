"""Idempotent seed data: supplier directory plus a demo client workspace."""

import json
import shutil
from pathlib import Path

from flask import current_app

import auth
from db import execute, new_id, now_iso, query
from stages import STAGES, stage_budget
from suppliers import SUPPLIERS
from workspaces import ensure_default_workspace

BASE_DIR = Path(__file__).resolve().parent
SEED_ASSETS = BASE_DIR / "static" / "img" / "seed"

# Printed on the sign-in page for demo installs, so it has to match the hashes
# below and in db.run_migrations.
DEMO_PASSWORD = "YaVaKa2026!"
DEMO_ACCOUNTS = ("admin@yavaka.co.zw", "client@yavaka.co.zw", "manager@yavaka.co.zw")


def ensure_seed():
    _seed_suppliers()
    if current_app.config.get("SEED_DEMO", False):
        _seed_demo()
        _ensure_staff_account()


def _ensure_staff_account():
    """Keeps a YaVaKa staff login available on demo installs."""
    existing = query("SELECT id FROM users WHERE role = 'admin' LIMIT 1", one=True)
    if existing:
        return

    execute(
        """INSERT INTO users (id, name, email, password_hash, role, phone, country, avatar_color, created_at)
           VALUES (?, ?, ?, ?, 'admin', NULL, 'Zimbabwe', '#0B4F3C', ?)""",
        (
            new_id(),
            "YaVaKa Staff",
            "admin@yavaka.co.zw",
            auth.hash_password(DEMO_PASSWORD),
            "2026-02-18T08:00:00+00:00",
        ),
    )


def _seed_suppliers():
    """Idempotent, so concurrent gunicorn workers cannot duplicate the directory.

    The id is derived from the name, which makes the row stable across boots.
    Fields are refreshed rather than skipped, so a corrected website or phone
    number in the source list actually reaches a database that was seeded
    earlier.
    """
    for index, supplier in enumerate(SUPPLIERS):
        supplier_id = "sup-" + "".join(
            char for char in supplier["name"].lower() if char.isalnum()
        )[:18]
        execute(
            """INSERT INTO suppliers
                 (id, name, category, city, website, phone, address, description, tags, verified, position)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (id) DO UPDATE SET
                 name = excluded.name,
                 category = excluded.category,
                 city = excluded.city,
                 website = excluded.website,
                 phone = excluded.phone,
                 address = excluded.address,
                 description = excluded.description,
                 tags = excluded.tags,
                 verified = excluded.verified,
                 position = excluded.position""",
            (
                supplier_id,
                supplier["name"],
                supplier["category"],
                supplier["city"],
                supplier.get("website"),
                supplier.get("phone"),
                supplier.get("address"),
                supplier["description"],
                ",".join(supplier.get("tags", [])),
                1 if supplier.get("verified") else 0,
                index,
            ),
        )


def _copy_seed_asset(name: str):
    source = SEED_ASSETS / name
    if not source.exists():
        return None
    target = Path(current_app.config["UPLOAD_FOLDER"]) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return name


def _seed_demo():
    existing = query("SELECT COUNT(*) AS count FROM users", one=True)
    if existing and existing["count"] > 0:
        return

    password_hash = auth.hash_password(DEMO_PASSWORD)
    client_id = new_id()
    manager_id = new_id()

    for user_id, name, email, role, phone, country, colour in [
        (client_id, "Rudo Chikafu", "client@yavaka.co.zw", "client", "263771234567", "United Kingdom", "#0F5D46"),
        (manager_id, "Tendai Moyo", "manager@yavaka.co.zw", "manager", "263772555001", "Zimbabwe", "#C8963E"),
    ]:
        execute(
            """INSERT INTO users (id, name, email, password_hash, role, phone, country, avatar_color, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, name, email, password_hash, role, phone, country, colour, "2026-02-20T10:00:00+00:00"),
        )

    project_id = _create_project(
        owner_id=client_id,
        manager_id=manager_id,
        code="YVK-0001",
        name="Greendale Family Home",
        description="Three-bedroom family house on Stand 1421, Greendale. Client is based in London and visits twice a year.",
        city="Harare",
        suburb="Greendale",
        stand="Stand 1421",
        budget_cents=8_500_000,
        status="in_progress",
        start_date="2026-03-02",
        target_date="2026-12-15",
        completed=9,
        current="superstructure",
    )

    _create_project(
        owner_id=client_id,
        manager_id=manager_id,
        code="YVK-0002",
        name="Waterfalls Rental Cottage",
        description="Two-bedroom cottage for rental income. Awaiting council plan approval before site works begin.",
        city="Harare",
        suburb="Waterfalls",
        stand="Stand 88",
        budget_cents=4_500_000,
        status="planning",
        start_date="2026-11-01",
        target_date="2027-06-30",
        completed=3,
        current="plan_approval",
    )

    transactions = [
        ("FUNDING", 2_000_000, "client_deposit", None, "Initial mobilisation deposit", "BANK_TRANSFER", "FT-88213", "2026-03-05T10:22:00+00:00"),
        ("FUNDING", 2_500_000, "client_deposit", None, "Second tranche — substructure", "BANK_TRANSFER", "FT-90441", "2026-05-18T14:05:00+00:00"),
        ("FUNDING", 1_500_000, "client_deposit", None, "Third tranche — superstructure", "OTHER", "WISE-5512", "2026-07-29T08:41:00+00:00"),
        ("EXPENSE", 125_000, "fees", "plan_approval", "Harare City Council plan scrutiny fees", "BANK_TRANSFER", "RCPT-2231", "2026-03-12T09:00:00+00:00"),
        ("EXPENSE", 45_000, "fees", "survey_diagram", "Registered surveyor — beacon confirmation", "ECOCASH", None, "2026-03-20T11:30:00+00:00"),
        ("EXPENSE", 80_000, "labour", "site_setting_out", "Site clearance crew — four days", "CASH", None, "2026-04-02T07:45:00+00:00"),
        ("EXPENSE", 845_000, "materials", "foundation", "Cement, river sand and 12mm rebar", "BANK_TRANSFER", "INV-4471", "2026-04-15T13:10:00+00:00"),
        ("EXPENSE", 230_000, "labour", "foundation", "Foundation excavation and concrete pour", "CASH", None, "2026-04-22T16:20:00+00:00"),
        ("EXPENSE", 485_000, "materials", "superstructure", "Face bricks — 6,000 units", "BANK_TRANSFER", "INV-5120", "2026-06-10T10:05:00+00:00"),
        ("EXPENSE", 160_000, "materials", "superstructure", "River sand and 19mm stone", "CASH", None, "2026-06-18T09:15:00+00:00"),
        ("EXPENSE", 62_000, "transport", "superstructure", "Truck hire — materials to site", "ECOCASH", None, "2026-06-19T15:40:00+00:00"),
        ("EXPENSE", 350_000, "labour", "superstructure", "Bricklaying crew — progress payment", "CASH", None, "2026-08-05T17:00:00+00:00"),
        ("EXPENSE", 520_000, "materials", "ring_beam_roof", "Roof trusses — 40% deposit", "BANK_TRANSFER", "INV-6033", "2026-10-02T12:00:00+00:00"),
    ]

    for tx_type, amount, category, stage_key, description, method, reference, occurred_at in transactions:
        execute(
            """INSERT INTO transactions
                 (id, project_id, type, amount_cents, currency, category, stage_key, description, method, reference, occurred_at, created_by, created_at)
               VALUES (?, ?, ?, ?, 'USD', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_id(),
                project_id,
                tx_type,
                amount,
                category,
                stage_key,
                description,
                method,
                reference,
                occurred_at,
                client_id if tx_type == "FUNDING" else manager_id,
                occurred_at,
            ),
        )

    for description, asset in [
        ("Cement, river sand and 12mm rebar", "receipt-cement.png"),
        ("Face bricks — 6,000 units", "receipt-bricks.png"),
    ]:
        saved = _copy_seed_asset(asset)
        if not saved:
            continue
        transaction = query(
            "SELECT id FROM transactions WHERE project_id = ? AND description = ?",
            (project_id, description),
            one=True,
        )
        if not transaction:
            continue
        execute(
            """INSERT INTO attachments
                 (id, project_id, transaction_id, uploader_id, kind, filename, original_name, mime_type, size, created_at)
               VALUES (?, ?, ?, ?, 'receipt', ?, ?, 'image/png', ?, ?)""",
            (new_id(), project_id, transaction["id"], manager_id, saved, asset, 184320, "2026-04-15T13:20:00+00:00"),
        )

    _seed_agreement(project_id, client_id)
    _seed_whatsapp(client_id, project_id)
    _seed_audit(client_id, manager_id, project_id)


def _create_project(
    *,
    owner_id,
    manager_id,
    code,
    name,
    description,
    city,
    suburb,
    stand,
    budget_cents,
    status,
    start_date,
    target_date,
    completed=0,
    current=None,
):
    project_id = new_id()
    created_at = "2026-02-24T08:00:00+00:00"
    owner = query("SELECT * FROM users WHERE id = ?", (owner_id,), one=True)
    workspace = ensure_default_workspace(owner)
    execute(
        """INSERT INTO projects
             (id, code, name, description, owner_id, manager_id, city, suburb, stand_number, status, budget_cents, start_date, target_date, workspace_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            project_id,
            code,
            name,
            description,
            owner_id,
            manager_id,
            city,
            suburb,
            stand,
            status,
            budget_cents,
            start_date,
            target_date,
            workspace["id"] if workspace else None,
            created_at,
            now_iso(),
        ),
    )

    for index, stage in enumerate(STAGES):
        stage_status = "pending"
        started_at = None
        completed_at = None

        if index < completed:
            stage_status = "complete"
            started_at = f"2026-{3 + (index // 4):02d}-{(index % 26) + 1:02d}T08:00:00+00:00"
            completed_at = f"2026-{3 + ((index + 1) // 4):02d}-{((index + 1) % 26) + 1:02d}T16:00:00+00:00"
        elif current and stage["key"] == current:
            stage_status = "in_progress"
            started_at = "2026-09-20T08:00:00+00:00"

        execute(
            """INSERT INTO stages
                 (id, project_id, key, name, position, status, budget_cents, notes, started_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)""",
            (
                new_id(),
                project_id,
                stage["key"],
                stage["name"],
                index + 1,
                stage_status,
                stage_budget(stage["weight"], budget_cents),
                started_at,
                completed_at,
            ),
        )

    return project_id


def _seed_agreement(project_id, client_id):
    schedule = [
        {"label": "Signing and site mobilisation", "amountCents": 1_700_000},
        {"label": "Foundation, slab and superstructure", "amountCents": 2_550_000},
        {"label": "Roof, services and finishes", "amountCents": 2_550_000},
        {"label": "Practical completion and handover", "amountCents": 1_700_000},
    ]

    terms = "\n".join(
        [
            "1. The contractor will build in accordance with the council-approved drawings and the specifications attached to this agreement.",
            "2. The contract price is USD 85,000.00, payable against the milestones set out in the payment schedule.",
            "3. Client funds are held in the project account and released per completed and inspected milestone.",
            "4. Any variation must be agreed in writing before the work is carried out and will be priced separately.",
            "5. The contractor is responsible for site safety and for statutory inspections at foundation, roofing and completion stages.",
            "6. Practical completion is targeted for 15 December 2026, subject to council approvals and client-funded materials arriving on time.",
            "7. The contractor holds 5% retention from each payment until the snag list is closed, then releases it within 14 days.",
            "8. Either party may refer a dispute to mediation, then arbitration under the Arbitration Act [Chapter 7:15] of Zimbabwe.",
            "9. This agreement is governed by the laws of Zimbabwe.",
        ]
    )

    execute(
        """INSERT INTO agreements
             (id, project_id, type, title, contract_value_cents, currency, scope, terms, payment_schedule,
              client_name, client_signature, signed_at, status, created_by, created_at)
           VALUES (?, ?, 'build_contract', ?, ?, 'USD', ?, ?, ?, ?, NULL, ?, 'signed', ?, ?)""",
        (
            new_id(),
            project_id,
            "Residential build contract — Greendale Family Home",
            8_500_000,
            "Design, council approval support, construction and handover of a three-bedroom house (approximately 180m²) on Stand 1421, Greendale, Harare, including external works and connection applications.",
            terms,
            json.dumps(schedule),
            "Rudo Chikafu",
            "2026-03-02T09:30:00+00:00",
            client_id,
            "2026-03-01T16:00:00+00:00",
        ),
    )


def _seed_whatsapp(client_id, project_id):
    contact_id = new_id()
    execute(
        """INSERT INTO whatsapp_contacts (id, phone, name, user_id, project_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (contact_id, "263771234567", "Rudo Chikafu", client_id, project_id, "2026-03-04T09:00:00+00:00"),
    )

    messages = [
        ("IN", "Hi, how much have I used so far?", "balance", "2026-10-18T09:12:00+00:00"),
        (
            "OUT",
            "*Greendale Family Home*\n\nReceived: $60,000.00\nUsed: $29,020.00\n*Available: $30,980.00*",
            "balance",
            "2026-10-18T09:12:05+00:00",
        ),
        ("IN", "Status", "status", "2026-10-18T09:15:00+00:00"),
        (
            "OUT",
            "*Greendale Family Home*\nProgress: 39% (9/19 stages)\nNow: *Superstructure brickwork*",
            "status",
            "2026-10-18T09:15:04+00:00",
        ),
    ]

    for direction, body, intent, created_at in messages:
        execute(
            """INSERT INTO whatsapp_messages (id, contact_id, direction, body, intent, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (new_id(), contact_id, direction, body, intent, "received" if direction == "IN" else "sent", created_at),
        )


def _seed_audit(client_id, manager_id, project_id):
    events = [
        (manager_id, "project.created", "Project Greendale Family Home created", "2026-02-24T08:00:00+00:00"),
        (manager_id, "stage.completed", "Slab & damp course marked complete", "2026-05-30T15:00:00+00:00"),
        (manager_id, "expense.recorded", "Roof trusses deposit of $5,200.00 recorded", "2026-10-02T12:00:00+00:00"),
        (client_id, "deposit.notified", "Third tranche of $15,000.00 received", "2026-07-29T08:41:00+00:00"),
    ]

    for user_id, action, detail, created_at in events:
        execute(
            "INSERT INTO audit_events (id, user_id, project_id, action, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (new_id(), user_id, project_id, action, detail, created_at),
        )
