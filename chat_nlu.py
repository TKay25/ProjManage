"""Reading a sentence the way the person who typed it expects to be understood.

Everything downstream — which flow starts, which ledger entry lands, which
answer comes back — is decided by what is extracted here. So this module does
the unglamorous work properly: it copes with typos, Zimdollar-era money words,
numbers written as words, dates said out loud, several instructions in one
sentence, and names of projects that are only half-remembered.

It touches no database and no request context, which is what makes it testable
on strings alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher

# ----------------------------------------------------------------------
# Cleaning
# ----------------------------------------------------------------------

_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"})

# Said around an instruction, never part of one.
_POLITE = (
    "please",
    "kindly",
    "can you",
    "could you",
    "would you",
    "will you",
    "i want to",
    "i need to",
    "i would like to",
    "i'd like to",
    "help me",
    "let's",
    "lets",
    "hey",
    "hi",
    "hello",
    "ok",
    "okay",
    "so",
    "just",
    "now",
    "quick",
    "quickly",
)

_VERB_STEMS = (
    "record",
    "log",
    "add",
    "post",
    "paid",
    "pay",
    "spent",
    "spend",
    "bought",
    "buy",
    "purchased",
    "received",
    "receive",
    "deposit",
    "got",
    "receipt",
    "receipted",
    "start",
    "begin",
    "complete",
    "finish",
    "finished",
    "block",
    "blocked",
    "open",
    "fix",
    "repair",
    "reverse",
    "undo",
    "delete",
    "remove",
    "switch",
    "change",
    "move",
    "set",
    "mark",
    "show",
    "open",
    "tell",
    "inform",
    "update",
    "send",
    "note",
    "create",
    "raise",
    "invoice",
)


def normalise(text) -> str:
    """Whitespace and quote hygiene only — case is kept for descriptions."""
    cleaned = str(text or "").translate(_QUOTES)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def strip_politeness(text: str) -> str:
    lowered = text.lower()
    for phrase in _POLITE:
        if lowered.startswith(phrase + " "):
            return text[len(phrase) :].lstrip(" ,:-")
    return text


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def similar(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


# ----------------------------------------------------------------------
# Numbers, including the ones written as words
# ----------------------------------------------------------------------

_UNITS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_SCALES = {
    "hundred": 100,
    "thousand": 1_000,
    "k": 1_000,
    "grand": 1_000,
    "million": 1_000_000,
    "m": 1_000_000,
}
_CURRENCY_WORDS = {"usd", "dollar", "dollars", "buck", "bucks", "bond", "bonds", "rtgs", "zwg", "zig"}

_AMOUNT_RE = re.compile(
    r"(?P<pre>\$|us\$|usd\s*)?"
    r"(?<![\w.])"
    r"(?P<num>\d{1,3}(?:[,\s]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s*(?P<suf>k|grand|thousand|million|m|usd|dollars?|bucks?|bonds?|rtgs|zwg|cents?)\b)?"
    r"(?![\w])",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

_MONEY_VERBS = (
    "spent",
    "spend",
    "paid",
    "pay",
    "cost",
    "costs",
    "bought",
    "buy",
    "purchase",
    "purchased",
    "received",
    "receive",
    "got",
    "deposited",
    "deposit",
    "funded",
    "collected",
    "charged",
    "worth",
    "for",
    "of",
)


@dataclass
class Amount:
    cents: int
    start: int
    end: int
    score: int = 0

    @property
    def text(self) -> str:
        return f"{self.cents / 100:.2f}"


def _word_amount(segment: str) -> int | None:
    """'twenty five thousand' -> 2500000 cents; None when no number hides here."""
    total = 0
    current = 0
    seen = False
    for token in words(segment):
        if token in _UNITS:
            current += _UNITS[token]
            seen = True
        elif token in _TENS:
            current += _TENS[token]
            seen = True
        elif token == "and":
            continue
        elif token in _SCALES:
            scale = _SCALES[token]
            if scale == 100:
                current = max(current, 1) * 100
            else:
                total += max(current, 1) * scale
                current = 0
            seen = True
        elif seen:
            break
    if not seen:
        return None
    return total + current


def extract_amounts(text: str) -> list[Amount]:
    """Every figure in the sentence, each scored by how money-like it looks."""
    lowered = text.lower()
    found: list[Amount] = []

    for match in _AMOUNT_RE.finditer(text):
        raw = match.group("num").replace(",", "").replace(" ", "")
        suffix = (match.group("suf") or "").lower()
        prefix = match.group("pre") or ""
        try:
            value = float(raw)
        except ValueError:
            continue

        cents = int(round(value * 100))
        if suffix == "cents":
            cents = int(round(value))
        elif suffix in _SCALES:
            cents = int(round(value * _SCALES[suffix] * 100))

        before = lowered[max(0, match.start() - 18) : match.start()]
        after = lowered[match.end() : match.end() + 14]
        score = 0
        if prefix:
            score += 60
        if suffix in _CURRENCY_WORDS:
            score += 60
        elif suffix == "cents":
            score += 55
        elif suffix in _SCALES:
            score += 45
        if "." in raw:
            score += 25
        if any(verb in before for verb in _MONEY_VERBS):
            score += 40
        if "currency" in after or "usd" in after:
            score += 30
        if _YEAR_RE.fullmatch(raw):
            score -= 70
        if any(name in before or name in after for name in _MONTHS):
            score -= 60
        if raw in {"1", "2", "3"} and "bag" in after:
            score -= 20
        found.append(Amount(cents=cents, start=match.start(), end=match.end(), score=score))

    # Figures spelled out: "two thousand", "fifteen hundred".
    for match in re.finditer(
        r"\b((?:(?:%s|%s|and|hundred|thousand|million|k|grand)\s*){2,})"
        % ("|".join(_UNITS), "|".join(_TENS)),
        lowered,
    ):
        value = _word_amount(match.group(1))
        if not value:
            continue
        score = 30
        before = lowered[max(0, match.start() - 18) : match.start()]
        if any(verb in before for verb in _MONEY_VERBS):
            score += 40
        found.append(
            Amount(cents=value * 100, start=match.start(), end=match.end(), score=score)
        )

    return sorted(found, key=lambda item: (item.start, item.end))


def best_amount(text: str) -> Amount | None:
    """The figure the sentence is actually about."""
    candidates = extract_amounts(text)
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item.score, item.cents, -item.start), reverse=True)
    return candidates[0]


def parse_amount(text: str) -> int | None:
    amount = best_amount(text)
    return amount.cents if amount else None


# ----------------------------------------------------------------------
# Dates said out loud
# ----------------------------------------------------------------------


def parse_date_ref(text: str, today: date | None = None) -> str | None:
    """An ISO date when the sentence says when, so entries land on the right day."""
    today = today or date.today()
    lowered = text.lower()

    if "day before yesterday" in lowered:
        return (today - timedelta(days=2)).isoformat()
    if "yesterday" in lowered:
        return (today - timedelta(days=1)).isoformat()
    if re.search(r"\btoday\b", lowered):
        return today.isoformat()
    if "last week" in lowered:
        return (today - timedelta(days=7)).isoformat()
    if "last month" in lowered:
        first = today.replace(day=1)
        return (first - timedelta(days=1)).replace(day=1).isoformat()

    for index, name in enumerate(_WEEKDAYS):
        if re.search(rf"\b{name}\b", lowered):
            back = (today.weekday() - index) % 7 or 7
            return (today - timedelta(days=back)).isoformat()

    match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if match:
        return match.group(0)

    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", text)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        year = today.year
        if match.group(3):
            year = int(match.group(3))
            year += 2000 if year < 100 else 0
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None

    match = re.search(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({'|'.join(_MONTHS)})"
        rf"(?:\s+(\d{{4}}))?\b",
        lowered,
    )
    if not match:
        match = re.search(
            rf"\b({'|'.join(_MONTHS)})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s+(\d{{4}}))?\b",
            lowered,
        )
        if match:
            month, day = _MONTHS[match.group(1)], int(match.group(2))
            year = int(match.group(3) or today.year)
        else:
            return None
    else:
        day, month = int(match.group(1)), _MONTHS[match.group(2)]
        year = int(match.group(3) or today.year)
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def date_span(text: str) -> tuple[int, int] | None:
    """Where in the sentence the date was said, so the description can drop it."""
    lowered = text.lower()
    patterns = (
        r"\bday before yesterday\b",
        r"\byesterday\b",
        r"\btoday\b",
        r"\blast week\b",
        r"\blast month\b",
        r"\b(?:last\s+)?(?:%s)\b" % "|".join(_WEEKDAYS),
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",
        r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:%s)(?:\s+\d{4})?\b" % "|".join(_MONTHS),
    )
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            return match.span()
    return None


# ----------------------------------------------------------------------
# Choosing between named things
# ----------------------------------------------------------------------


# Words in a name that describe a type of place rather than which one it is.
_GENERIC_NAME_WORDS = {
    "road",
    "street",
    "avenue",
    "close",
    "drive",
    "lane",
    "way",
    "house",
    "home",
    "flat",
    "cottage",
    "complex",
    "plot",
    "stand",
    "site",
    "build",
    "building",
    "project",
    "property",
    "phase",
    "stage",
    "and",
    "the",
    # Words that describe who or what, never which: "received from the client"
    # must not be read as naming a build called "Client House".
    "client",
    "owner",
    "manager",
    "admin",
    "staff",
    "tenant",
    "landlord",
    "customer",
    "test",
    "demo",
    "sample",
    "seed",
    "probe",
    "new",
    "old",
    "main",
    "first",
    "second",
    "third",
    "cottage",
    "duplex",
    "apartment",
    "villa",
    "townhouse",
    "family",
    "units",
    "block",
}


@dataclass
class Match:
    score: float
    item: dict


def rate_match(phrase: str, option: dict, keys=("name", "code", "label")) -> float:
    phrase = phrase.strip().lower()
    if not phrase:
        return 0.0
    haystacks = []
    for key in keys:
        value = option.get(key)
        if value:
            haystacks.append(str(value).lower())
    if not haystacks:
        return 0.0

    best = 0.0
    phrase_tokens = set(words(phrase))
    for haystack in haystacks:
        if phrase == haystack:
            best = max(best, 1.0)
        elif haystack in phrase:
            # "switch to the greendale build" contains "greendale".
            best = max(best, 0.92)
        elif phrase in haystack:
            best = max(best, 0.88)
        else:
            hay_tokens = set(words(haystack))
            if hay_tokens and phrase_tokens:
                overlap = len(phrase_tokens & hay_tokens) / len(phrase_tokens | hay_tokens)
                best = max(best, 0.75 * overlap + 0.25 * similar(phrase, haystack))
            # One distinctive word is enough: "greendale", "acacia".
            distinctive = {
                token
                for token in hay_tokens & phrase_tokens
                if len(token) >= 4 and token not in _GENERIC_NAME_WORDS
            }
            if distinctive:
                best = max(best, 0.82)
    return best


def rank_options(phrase: str, options, keys=("name", "code", "label")) -> list[Match]:
    scored = [Match(rate_match(phrase, option, keys), option) for option in options or []]
    scored = [item for item in scored if item.score >= 0.6]
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored


def resolve_option(phrase: str, options, keys=("name", "code", "label")):
    """(best, runner_up) — a runner-up that scores close means ask, don't guess."""
    ranked = rank_options(phrase, options, keys)
    if not ranked:
        return None, None
    best = ranked[0]
    runner = ranked[1] if len(ranked) > 1 else None
    if runner and best.score < 0.95 and runner.score >= best.score - 0.08:
        return best.item, runner.item
    return best.item, None


