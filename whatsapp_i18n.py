"""Reply copy for the WhatsApp assistant, in the languages agents actually use.

Every reply the assistant sends goes through `t()`, so switching a contact's
language changes the whole conversation - greetings, menus, balances, errors -
not just the first line.

English is the default. Shona and Ndebele strings are deliberately short and
plain; have a native speaker review them before a wide rollout.
"""

DEFAULT_LANGUAGE = "en"

LANGUAGES = {"en": "English", "sn": "Shona", "nd": "Ndebele"}

# Menu ids are stable machine values; titles are localised below.
CLIENT_MENU = (
    "balance",
    "status",
    "documents",
    "receipt",
    "projects",
    "contact",
    "language",
)
MANAGER_MENU = (
    "portfolio",
    "approvals",
    "update",
    "clients",
    "documents",
    "escalate",
    "language",
)

STRINGS = {
    # ---------- openings ----------
    "greeting_client": {
        "en": "Hello {name}. {project} - tap an option or reply with a number.",
        "sn": "Mauya {name}. {project} - sarudza option kana kupindura nenhamba.",
        "nd": "Wamkelekile {name}. {project} - khetha okukodwa noma uphendule ngenombolo.",
    },
    "greeting_manager": {
        "en": "Hello {name}. {projects} project(s) under you, {pending} needing attention.",
        "sn": "Mauya {name}. Zvirongwa {projects}, zvinoda kutariswa {pending}.",
        "nd": "Wamkelekile {name}. Imisebenzi {projects}, kudinga ukunakwa {pending}.",
    },
    "greeting_unknown": {
        "en": (
            "Hello. This number is not linked to a YaVaKa project yet.\n\n"
            "Ask your build manager to save this number on your project, "
            "or reply *LANGUAGE* to change language."
        ),
        "sn": (
            "Mhoro. Nhamba iyi haisati yabatanidzwa nechirongwa cheYaVaKa.\n\n"
            "Kumbira maneja wako kuti aise nhamba iyi pachirongwa chako, "
            "kana pindura *MUTAURO* kuti uchinje mutauro."
        ),
        "nd": (
            "Sawubona. Le nombolo ayikaxhunyaniswa nomsebenzi we-YaVaKa.\n\n"
            "Cela umphathi wakho ukuthi afake le nombolo emsebenzini wakho, "
            "noma uphendule *ULIMI* ukutshintsha ulimi."
        ),
    },
    "menu_more": {
        "en": "More options",
        "sn": "Zvimwe",
        "nd": "Okunye",
    },
    "language_prompt": {
        "en": "Choose a language. Every reply will use it from now on.",
        "sn": "Sarudza mutauro. Mhinduro dzose dzichashandisa uyu kubva zvino.",
        "nd": "Khetha ulimi. Zonke izimpendulo zizosebenzisa lolu kusukela manje.",
    },
    "language_set": {
        "en": "Language set to English.",
        "sn": "Mutauro waiswa kuShona.",
        "nd": "Ulimi lubekwe kuNdebele.",
    },
    "unknown": {
        "en": "I did not understand that. Reply with a number or tap an option.",
        "sn": "Handina kuzvinzwisisa. Pindura nenhamba kana kusarudza option.",
        "nd": "Angizwisisanga. Phendula ngenombolo noma ukhethe okukodwa.",
    },
    "help_footer": {
        "en": "A human from your build team reads these messages during working hours.",
        "sn": "Munhu weboka rako rekuvaka anoverenga mameseji aya munguva yebasa.",
        "nd": "Umuntu weqembu lakho lokwakha ufunda le milayezo ngesikhathi somsebenzi.",
    },

    # ---------- client replies ----------
    "balance_received": {
        "en": "Received: {amount}",
        "sn": "Zvasvika: {amount}",
        "nd": "Okwamukelwe: {amount}",
    },
    "balance_used": {
        "en": "Used: {amount}",
        "sn": "Zvashandiswa: {amount}",
        "nd": "Okusetshenzisiwe: {amount}",
    },
    "balance_available": {
        "en": "Available: {amount}",
        "sn": "Zviripo: {amount}",
        "nd": "Okukhona: {amount}",
    },
    "status_progress": {
        "en": "Progress: {percent}% ({done}/{total} stages)",
        "sn": "Kufambira mberi: {percent}% ({done}/{total} nhanho)",
        "nd": "Inqubekela phambili: {percent}% ({done}/{total} izigaba)",
    },
    "status_now": {
        "en": "Now: {stage}",
        "sn": "Iye zvino: {stage}",
        "nd": "Manje: {stage}",
    },
    "status_done": {
        "en": "All stages complete.",
        "sn": "Nhanho dzose dzapera.",
        "nd": "Zonke izigaba ziqediwe.",
    },
    "status_blocked": {
        "en": "This stage is on hold - your manager will call you.",
        "sn": "Nhanho iyi yakamiswa - maneja wako achakufonera.",
        "nd": "Lesi sigaba simisiwe - umphathi wakho uzokushayela.",
    },
    "projects_heading": {
        "en": "Your projects",
        "sn": "Zvirongwa zvako",
        "nd": "Imisebenzi yakho",
    },
    "receipt_help": {
        "en": (
            "How to send a receipt\n\n"
            "1. Open YaVaKa - Documents - Upload receipt\n"
            "2. Or send the photo here and your manager will attach it.\n\n"
            "Always include the amount, supplier and project name."
        ),
        "sn": (
            "Mashandisiro ekutumira risiti\n\n"
            "1. Vhura YaVaKa - Documents - Upload risiti\n"
            "2. Kana tumira foto pano, maneja wako achaisa.\n\n"
            "Isa mari, mutengesi uye zita rechirongwa."
        ),
        "nd": (
            "Indlela yokuthumela irisidi\n\n"
            "1. Vula YaVaKa - Documents - Upload irisidi\n"
            "2. Noma thumela isithombe lapha, umphathi uzosifaka.\n\n"
            "Faka imali, umthengisi kanye nebizo lomsebenzi."
        ),
    },
    "deposit_logged": {
        "en": "Logged a {amount} deposit notice for {project}.",
        "sn": "Kunyorwa {amount} yemari yekuisa mu {project}.",
        "nd": "Kubhaliswe {amount} yemali yokufaka ku-{project}.",
    },
    "deposit_pending": {
        "en": (
            "Status: pending verification - your manager will match it to the "
            "bank or EcoCash entry and attach the proof."
        ),
        "sn": (
            "Mamiriro: kumirira kusimbiswa - maneja wako achaienzanisa nebhangi "
            "kana EcoCash uye aise humbowo."
        ),
        "nd": (
            "Isimo: kulindele ukucinisekiswa - umphathi uzakuqhathanisa nebhange "
            "noma i-EcoCash bese efaka ubufakazi."
        ),
    },
    "deposit_bad": {
        "en": "I could not read that amount. Try PAY 500 or PAY 1,250.50. Nothing is recorded yet.",
        "sn": "Handina kuverenga mari iyoyo. Edza PAY 500 kana PAY 1,250.50. Hapana chanyorwa.",
        "nd": "Angikwazanga ukufunda leyo mali. Zama PAY 500 noma PAY 1,250.50. Akukho okubhaliwe.",
    },

    # ---------- manager replies ----------
    "portfolio_empty": {
        "en": "You have no projects assigned yet.",
        "sn": "Hauna zvirongwa zvakupihwa.",
        "nd": "Awukabi nemisebenzi oyinikiwe.",
    },
    "portfolio_line": {
        "en": "{name} ({code}) - {percent}% - {status}",
        "sn": "{name} ({code}) - {percent}% - {status}",
        "nd": "{name} ({code}) - {percent}% - {status}",
    },
    "approvals_none": {
        "en": "Nothing is waiting on you. Every stage is either complete or not started.",
        "sn": "Hapana chakumirira iwe. Nhanho dzose dzapera kana kusati dzatanga.",
        "nd": "Akukho okulindile kuwe. Zonke izigaba ziqediwe noma aziqalanga.",
    },
    "approvals_line": {
        "en": "{name}: {detail}",
        "sn": "{name}: {detail}",
        "nd": "{name}: {detail}",
    },
    "clients_empty": {
        "en": "You have no client contacts on record yet.",
        "sn": "Hauna mazita evatengi akanyorwa.",
        "nd": "Awunabo abaklayenti ababhalisiwe.",
    },
    "clients_line": {
        "en": "{name} - {phone}",
        "sn": "{name} - {phone}",
        "nd": "{name} - {phone}",
    },
    "update_usage": {
        "en": "To post an update, reply: UPDATE <project code> <message>\n\nExample: UPDATE YVK-0001 Brickwork finished on the north wall.",
        "sn": "Kutumira mashoko, pindura: UPDATE <code yechirongwa> <mashoko>\n\nMuenzaniso: UPDATE YVK-0001 Brickwork yapera.",
        "nd": "Ukuthumela isaziso, phendula: UPDATE <ikhodi yomsebenzi> <umlayezo>\n\nIsibonelo: UPDATE YVK-0001 Izitini ziqediwe.",
    },
    "update_saved": {
        "en": "Update posted to {project}. The client has been notified.",
        "sn": "Mashoko atumirwa ku {project}. Mutengi aziviswa.",
        "nd": "Isaziso sithunyelwe ku-{project}. Iklayenti lazisiwe.",
    },
    "update_unknown_project": {
        "en": "No project with that code is assigned to you.",
        "sn": "Hapana chirongwa necode iyoyo chakupihwa.",
        "nd": "Akukho msebenzi waleyo khodi onikiwe.",
    },
    "escalate_sent": {
        "en": "Sent to the YaVaKa team. Someone will reply here.",
        "sn": "Zvatumirwa kuboka reYaVaKa. Mumwe achapindura pano.",
        "nd": "Kuthunyelwe eqenjini le-YaVaKa. Omunye uzophendula lapha.",
    },

    # ---------- menu titles ----------
    "menu_balance": {"en": "Balance", "sn": "Mari iripo", "nd": "Imali ekhona"},
    "menu_status": {
        "en": "Build progress",
        "sn": "Kufambira mberi",
        "nd": "Inqubekela phambili",
    },
    "menu_projects": {"en": "My projects", "sn": "Zvirongwa zvangu", "nd": "Imisebenzi yami"},
    "menu_receipt": {"en": "Send a receipt", "sn": "Tumira risiti", "nd": "Thumela irisidi"},
    "menu_contact": {
        "en": "Talk to my manager",
        "sn": "Taura nemaneja",
        "nd": "Khuluma nomphathi",
    },
    "menu_language": {"en": "Language", "sn": "Mutauro", "nd": "Ulimi"},
    "contact_details": {
        "en": "{name} - {phone}\n\nThey read these messages during working hours.",
        "sn": "{name} - {phone}\n\nVanoverenga mameseji aya munguva yebasa.",
        "nd": "{name} - {phone}\n\nBafunda le milayezo ngesikhathi somsebenzi.",
    },
    "menu_portfolio": {"en": "My projects", "sn": "Zvirongwa zvangu", "nd": "Imisebenzi yami"},
    "menu_approvals": {
        "en": "Needs attention",
        "sn": "Zvinoda kutariswa",
        "nd": "Kudinga ukunakwa",
    },
    "menu_update": {"en": "Post an update", "sn": "Tumira mashoko", "nd": "Thumela isaziso"},
    "menu_clients": {"en": "My clients", "sn": "Vatengi vangu", "nd": "Amaklayenti ami"},
    "menu_escalate": {"en": "Contact YaVaKa", "sn": "Bata YaVaKa", "nd": "Xhumana ne-YaVaKa"},
    "menu_documents": {
        "en": "My documents",
        "sn": "Magwaro angu",
        "nd": "Amadokhumenti ami",
    },
    "documents_heading": {
        "en": "Your latest documents",
        "sn": "Magwaro ako ekupedzisira",
        "nd": "Amadokhumenti akho akamuva",
    },
    "documents_empty": {
        "en": "No documents have been uploaded for this project yet.",
        "sn": "Hapana magwaro akaiswa pachirongwa ichi.",
        "nd": "Akukho madokhumenti afakwe kulo msebenzi.",
    },
    "documents_footer": {
        "en": "These links work for 7 days. Reply DOCUMENTS any time to get them again.",
        "sn": "Zvinongedzo izvi zvinoshanda mazuva 7. Pindura DOCUMENTS chero nguva.",
        "nd": "Lezi zixhumanisi zisebenza izinsuku eziyi-7. Phendula DOCUMENTS noma nini.",
    },
}

