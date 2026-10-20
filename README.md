# Vaka

**Build from anywhere.** Vaka is a construction project management platform for
Zimbabweans in the diaspora who are building a home back home. It tracks the
build from stand due diligence and council plan approval through to the
Certificate of Occupation — with every dollar sent, every expense and every
receipt in one auditable record.

Built with **Flask + Jinja + vanilla JS** (Python modules in this root folder,
templates in `templates/`, assets in `static/`).

---

## Why it exists

Building from London, Johannesburg or Dubai usually means trusting a cousin, a
WhatsApp group and a notebook. Vaka turns that into a record you can audit:

- **Money you sent vs money actually spent**, with a receipt attached to every expense.
- **The real Zimbabwean approval sequence**, including the regulatory gates that stop a build.
- **One document file** for plans, council receipts, delivery notes and handover certificates.
- **WhatsApp as a first-class client** — the people on the ground may never open a dashboard.

---

## What is included

| Area | What works today |
| --- | --- |
| Authentication | Register, login, logout, hashed passwords, signed session cookies, per-request CSRF tokens, login throttling |
| Roles & access | `client`, `manager`, `admin`; a project is only visible to its owner, its build manager, or an admin |
| Projects | Create with stand/suburb/budget; the 19-stage Zimbabwe plan and budget split are generated automatically |
| Stages | 5 groups, 19 stages, 5 regulatory gates, notes, status transitions, weighted progress %, budget-vs-actual per stage |
| Money | Funding and expense ledger in integer US cents, stage tagging, category/method/reference, live balance preview, delete and re-attach receipts |
| Documents | Receipts, statutory documents and site photos, image thumbnails, download, delete, access-checked file serving |
| Agreements | Scope, terms, milestone payment schedule, on-screen signature capture, print/PDF view, void |
| Suppliers | Directory of Zimbabwean material suppliers with links out to their own catalogues |
| WhatsApp | Meta Cloud API webhook (verify + signature check), intent router (`BALANCE`, `STATUS`, `PROJECTS`, `PAY 500`, `RECEIPT`), stored conversation history, in-app simulator |
| PWA | Web manifest, service worker, install prompt, offline fallback page, maskable icons |
| Dashboard | Balance, received, spent, weighted progress, 6-month cash flow chart, attention feed (blocked stages, missing receipts, overdraw), project log |

---

## Run it

Requires Python 3.10+ (tested on 3.14) and Flask 3.

```powershell
python -m pip install -r requirements.txt
python app.py
```

Then open <http://localhost:3000>.

The database, session key and uploads are created on first run:

- `instance/vaka.db` — SQLite database
- `instance/secret.key` — generated session signing key (or set `SECRET_KEY`)
- `uploads/` — receipts and documents

### Demo accounts

| Role | Email | Password |
| --- | --- | --- |
| Client | `client@vaka.co.zw` | `Vaka2026!` |
| Build manager | `manager@vaka.co.zw` | `Vaka2026!` |

Set `SEED_DEMO=false` to start with an empty workspace (the supplier directory is
always seeded).

### Tests

```powershell
python -m unittest discover -s tests -v
```

---

## Project layout

```
app.py                  Flask app factory, template filters and globals
config.py               Configuration and secrets handling
db.py                   SQLite connection, schema, query helpers
auth.py                 Sessions, password hashing, CSRF, access control
money.py                Money/date formatting (integer cents everywhere)
stages.py               The 19-stage Zimbabwe build sequence and budgets
suppliers.py            Seed supplier directory
queries.py              Read models (totals, cash flow, missing receipts)
storage.py              Upload validation and storage
whatsapp.py             Meta Cloud API client + conversation assistant
seed.py                 Demo workspace seeding
ui.py                   Icon set and small render helpers

routes_auth.py          Register / login / logout
routes_public.py        Landing, public suppliers, PWA assets, health
routes_dashboard.py     Signed-in dashboard
routes_projects.py      Projects, stage tracking, budget, manager assignment
routes_money.py         Funding, expenses, receipts
routes_documents.py     Document vault and file serving
routes_agreements.py    Agreements, signing, print view
routes_suppliers.py     In-app supplier directory
routes_whatsapp.py      WhatsApp inbox, simulator, webhook
routes_settings.py      Profile and password

templates/              Jinja templates
  base.html             Public shell
  app/base.html         Workspace shell (sidebar, topbar, mobile tab bar)
  partials/             Header, footer, sidebar, flash, transaction row
  app/                  Dashboard, projects, money, documents, agreements, suppliers, WhatsApp, settings
  auth/                 Login, register
  errors/               Error page

static/css/app.css      Brand tokens, public site, auth, forms
static/css/portal.css   Workspace, tables, charts, chat, print
static/js/app.js        Progressive enhancement (drawer, money form, uploads, install)
static/js/signature.js  Signature pad
static/js/whatsapp.js   Simulator chat
static/sw.js            Service worker
static/icons/           PWA icons
static/img/seed/        Demo receipt images
tests/test_app.py       Smoke and behaviour tests
```

---

## Money model

All amounts are stored as **integer US cents** — never floats. Parse with
`parse_money_to_cents()`, render with the `money` Jinja filter. The dashboard
balance is always `SUM(funding) - SUM(expense)` for the project, so it cannot
drift from the ledger.

Vaka never touches client money: it is a record, not a wallet, bank or escrow.

---

## Going live with WhatsApp

1. Create a Meta app with the WhatsApp product and a business phone number.
2. Set the environment variables:

   ```
   WHATSAPP_TOKEN=EAAG...            # permanent system-user token
   WHATSAPP_PHONE_NUMBER_ID=123456789
   WHATSAPP_VERIFY_TOKEN=some-random-string
   WHATSAPP_APP_SECRET=...           # enables X-Hub-Signature-256 checks
   ```

3. In Meta → WhatsApp → Configuration, set the callback URL to
   `https://your-domain/api/whatsapp/webhook` and the same verify token.
4. Subscribe to the `messages` field.

Without credentials the app runs in **simulator mode**: `/app/whatsapp` lets you
send messages as the client and see exactly what the assistant would reply, and
messages are stored in the same tables as real traffic.

A client's number is linked to their account by matching `users.phone` (stored
normalised, e.g. `263771234567`).

---

## Deploying

Any WSGI host works. Minimal example:

```powershell
python -m pip install waitress
waitress-serve --port=8000 app:app
```

Checklist:

- Set `SECRET_KEY` to a long random value.
- Set `COOKIE_SECURE=1` behind HTTPS.
- Put `instance/` and `uploads/` on persistent storage (or point `DATABASE_FILE`
  and `UPLOAD_DIR` at a mounted volume).
- Terminate TLS at the proxy; the app sets sensible security headers itself.

---

## Limitations

- **Stage guidance is a checklist, not legal advice.** Fees, forms and inspection
  rules differ by local authority (Harare, Bulawayo, Mutare, Gweru…). Confirm
  requirements with the council, EMA, ZINWA and ZESA.
- Single SQLite file: perfect for a pilot, swap for Postgres before running many
  concurrent workspaces.
- No payment gateway is wired in — funding is recorded, not collected.
- The supplier directory is a convenience index. Vaka takes no commission and
  does not process supplier payments.