_ORDINALS = {
    "first": 0,
    "1st": 0,
    "one": 0,
    "second": 1,
    "2nd": 1,
    "two": 1,
    "third": 2,
    "3rd": 2,
    "three": 2,
    "fourth": 3,
    "4th": 3,
    "fifth": 4,
    "5th": 4,
    "last": -1,
    "final": -1,
}


def ordinal_index(text: str, length: int) -> int | None:
    """'the second one' / 'number 3' / 'last' -> a position in a short list."""
    if not length:
        return None
    lowered = text.lower()
    for token in words(lowered):
        if token in _ORDINALS:
            index = _ORDINALS[token]
            return index if index >= 0 else length - 1
    match = re.search(r"\b(?:number|option|choice|pick)\s*(\d+)\b", lowered)
    if match:
        index = int(match.group(1)) - 1
        return index if 0 <= index < length else None
    if len(words(lowered)) == 1 and lowered.strip().isdigit():
        index = int(lowered.strip()) - 1
        return index if 0 <= index < length else None
    return None


# ----------------------------------------------------------------------
# Vocabulary the app already speaks
# ----------------------------------------------------------------------

CATEGORY_HINTS = (
    ("materials", ("cement", "brick", "bricks", "sand", "stone", "quarry", "timber", "wood", "steel", "rebar", "roof", "sheet", "sheets", "tile", "tiles", "paint", "pipe", "pipes", "wire", "cable", "hardware", "material", "materials", "supplies")),
    ("labour", ("labour", "labor", "wages", "wage", "worker", "workers", "builder", "builders", "fundi", "team", "salary", "paid the guys", "casual")),
    ("fees", ("fee", "fees", "permit", "permits", "council", "rates", "levy", "survey", "surveyor", "architect", "engineer", "approval", "stamp", "legal", "professional")),
    ("transport", ("fuel", "petrol", "diesel", "transport", "delivery", "truck", "hire", "lorry", "trip", "trips", "diesel")),
    ("equipment", ("hire", "equipment", "machine", "mixer", "scaffold", "scaffolding", "compactor", "pump", "generator", "tool", "tools")),
    ("other", ("misc", "miscellaneous", "other", "sundries")),
)