# Words that switch language, in all three languages plus the menu ids.
LANGUAGE_WORDS = {
    "language": None,
    "languages": None,
    "lang": None,
    "mutauro": None,
    "ulimi": None,
    "lang_en": "en",
    "lang_sn": "sn",
    "lang_nd": "nd",
    "english": "en",
    "shona": "sn",
    "ndebele": "nd",
}


def normalise_language(value: str) -> str:
    candidate = (value or "").strip().lower().replace("-", "_")
    if candidate.startswith("lang_"):
        candidate = candidate.split("_", 1)[1]
    return candidate if candidate in LANGUAGES else DEFAULT_LANGUAGE


def t(key: str, language: str = DEFAULT_LANGUAGE, **values) -> str:
    """Look up a reply in the contact's language, falling back to English."""
    entries = STRINGS.get(key)
    if not entries:
        return key
    text = entries.get(normalise_language(language)) or entries[DEFAULT_LANGUAGE]
    if not values:
        return text
    try:
        return text.format(**values)
    except (KeyError, IndexError):
        return text


def menu_for(role: str) -> tuple[str, ...]:
    """Managers get their own workspace; everyone else gets the client menu."""
    return MANAGER_MENU if role == "manager" else CLIENT_MENU


def menu_titles(items, language: str) -> list[tuple[str, str]]:
    """[(menu_id, localised title)] for a menu definition."""
    return [(f"m_{key}", t(f"menu_{key}", language)) for key in items]
