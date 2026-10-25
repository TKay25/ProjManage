"""What kind of work a project is.

A YaVaKa project is not only a house built from scratch. The same record — a
plan, a ledger, receipts and a handover file — fits a renovation, a kitchen
fit-out, a solar install or a borehole. Each kind carries:

* ``label``  — what the picker shows.
* ``noun``   — how the kind reads mid-sentence ("a kitchen and cabinet fit-out").
* ``this``   — how it reads when a page is already about one project.
* ``stages`` — the stages that kind actually needs, used to pre-select the plan.

Keeping this in one place means the wording across the app and the workflow a
kind starts with cannot drift apart.
"""

FULL_BUILD_STAGES = [
    "land_due_diligence",
    "survey_diagram",
    "architectural_design",
    "plan_approval",
    "ema_geotech",
    "water_sewer_application",
    "site_setting_out",
    "foundation",
    "slab",
    "superstructure",
    "ring_beam_roof",
    "openings",
    "plumbing_electrical_rough",
    "plaster_screed",
    "finishes",
    "external_works",
    "zesa_connection",
    "certificate_of_occupation",
    "handover_snags",
]

PROJECT_KINDS = [
    {
        "key": "full_build",
        "label": "Full house build",
        "noun": "a full house build",
        "this": "this build",
        "icon": "building",
        "summary": "A new house from the stand up: approvals, substructure, roof, services and handover.",
        "stages": FULL_BUILD_STAGES,
        "shows_budget_against": "the house",
    },
    {
        "key": "renovation",
        "label": "Renovation & remodelling",
        "noun": "a renovation",
        "this": "this renovation",
        "icon": "refresh",
        "summary": "Reworking an existing house — strip out, move walls, renew services and redecorate.",
        "stages": [
            "site_setting_out",
            "openings",
            "plumbing_electrical_rough",
            "plaster_screed",
            "finishes",
            "external_works",
            "handover_snags",
        ],
        "shows_budget_against": "the renovation",
    },
    {
        "key": "extension",
        "label": "Extension & new rooms",
        "noun": "an extension",
        "this": "this extension",
        "icon": "layout",
        "summary": "Adding rooms or a storey onto a house that is already standing.",
        "stages": [
            "architectural_design",
            "plan_approval",
            "site_setting_out",
            "foundation",
            "slab",
            "superstructure",
            "ring_beam_roof",
            "openings",
            "plaster_screed",
            "finishes",
            "handover_snags",
        ],
        "shows_budget_against": "the extension",
    },
    {
        "key": "kitchen",
        "label": "Kitchen & cabinets",
        "noun": "a kitchen and cabinet fit-out",
        "this": "this kitchen",
        "icon": "layout",
        "summary": "Carcasses, counter tops, tiling, plumbing and electrical for a new or rebuilt kitchen.",
        "stages": [
            "plumbing_electrical_rough",
            "plaster_screed",
            "finishes",
            "handover_snags",
        ],
        "shows_budget_against": "the kitchen",
    },
    {
        "key": "bathroom",
        "label": "Bathroom & wet rooms",
        "noun": "a bathroom fit-out",
        "this": "this bathroom",
        "icon": "layout",
        "summary": "Waterproofing, sanitary ware, tiling and the plumbing behind it.",
        "stages": [
            "plumbing_electrical_rough",
            "plaster_screed",
            "finishes",
            "handover_snags",
        ],
        "shows_budget_against": "the bathroom",
    },
    {
        "key": "interior",
        "label": "Interior design & finishes",
        "noun": "an interior design project",
        "this": "this interior",
        "icon": "pen",
        "summary": "Ceilings, joinery, paint, lighting and the finishing details that make a house live well.",
        "stages": ["plaster_screed", "finishes", "handover_snags"],
        "shows_budget_against": "the interior",
    },
    {
        "key": "roofing",
        "label": "Roofing & trusses",
        "noun": "a roofing project",
        "this": "this roof",
        "icon": "home",
        "summary": "Trusses, sheeting, waterproofing and rainwater goods on a new or re-roofed house.",
        "stages": ["ring_beam_roof", "openings", "external_works", "handover_snags"],
        "shows_budget_against": "the roof",
    },
    {
        "key": "solar",
        "label": "Solar & backup power",
        "noun": "a solar installation",
        "this": "this solar install",
        "icon": "sun",
        "summary": "Panels, inverter, battery bank and the wiring that carries the load.",
        "stages": ["plumbing_electrical_rough", "finishes", "handover_snags"],
        "shows_budget_against": "the system",
    },
    {
        "key": "borehole",
        "label": "Borehole & water",
        "noun": "a borehole and water project",
        "this": "this borehole",
        "icon": "globe",
        "summary": "Siting, drilling, casing, pump, tank stand and the connection into the house.",
        "stages": [
            "water_sewer_application",
            "site_setting_out",
            "external_works",
            "handover_snags",
        ],
        "shows_budget_against": "the water system",
    },
    {
        "key": "walls_gates",
        "label": "Walls, gates & landscaping",
        "noun": "a walls, gates and landscaping project",
        "this": "these external works",
        "icon": "building",
        "summary": "Perimeter wall, gate, driveway, paving, garden and the security that goes with them.",
        "stages": [
            "plan_approval",
            "site_setting_out",
            "external_works",
            "handover_snags",
        ],
        "shows_budget_against": "the external works",
    },
]

KINDS_BY_KEY = {kind["key"]: kind for kind in PROJECT_KINDS}
DEFAULT_KIND = "full_build"


def kind_for(value):
    """The catalogue entry for a stored key, falling back to a full build."""
    return KINDS_BY_KEY.get((value or "").strip(), KINDS_BY_KEY[DEFAULT_KIND])


def kind_label(value) -> str:
    return kind_for(value)["label"]


def kind_noun(value) -> str:
    return kind_for(value)["noun"]


def kind_this(value) -> str:
    return kind_for(value)["this"]


def kind_icon(value) -> str:
    return kind_for(value)["icon"]


def default_stages(value) -> list:
    return list(kind_for(value)["stages"])


def is_valid(value) -> bool:
    return (value or "") in KINDS_BY_KEY


def choices():
    """(key, label) pairs for a select control."""
    return [(kind["key"], kind["label"]) for kind in PROJECT_KINDS]