PROPERTY_COST_HINTS = (
    ("rates", ("rates", "council", "city of", "municipal")),
    ("water", ("water", "sewer", "sewage", "zINWA", "water bill")),
    ("insurance", ("insurance", "insured", "cover", "premium")),
    ("repairs", ("repair", "repairs", "fix", "plumber", "electrician", "painter", "maintenance", "geyser", "burst", "leak", "broken", "replaced", "spares")),
    ("management", ("management", "managing agent", "commission", "agent fee")),
    ("levy", ("levy", "body corporate", "complex fee")),
    ("other", ("misc", "other", "sundries")),
)

METHOD_HINTS = (
    ("ECOCASH", ("ecocash", "eco cash", "econet", "mukuru")),
    ("INN_BUCKS", ("innbucks", "inn bucks", "inbucks")),
    ("CASH", ("cash", "usd cash", "notes", "hand")),
    ("CARD", ("card", "swipe", "visa", "mastercard", "pos")),
    ("BANK_TRANSFER", ("bank", "transfer", "eft", "rtgs", "wire", "deposit into", "account")),
    ("OTHER", ("other", "cheque", "check")),
)

STATUS_WORDS = {
    "start": "in_progress",
    "started": "in_progress",
    "starting": "in_progress",
    "begin": "in_progress",
    "begun": "in_progress",
    "underway": "in_progress",
    "in progress": "in_progress",
    "ongoing": "in_progress",
    "complete": "complete",
    "completed": "complete",
    "finish": "complete",
    "finished": "complete",
    "done": "complete",
    "closed": "complete",
    "block": "blocked",
    "blocked": "blocked",
    "stuck": "blocked",
    "halt": "blocked",
    "halted": "blocked",
    "stalled": "blocked",
    "on hold": "blocked",
    "paused": "blocked",
    "stop": "blocked",
}

