"""The Zimbabwean residential build sequence tracked by YaVaKa.

Regulatory gates reflect local-authority plan approval, the Deeds Registry,
EMA and ZINWA requirements. Fees and forms differ by council, so each gate is a
management checklist, not legal advice.
"""

STAGE_GROUPS = [
    "Pre-construction & compliance",
    "Substructure",
    "Superstructure",
    "Services & finishes",
    "Completion",
]

STAGES = [
    {
        "key": "land_due_diligence",
        "name": "Land & title due diligence",
        "summary": "Confirm ownership, title deed or cession, stand size and encumbrances before any money changes hands.",
        "group": "Pre-construction & compliance",
        "authority": "Deeds Registry / Local Authority",
        "requires_authority": True,
        "weight": 4,
        "documents": ["Title deed or cession", "Seller ID", "Council valuation"],
    },
    {
        "key": "survey_diagram",
        "name": "Survey & stand diagram",
        "summary": "A registered land surveyor confirms beacons and produces the diagram used on drawings and the cession.",
        "group": "Pre-construction & compliance",
        "authority": "Registered Land Surveyor",
        "weight": 1.5,
        "documents": ["Survey diagram", "Beacon certificate"],
    },
    {
        "key": "architectural_design",
        "name": "Architectural & structural drawings",
        "summary": "House plans, structural details and services layout prepared by an architect, draughtsperson or engineer.",
        "group": "Pre-construction & compliance",
        "weight": 2.5,
        "documents": ["Floor plans", "Elevations", "Structural drawings"],
    },
    {
        "key": "plan_approval",
        "name": "Council plan approval",
        "summary": "Lodge plans with the local authority, pay scrutiny fees and obtain approved stamped drawings before breaking ground.",
        "group": "Pre-construction & compliance",
        "authority": "City / Municipal Council",
        "requires_authority": True,
        "weight": 3,
        "documents": ["Approved plans", "Council receipt", "Scrutiny fee"],
    },
    {
        "key": "ema_geotech",
        "name": "EMA clearance & geotechnical report",
        "summary": "Environmental Management Agency clearance where required, plus a soils report to size the foundation correctly.",
        "group": "Pre-construction & compliance",
        "authority": "EMA",
        "requires_authority": True,
        "weight": 1.5,
        "documents": ["EMA licence", "Soils report"],
    },
    {
        "key": "water_sewer_application",
        "name": "Water & sewer connection application",
        "summary": "Apply to the council or ZINWA for water and sewer connections; confirm connection points and fees.",
        "group": "Pre-construction & compliance",
        "authority": "ZINWA / Local Authority",
        "requires_authority": True,
        "weight": 2,
        "documents": ["Connection application", "Payment receipt"],
    },
    {
        "key": "site_setting_out",
        "name": "Site clearance & setting out",
        "summary": "Clear the stand, peg the building line and confirm levels against the approved plan.",
        "group": "Substructure",
        "weight": 1.5,
    },
    {
        "key": "foundation",
        "name": "Foundation & footings",
        "summary": "Excavate, pour strip footings and foundation concrete, including council inspection before backfill.",
        "group": "Substructure",
        "authority": "Council building inspector",
        "requires_authority": True,
        "weight": 9,
        "documents": ["Inspection sign-off", "Concrete delivery notes"],
    },
    {
        "key": "slab",
        "name": "Oversite slab & damp course",
        "summary": "Hardcore, blinding, damp-proof membrane and the ground-floor slab.",
        "group": "Substructure",
        "weight": 5,
    },
    {
        "key": "superstructure",
        "name": "Superstructure brickwork",
        "summary": "Walls, lintels, columns and ring beam built to the approved drawings, with openings set out correctly.",
        "group": "Superstructure",
        "weight": 17,
        "documents": ["Progress photos", "Material delivery notes"],
    },
    {
        "key": "ring_beam_roof",
        "name": "Ring beam, trusses & roof sheeting",
        "summary": "Cast the ring beam, fix timber trusses, purlins, roof sheets, fascia and rainwater goods.",
        "group": "Superstructure",
        "weight": 12,
    },
    {
        "key": "openings",
        "name": "Doors, windows & burglar bars",
        "summary": "Supply and fit frames, glazing, door sets and security bars.",
        "group": "Superstructure",
        "weight": 6,
    },
    {
        "key": "plumbing_electrical_rough",
        "name": "Plumbing & electrical rough-in",
        "summary": "First-fix plumbing and electrical, conduit, DB board and earthing before plaster closes the walls.",
        "group": "Services & finishes",
        "weight": 5,
    },
    {
        "key": "plaster_screed",
        "name": "Plaster, screed & ceilings",
        "summary": "Internal and external plaster, floor screed and ceiling installation.",
        "group": "Services & finishes",
        "weight": 5,
    },
    {
        "key": "finishes",
        "name": "Finishes & fittings",
        "summary": "Tiling, kitchen, sanitaryware, second-fix electrical, painting and final connections.",
        "group": "Services & finishes",
        "weight": 14,
    },
    {
        "key": "external_works",
        "name": "External works",
        "summary": "Driveway, stormwater drainage, boundary wall, gate and landscaping.",
        "group": "Services & finishes",
        "weight": 5,
    },
    {
        "key": "zesa_connection",
        "name": "ZESA connection & meter",
        "summary": "Apply for and complete the electricity connection, meter and certificate.",
        "group": "Completion",
        "authority": "ZESA / ZETDC",
        "requires_authority": True,
        "weight": 2.5,
        "documents": ["ZESA application", "Meter certificate"],
    },
    {
        "key": "certificate_of_occupation",
        "name": "Final inspection & Certificate of Occupation",
        "summary": "Council final inspection, submission of as-built drawings and issue of the Certificate of Occupation.",
        "group": "Completion",
        "authority": "City / Municipal Council",
        "requires_authority": True,
        "weight": 1.5,
        "documents": ["Certificate of Occupation", "As-built drawings"],
    },
    {
        "key": "handover_snags",
        "name": "Snag list & handover",
        "summary": "Walk the house with the client, close out snags, hand over keys, warranties and the document file.",
        "group": "Completion",
        "weight": 2,
        "documents": ["Signed snag list", "Handover certificate", "Warranties"],
    },
]

