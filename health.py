"""Red and green signals for a project.

One vocabulary for "is this healthy?" so a list card, a dashboard panel, the
attention inbox and a notification all agree, and all use the same tones:

* ``danger`` — red. Over budget, over-funded, past the handover date, blocked.
* ``warn``   — amber. Nearly out of time, or proof still missing.
* ``success``— green. Inside budget with time to spare.

The tone names match the existing badge classes (``badge-danger``,
``badge-warn``, ``badge-success``), so nothing new has to be styled.
"""

from datetime import date, datetime

DANGER = "danger"
WARN = "warn"
SUCCESS = "success"

# A build within this many days of its target date is worth flagging, without
# calling it late.
DEADLINE_WATCH_DAYS = 21


def _as_date(value):
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value)[:19]).date()
    except (TypeError, ValueError):
        return None


def days_to_deadline(project, today=None) -> int | None:
    target = _as_date(project.get("target_date"))
    if not target:
        return None
    return (target - (today or date.today())).days


def signals(project, totals=None, *, blocked_stages=0, missing_receipts=0, today=None):
    """Every signal that applies, worst first."""
    found = []
    totals = totals or {}
    budget = int(project.get("budget_cents") or 0)
    spent = int(totals.get("spent") or 0)
    funded = int(totals.get("funded") or 0)
    balance = funded - spent
    status = project.get("status") or "planning"
    finished = status == "completed"

    if budget and spent > budget:
        found.append(
            {
                "key": "over_budget",
                "tone": DANGER,
                "label": f"{(spent - budget) / 100:,.2f} over budget",
                "detail": "Spending has passed the approved project budget.",
            }
        )
    elif budget and spent >= budget * 0.9:
        found.append(
            {
                "key": "budget_watch",
                "tone": WARN,
                "label": "Near the budget ceiling",
                "detail": "Ninety percent or more of the budget is committed.",
            }
        )

    if balance < 0:
        found.append(
            {
                "key": "over_funded_spend",
                "tone": DANGER,
                "label": "Spending exceeds funding",
                "detail": "More has been paid out than has been received.",
            }
        )

    remaining = days_to_deadline(project, today)
    if remaining is not None and not finished:
        if remaining < 0:
            found.append(
                {
                    "key": "past_deadline",
                    "tone": DANGER,
                    "label": f"{abs(remaining)} day{'s' if abs(remaining) != 1 else ''} past the handover date",
                    "detail": "The target handover date has passed and the project is not complete.",
                }
            )
        elif remaining <= DEADLINE_WATCH_DAYS:
            found.append(
                {
                    "key": "deadline_soon",
                    "tone": WARN,
                    "label": f"{remaining} day{'s' if remaining != 1 else ''} to handover",
                    "detail": "The target handover date is close.",
                }
            )

    if blocked_stages:
        found.append(
            {
                "key": "blocked",
                "tone": DANGER,
                "label": f"{blocked_stages} blocked stage{'s' if blocked_stages != 1 else ''}",
                "detail": "Work is on hold until the block is cleared.",
            }
        )

    if missing_receipts:
        found.append(
            {
                "key": "missing_receipts",
                "tone": WARN,
                "label": f"{missing_receipts} payment{'s' if missing_receipts != 1 else ''} without proof",
                "detail": "Attach the receipt so the spend is accounted for.",
            }
        )

    if not found and status in {"planning", "in_progress"}:
        found.append(
            {
                "key": "on_track",
                "tone": SUCCESS,
                "label": "On budget and on time",
                "detail": "Nothing is over budget or past its date.",
            }
        )

    return found


def alerts(project, totals=None, *, blocked_stages=0, missing_receipts=0, today=None):
    """Only the signals that need action.

    These are what raise a notification; "on budget" is never news, so it is
    filtered out here rather than at every call site.
    """
    return [
        signal
        for signal in signals(
            project,
            totals,
            blocked_stages=blocked_stages,
            missing_receipts=missing_receipts,
            today=today,
        )
        if signal["tone"] in {DANGER, WARN}
    ]


def worst(signals_list):
    """The most serious tone present, or None."""
    tones = {signal["tone"] for signal in signals_list}
    for tone in (DANGER, WARN, SUCCESS):
        if tone in tones:
            return tone
    return None


def summary(project, totals=None, **flags):
    """A single badge for a list card: the worst signal that applies."""
    found = signals(project, totals, **flags)
    tone = worst(found)
    if not tone:
        return None
    headline = found[0]
    return {"tone": tone, "label": headline["label"], "signals": found}