PRIORITY_WORDS = {
    "urgent": "urgent",
    "emergency": "urgent",
    "asap": "urgent",
    "immediately": "urgent",
    "critical": "urgent",
    "low": "low",
    "minor": "low",
    "whenever": "low",
    "normal": "normal",
    "routine": "normal",
}

_MONEY_OUT_WORDS = (
    "spent",
    "spend",
    "paid",
    "pay",
    "bought",
    "buy",
    "purchase",
    "purchased",
    "expense",
    "cost",
    "costs",
    "charged",
    "invoice for",
)
_MONEY_IN_WORDS = (
    "received",
    "receive",
    "got",
    "deposited",
    "deposit",
    "funded",
    "funding",
    "sent in",
    "topped up",
    "top up",
    "transferred",
    "client paid",
    "paid in",
    "inflow",
)

_UPDATE_WORDS = (
    "update",
    "tell the client",
    "let the client know",
    "inform",
    "note that",
    "add a note",
    "post that",
    "report that",
    "say that",
    "message the client",
)


def _hints(text: str, table) -> str | None:
    lowered = text.lower()
    best_key, best_hits = None, 0
    for key, needles in table:
        hits = sum(1 for needle in needles if needle in lowered)
        if hits > best_hits:
            best_key, best_hits = key, hits
    return best_key


def guess_project_category(text: str) -> str | None:
    return _hints(text, CATEGORY_HINTS)


def guess_property_category(text: str) -> str | None:
    return _hints(text, PROPERTY_COST_HINTS)


def guess_method(text: str) -> str | None:
    return _hints(text, METHOD_HINTS)


def guess_status(text: str) -> str | None:
    lowered = text.lower()
    for phrase, status in sorted(STATUS_WORDS.items(), key=lambda item: -len(item[0])):
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            return status
    return None


def guess_priority(text: str) -> str | None:
    lowered = text.lower()
    for phrase, priority in sorted(PRIORITY_WORDS.items(), key=lambda item: -len(item[0])):
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            return priority
    return None


# ----------------------------------------------------------------------
# One sentence, several instructions
# ----------------------------------------------------------------------

_SPLIT_RE = re.compile(
    r"(\s*(?:;|\.\s+|\band then\b|\bthen\b|\balso\b|\bplus\b|\band\b|\bafter that\b)\s*)",
    re.IGNORECASE,
)


def _is_instruction(piece: str) -> bool:
    tokens = set(words(piece))
    if tokens & set(_VERB_STEMS):
        return True
    return bool(re.search(r"\d", piece)) and len(tokens) >= 3