STAGES_BY_KEY = {stage["key"]: stage for stage in STAGES}

STATUS_LABELS = {
    "pending": "Not started",
    "in_progress": "In progress",
    "complete": "Complete",
    "blocked": "Blocked",
}

PROJECT_STATUS_LABELS = {
    "planning": "Planning",
    "in_progress": "In progress",
    "on_hold": "On hold",
    "completed": "Completed",
}

TRANSACTION_CATEGORIES = [
    ("client_deposit", "Client deposit"),
    ("materials", "Materials"),
    ("labour", "Labour"),
    ("fees", "Statutory & professional fees"),
    ("transport", "Transport & logistics"),
    ("equipment", "Equipment hire"),
    ("other", "Other"),
]

PAYMENT_METHODS = [
    ("BANK_TRANSFER", "Bank transfer"),
    ("CARD", "Card"),
    ("ECOCASH", "EcoCash"),
    ("INN_BUCKS", "InnBucks"),
    ("CASH", "Cash"),
    ("OTHER", "Other"),
]


def stage_by_key(key):
    return STAGES_BY_KEY.get(key or "")


def stage_name(key) -> str:
    stage = stage_by_key(key)
    return stage["name"] if stage else "Unassigned"


def stage_budget(weight: float, budget_cents: int) -> int:
    return round(budget_cents * weight / 100)


def project_progress(stage_rows) -> int:
    """Weighted progress across all stages (0-100)."""
    weighted = 0.0
    for stage in stage_rows:
        definition = stage_by_key(stage["key"])
        if not definition:
            continue
        if stage["status"] == "complete":
            weighted += definition["weight"]
        elif stage["status"] == "in_progress":
            weighted += definition["weight"] * 0.5
    return min(100, int(weighted + 0.5))


def category_label(value) -> str:
    for key, label in TRANSACTION_CATEGORIES:
        if key == value:
            return label
    return value or "Other"


def method_label(value) -> str:
    for key, label in PAYMENT_METHODS:
        if key == value:
            return label
    return value or "Other"
