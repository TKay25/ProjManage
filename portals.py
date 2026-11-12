"""The two sign-in doors: Project Management and Property Management.

Project Management is the main product: the build, its stages, the money and
the proof. Property Management is the second door, for a house that is already
standing — a completed build, an inherited property or a buy-to-let — and
rental management is the bonus module that ships inside it.

Keeping both doors in one catalogue means the sign-in pages, the sidebar, the
assistant and the redirect after login cannot drift apart.
"""

PROJECT = "project"
PROPERTY = "property"

ALL = (PROJECT, PROPERTY)

PORTALS = {
    PROJECT: {
        "key": PROJECT,
        "name": "YaVaKa Project Management",
        "short": "Project Management",
        "tagline": "Build from anywhere",
        "summary": (
            "The main system: stages, funding, receipts and the handover file "
            "for a build that is still going up."
        ),
        "login_endpoint": "auth.login",
        "home_path": "/app",
        "badge": "Main system",
    },
    PROPERTY: {
        "key": PROPERTY,
        "name": "YaVaKa Property Management",
        "short": "Property Management",
        "tagline": "Collect the rent, keep the paper trail",
        "summary": (
            "The property workspace: tenants, leases, rent invoices and "
            "receipts. Rental management is a bonus module that comes with it, "
            "not a replacement for Project Management."
        ),
        "login_endpoint": "auth.property_login",
        "home_path": "/property",
        "badge": "Bonus rental module",
    },
}


def normalise(value) -> list[str]:
    """Turn a stored ``portals`` value into the doors this account may open.

    Older rows carry no value at all; those accounts are project accounts,
    which is what they were created as.
    """
    if isinstance(value, (list, tuple, set)):
        parts = [str(part) for part in value]
    else:
        parts = str(value or "").split(",")

    keys = {part.strip().lower() for part in parts}
    ordered = [key for key in ALL if key in keys]
    return ordered or [PROJECT]


def for_user(user) -> list[str]:
    if not user:
        return []
    if user.get("role") == "admin":
        return list(ALL)
    return normalise(user.get("portals"))


def has(user, key: str) -> bool:
    return (key or "").strip().lower() in for_user(user)


def entry(key: str) -> dict:
    return PORTALS.get((key or "").strip().lower(), PORTALS[PROJECT])


def normalise_key(value) -> str:
    key = (value or "").strip().lower()
    return key if key in ALL else PROJECT


def home_path(key: str) -> str:
    return entry(key)["home_path"]


def login_path(key: str) -> str:
    return "/property/login" if (key or "").strip().lower() == PROPERTY else "/login"


def default_for(user) -> str:
    """Where this account lands: property-only accounts land in properties."""
    doors = for_user(user)
    return PROPERTY if doors == [PROPERTY] else PROJECT


def other_than(user, current: str):
    """The door this account could switch to, or None when it only has one."""
    for key in for_user(user):
        if key != current:
            return PORTALS[key]
    return None


def current_from_path(path: str) -> str:
    return PROPERTY if str(path or "").startswith("/property") else PROJECT


def grant(user_id: str, key: str) -> list[str]:
    """Adds a door to an existing account and returns the new set."""
    from db import execute, query

    key = (key or "").strip().lower()
    if key not in ALL:
        return []
    row = query("SELECT portals FROM users WHERE id = ?", (user_id,), one=True)
    keys = normalise(row["portals"] if row else "")
    if key not in keys:
        keys.append(key)
        # Keep the canonical order so two rows never differ by accident.
        keys = [item for item in ALL if item in keys]
        execute("UPDATE users SET portals = ? WHERE id = ?", (",".join(keys), user_id))
    return keys