def split_clauses(text: str) -> list[str]:
    """'record 500 for cement and post an update' -> two instructions.

    The connector only splits when what follows reads like an instruction of its
    own, and when it does not the original words are put back — "sand and
    cement" stays one description, not "sand cement".
    """
    parts = _SPLIT_RE.split(text)
    if len(parts) <= 1:
        return [text.strip()]

    chunks = parts[0::2]
    separators = parts[1::2]

    merged = [chunks[0]]
    for index, chunk in enumerate(chunks[1:]):
        if _is_instruction(chunk):
            merged.append(chunk)
        else:
            merged[-1] = f"{merged[-1]}{separators[index]}{chunk}"
    return [piece.strip(" ,") for piece in merged if piece and piece.strip(" ,")]


# ----------------------------------------------------------------------
# Intent detection
# ----------------------------------------------------------------------


@dataclass
class Intent:
    kind: str
    text: str
    score: float = 1.0
    slots: dict = field(default_factory=dict)


@dataclass
class Context:
    """What the workspace can offer, so names in the sentence can be resolved."""

    projects: list = field(default_factory=list)
    properties: list = field(default_factory=list)


def _project_from(text: str, context: Context):
    if not context.projects:
        return None
    for project in context.projects:
        if _project_phrase(text, project):
            return project
    # A whole-name match still counts; a single shared word does not, or every
    # sentence with "house" in it would pick whichever build has "house" in it.
    lowered = text.lower()
    for project in context.projects:
        for key in ("name", "code"):
            value = (project.get(key) or "").strip().lower()
            if len(value) >= 6 and value in lowered:
                return project
    return None


def _project_phrase(text: str, project) -> str | None:
    """The literal stretch of sentence naming this project, if it does."""
    lowered = text.lower()
    for key in ("name", "code"):
        value = (project.get(key) or "").strip().lower()
        if not value:
            continue
        index = lowered.find(value)
        if index >= 0:
            return text[index : index + len(value)]
        # "12 Acacia Road" is named by "Acacia"; "Greendale Duplex" by "Greendale".
        for token in words(value):
            if len(token) < 4 or token in _GENERIC_NAME_WORDS:
                continue
            match = re.search(rf"\b{re.escape(token)}\b", lowered)
            if match:
                return text[match.start() : match.end()]
    return None


def _property_from(text: str, context: Context):
    if not context.properties:
        return None
    for row in context.properties:
        if _project_phrase(text, row):
            return row
    lowered = text.lower()
    for row in context.properties:
        for key in ("name", "code"):
            value = (row.get(key) or "").strip().lower()
            if len(value) >= 6 and value in lowered:
                return row
    return None


# Instruction words that describe the act of recording, not what was bought.
_INSTRUCTION_WORDS = {
    "i",
    "we",
    "they",
    "please",
    "record",
    "log",
    "add",
    "enter",
    "capture",
    "put",
    "paid",
    "pay",
    "paying",
    "spent",
    "spend",
    "bought",
    "buy",
    "purchased",
    "purchase",
    "received",
    "receive",
    "got",
    "deposited",
    "deposit",
    "was",
    "is",
    "were",
    "just",
    "then",
    "also",
    "usd",
    "dollar",
    "dollars",
    "buck",
    "bucks",
}


def _description(text: str, drop: list[tuple[int, int]], project) -> str:
    """What is left once the figure, the date and the project name are removed."""
    pieces = []
    last = 0
    for start, end in sorted(drop):
        if start < last:
            continue
        pieces.append(text[last:start])
        last = end
    pieces.append(text[last:])
    remainder = " ".join(pieces)

    remainder = re.sub(r"\s+", " ", remainder).strip(" .,;:-")
    tokens = [token for token in remainder.split(" ") if token.lower().strip(",.") not in _INSTRUCTION_WORDS]
    remainder = " ".join(tokens).strip(" .,;:-")
    while tokens and tokens[0].lower().strip(",.") in {
        "for",
        "on",
        "at",
        "to",
        "from",
        "of",
        "in",
        "the",
        "a",
        "an",
        "was",
        "is",
        "it",
        "that",
        "this",
        "my",
        "with",
        "and",
        "spent",
        "spend",
        "paid",
        "pay",
        "bought",
        "buy",
        "purchased",
        "received",
        "receive",
        "got",
        "deposited",
        "deposit",
        "record",
        "log",
        "add",
        "cost",
        "expense",
        "usd",
        "dollars",
        "bucks",
        "please",
    }:
        tokens.pop(0)
    while tokens and tokens[-1].lower().strip(",.") in {
        "for",
        "on",
        "at",
        "to",
        "from",
        "the",
        "a",
        "an",
        "today",
        "yesterday",
        "please",
    }:
        tokens.pop()
    return " ".join(tokens).strip(" .,;:-")


def _money_intent(text: str, context: Context, *, portal: str) -> Intent | None:
    lowered = text.lower()
    amount = best_amount(text)
    out_hit = any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in _MONEY_OUT_WORDS)
    in_hit = any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in _MONEY_IN_WORDS)
    if not amount and not (out_hit or in_hit):
        return None

    tx_type = "EXPENSE" if (out_hit and not in_hit) else ("FUNDING" if in_hit else "EXPENSE")
    if "client" in lowered and any(word in lowered for word in ("paid", "deposit", "sent")):
        tx_type = "FUNDING"
    if "refund" in lowered or "reimburse" in lowered:
        tx_type = "FUNDING"

    drop = []
    if amount:
        drop.append((amount.start, amount.end))
    span = date_span(text)
    if span:
        drop.append(span)

    project = _project_from(text, context) if portal == "project" else None
    property_row = _property_from(text, context) if portal != "project" else None
    named = project or property_row
    if named:
        phrase = _project_phrase(text, named)
        if phrase:
            index = text.lower().find(phrase.lower())
            if index >= 0:
                drop.append((index, index + len(phrase)))

    slots = {
        "type": tx_type,
        "amount": amount.cents if amount else None,
        "occurred": parse_date_ref(text),
        "method": guess_method(text),
        "project": project["id"] if project else None,
        "property": property_row["id"] if property_row else None,
        "category": (
            guess_property_category(text) if portal != "project" else guess_project_category(text)
        ),
        "description": _description(text, drop, project),
    }
    score = 0.55
    if amount:
        score += 0.25
    if out_hit or in_hit:
        score += 0.15
    if slots["description"]:
        score += 0.05
    return Intent("record_money", text, min(score, 1.0), slots)


def _cost_intent(text: str, context: Context) -> Intent | None:
    lowered = text.lower()
    amount = best_amount(text)
    if not amount:
        return None
    if not any(word in lowered for word in ("cost", "expense", "repair", "fix", "rates", "water", "insurance", "levy", "maintenance", "bill")):
        return None
    found = _property_from(text, context)
    if not found and not context.properties:
        return None
    drop = [(amount.start, amount.end)]
    span = date_span(text)
    if span:
        drop.append(span)
    if found:
        phrase = _project_phrase(text, found)
        if phrase:
            index = text.lower().find(phrase.lower())
            if index >= 0:
                drop.append((index, index + len(phrase)))
    return Intent(
        "record_cost",
        text,
        0.8,
        {
            "amount": amount.cents,
            "category": guess_property_category(text) or "other",
            "description": _description(text, drop, None),
            "property": found["id"] if found else None,
            "method": guess_method(text),
            "incurred": parse_date_ref(text),
        },
    )


def _rent_intent(text: str, context: Context) -> Intent | None:
    lowered = text.lower()
    if not any(word in lowered for word in ("rent", "tenant paid", "receipt", "received from")):
        return None
    amount = best_amount(text)
    found = _property_from(text, context)
    invoice_number = None
    match = re.search(r"\b(?:inv|invoice)\s*[-#]?\s*([a-z0-9-]+)\b", lowered)
    if match:
        invoice_number = match.group(1).upper()
    slots = {
        "amount": amount.cents if amount else None,
        "property": found["id"] if found else None,
        "method": guess_method(text),
        "invoice_number": invoice_number,
        "received_at": parse_date_ref(text),
    }
    score = 0.7 + (0.2 if amount else 0) + (0.1 if found else 0)
    return Intent("receipt_rent", text, min(score, 1.0), slots)


_STAGE_VERBS = (
    "start",
    "started",
    "begin",
    "began",
    "complete",
    "completed",
    "finish",
    "finished",
    "block",
    "blocked",
    "halt",
    "pause",
    "paused",
    "mark",
    "set",
    "move",
    "done with",
    "wrap up",
    "stuck",
    "on hold",
)


def _stage_intent(text: str, context: Context, stages) -> Intent | None:
    """A stage move needs a move verb — "the slab is done" is a statement, not
    an instruction to close the oversite slab stage."""
    status = guess_status(text)
    if not status:
        return None
    lowered = text.lower()
    if not any(re.search(rf"\b{re.escape(verb)}\b", lowered) for verb in _STAGE_VERBS):
        return None
    if "stage" not in lowered and not stages:
        return None
    matched = None
    if stages:
        for stage in stages:
            phrase = _project_phrase(text, stage)
            if phrase:
                matched = stage
                break
        if not matched:
            for stage in stages:
                if rate_match(text, stage, keys=("name", "key")) >= 0.78:
                    matched = stage
                    break
    if not matched and "stage" not in lowered:
        return None
    project = _project_from(text, context)
    note = ""
    if status == "blocked":
        reason = re.split(r"\b(?:because|since|as|due to)\b", text, maxsplit=1, flags=re.IGNORECASE)
        note = reason[1].strip(" ,.;:-") if len(reason) > 1 else ""
    slots = {
        "stage": matched["key"] if matched else None,
        "change": status,
        "note": note,
        "project": project["id"] if project else None,
    }
    score = 0.65 + (0.25 if matched else 0) + (0.1 if project else 0)
    return Intent("change_stage", text, min(score, 1.0), slots)


def _update_intent(text: str, context: Context) -> Intent | None:
    lowered = text.lower()
    hit = next((word for word in _UPDATE_WORDS if word in lowered), None)
    if not hit:
        return None
    index = lowered.find(hit)
    message = text[index + len(hit) :].lstrip(" :,-")
    message = re.sub(r"^(that|the client|client|everyone)\s+", "", message, flags=re.IGNORECASE)
    project = _project_from(text, context)
    return Intent(
        "record_update",
        text,
        0.8,
        {"message": message.strip(), "project": project["id"] if project else None},
    )


def _tenant_intent(text: str, context: Context) -> Intent | None:
    lowered = text.lower()
    if "tenant" not in lowered:
        return None
    if not any(word in lowered for word in ("add", "new", "moved in", "moving in", "registered", "sign")):
        return None
    name = ""
    match = re.search(r"(?:named|called|for)\s+([A-Z][\w'.-]*(?:\s+[A-Z][\w'.-]*){0,3})", text)
    if match:
        name = match.group(1).strip()
    phone = None
    phone_match = re.search(r"(\+?\d[\d\s-]{7,14}\d)", text)
    if phone_match:
        phone = re.sub(r"[^\d+]", "", phone_match.group(1))
    found = _property_from(text, context)
    return Intent(
        "add_tenant",
        text,
        0.75,
        {"name": name, "phone": phone, "property": found["id"] if found else None},
    )


def _work_order_intent(text: str, context: Context) -> Intent | None:
    lowered = text.lower()
    triggers = ("work order", "broken", "fix", "leak", "burst", "not working", "stopped working", "repair", "geyser", "blocked drain", "no power", "no water")
    if not any(word in lowered for word in triggers):
        return None
    found = _property_from(text, context)
    title = re.sub(
        r"^(please\s+)?(open|log|create|raise|report)\s+(a\s+|an\s+)?(work order|job|ticket|issue)\s*(for|about|on)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    if found:
        phrase = _project_phrase(text, found)
        if phrase:
            title = re.sub(re.escape(phrase), " ", title, flags=re.IGNORECASE)
    title = re.sub(
        r"[,;]?\s*(it\s+is|it's|this is|that is)?\s*(urgent|an emergency|asap|immediately|critical)\b",
        " ",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(r"\s+", " ", title).strip(" ,.;:-")
    title = re.sub(r"\s+(at|in|on|for|to|from|of|the)$", "", title, flags=re.IGNORECASE)
    if not title:
        title = text.strip()
    return Intent(
        "open_work_order",
        text,
        0.7,
        {
            "title": title,
            "priority": guess_priority(text) or "normal",
            "property": found["id"] if found else None,
        },
    )


CONFIRM_WORDS = {"yes", "y", "yeah", "yep", "correct", "confirm", "sure", "ok", "okay", "do it", "go ahead", "record it", "save it", "true", "right", "affirmative"}
CANCEL_WORDS = {"no", "n", "nope", "cancel", "stop", "never mind", "nevermind", "forget it", "leave it", "abort", "quit"}
UNDO_WORDS = {"undo", "undo that", "reverse that", "reverse it", "take that back", "delete that", "remove that", "that was wrong", "i made a mistake", "wrong entry", "cancel that entry"}
HELP_WORDS = {"help", "commands", "what can you do", "what can i say", "options", "menu", "show commands"}
BRIEF_WORDS = {"catch me up", "brief me", "what's new", "whats new", "summary", "summarise", "summarize", "overview", "how am i doing", "where do i stand", "status report", "give me an update"}

_NAV_VERBS = ("open", "go to", "show me", "take me to", "navigate to", "load", "jump to", "bring up")


def detect_navigation(text: str, destinations) -> dict | None:
    lowered = text.lower().strip()
    if not any(lowered.startswith(verb) for verb in _NAV_VERBS):
        return None
    body = lowered
    for verb in _NAV_VERBS:
        if body.startswith(verb):
            body = body[len(verb) :].strip(" :")
            break
    if not body:
        return None
    options = [{"label": label, "href": href} for label, href in destinations]
    best, runner = resolve_option(body, options, keys=("label",))
    if best and not runner:
        return best
    if best and runner:
        return {"label": "ambig", "options": [best, runner]}
    return None


_QUESTION_WORDS = (
    "how much",
    "how many",
    "how did",
    "how is",
    "how are",
    "what is",
    "what's",
    "whats",
    "what are",
    "what did",
    "when did",
    "when is",
    "who owes",
    "who paid",
    "which",
    "why",
    "where",
    "do i",
    "did i",
    "does",
    "have i",
    "has the",
    "is there",
    "are there",
    "show me",
    "list",
    "tell me",
)


def looks_like_question(text: str) -> bool:
    """A question must never be read as an instruction to write something."""
    lowered = text.lower().strip()
    if lowered.endswith("?"):
        return True
    return any(lowered.startswith(word) for word in _QUESTION_WORDS)


def detect(text: str, context: Context, *, portal: str = "project", stages=None) -> list[Intent]:
    """Every instruction in the sentence, strongest first.

    Reads one clause at a time so "record 500 for cement and post an update"
    becomes two flows rather than one confused one.
    """
    intents: list[Intent] = []
    for clause in split_clauses(normalise(text)):
        cleaned = strip_politeness(clause)
        lowered = cleaned.lower().strip(" .!?")
        asking = looks_like_question(cleaned)

        if lowered in CONFIRM_WORDS:
            intents.append(Intent("confirm", cleaned, 1.0))
            continue
        if lowered in CANCEL_WORDS:
            intents.append(Intent("cancel", cleaned, 1.0))
            continue
        if lowered in UNDO_WORDS:
            intents.append(Intent("undo", cleaned, 1.0))
            continue
        if lowered in HELP_WORDS:
            intents.append(Intent("help", cleaned, 1.0))
            continue
        if lowered in BRIEF_WORDS:
            intents.append(Intent("brief", cleaned, 1.0))
            continue

        if not asking:
            found = _rent_intent(cleaned, context) if portal != "project" else None
            if found:
                intents.append(found)
                continue

            found = _cost_intent(cleaned, context) if portal != "project" else None
            if found:
                intents.append(found)
                continue

            found = _tenant_intent(cleaned, context) if portal != "project" else None
            if found:
                intents.append(found)
                continue

            found = _work_order_intent(cleaned, context) if portal != "project" else None
            if found:
                intents.append(found)
                continue

            # "post an update that the slab is done" is an update, not a stage
            # move, so the explicit update verb is read first.
            found = _update_intent(cleaned, context)
            if found:
                intents.append(found)
                continue

            found = _stage_intent(cleaned, context, stages or [])
            if found:
                intents.append(found)
                continue

            found = _money_intent(cleaned, context, portal=portal)
            if found:
                intents.append(found)
                continue

    return intents


# ----------------------------------------------------------------------
# Corrections aimed at a flow that is already running
# ----------------------------------------------------------------------

_FIELD_WORDS = {
    "amount": ("amount", "figure", "total", "price", "it"),
    "description": ("description", "reason", "what for", "note", "details"),
    "category": ("category", "type of cost", "kind"),
    "method": ("method", "payment method", "how"),
    "stage": ("stage", "step"),
    "priority": ("priority", "urgency"),
    "name": ("name",),
    "phone": ("phone", "number", "cell"),
    "title": ("title", "issue", "what"),
}


def correction(text: str) -> dict | None:
    """'actually 600' or 'make the amount 600' while a flow is waiting."""
    lowered = text.lower().strip()
    trigger = None
    for word in ("actually", "make it", "change it", "change the", "rather", "instead", "i meant", "correction", "sorry", "no,"):
        if lowered.startswith(word):
            trigger = word
            break
    if not trigger:
        return None

    body = lowered[len(trigger) :].strip(" ,:")
    field_name = None
    for name, keys in _FIELD_WORDS.items():
        if any(re.search(rf"\b{re.escape(key)}\b", body) for key in keys):
            field_name = name
            break

    amount = best_amount(body)
    if amount and field_name in (None, "amount"):
        return {"field": "amount", "value": amount.cents}

    if field_name == "method":
        method = guess_method(body)
        if method:
            return {"field": "method", "value": method}
    if field_name == "category":
        category = guess_project_category(body) or guess_property_category(body)
        if category:
            return {"field": "category", "value": category}
    if field_name == "description":
        remainder = re.sub(r"\b(description|reason|note|details|to|is|it|the)\b", " ", body)
        remainder = re.sub(r"\s+", " ", remainder).strip(" ,:")
        if len(remainder) >= 3:
            return {"field": "description", "value": remainder}
    if field_name and len(body) > len(field_name) + 2:
        return {"field": field_name, "value": body.split(field_name, 1)[-1].strip(" ,:=") or None}
    return None
