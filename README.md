# YaVaKa

**Build from anywhere.** YaVaKa is a construction project management platform for
Zimbabweans in the diaspora who are building a home back home. It tracks the
build from stand due diligence and council plan approval through to the
Certificate of Occupation — with every dollar sent, every expense and every
receipt in one auditable record.

Built with **Flask + Jinja + vanilla JS** (Python modules in this root folder,
templates in `templates/`, assets in `static/`).

---

## Why it exists

Building from London, Johannesburg or Dubai usually means trusting a cousin, a
WhatsApp group and a notebook. YaVaKa turns that into a record you can audit:

- **Money you sent vs money actually spent**, with a receipt attached to every expense.
- **The real Zimbabwean approval sequence**, including the regulatory gates that stop a build.
- **One document file** for plans, council receipts, delivery notes and handover certificates.
- **WhatsApp as a first-class client** — the people on the ground may never open a dashboard.

---

## What is included

| Area | What works today |
| --- | --- |
| Authentication | Register, login, logout, hashed passwords, signed session cookies, per-request CSRF tokens, login throttling |
| Roles & access | `client`, `manager`, `admin`; a project is only visible to its owner, its build manager, or YaVaKa staff |
| **Staff portal** | `/admin` — every workspace in one table, platform money totals, attention feed, people & role management, account creation, activity log, stage reference |
| Projects | Create with stand/suburb/budget; the 19-stage Zimbabwe plan and budget split are generated automatically |
| Stages | 5 groups, 19 stages, 5 regulatory gates, notes, status transitions, weighted progress %, budget-vs-actual per stage |
| Money | Funding and expense ledger in integer US cents, stage tagging, category/method/reference, live balance preview, delete and re-attach receipts |
| Documents | Receipts, statutory documents and site photos, image thumbnails, download, delete, access-checked file serving |
| Agreements | Scope, terms, milestone payment schedule, on-screen signature capture, print/PDF view, void |
| Suppliers | Directory of Zimbabwean material suppliers with links out to their own catalogues |
| WhatsApp | Meta Cloud API webhook (verify + signature check), intent router (`BALANCE`, `STATUS`, `PROJECTS`, `PAY 500`, `RECEIPT`), stored conversation history, in-app simulator |
| PWA | Web manifest, service worker, install prompt, offline fallback page, maskable icons |
| Dashboard | Balance, received, spent, weighted progress, 6-month cash flow chart, attention feed (blocked stages, missing receipts, overdraw), project log |
| Interaction | Action flows run in dialogs (new project, money, agreement, upload, stage update) with an AJAX form enhancer; sidebar navigation shows a branded overlay loader and uses the View Transitions API where supported |
| Record reader | Clicking an agreement opens it in a wide dialog over the list, with signing inside the dialog; a direct link still renders the full page for printing and sharing |
| Sign-up | The header "Get started", the landing CTAs and the login link open a registration dialog; `/register` still works standalone for direct links and no-JavaScript browsers |
| Statements | `GET /app/money/export` streams a CSV of the ledger with a running balance, filtered to whatever the user is viewing; spreadsheet-formula cells are neutralised |
| Search & paging | Server-side search and paging on the ledger, projects and staff activity, with page numbers clamped so a stale link never shows a blank screen |
| Accessibility | Skip link, `aria-current` on navigation, labelled search and filter controls, scoped table headers, focus trapping and focus restore in dialogs |

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

Demo data is opt-in. Pass `SEED_DEMO=true` before the first run:

```powershell
$env:SEED_DEMO="true"; python app.py
```

| Role | Email | Password |
| --- | --- | --- |
| Client | `client@yavaka.co.zw` | `YaVaKa2026!` |
| Build manager | `manager@yavaka.co.zw` | `YaVaKa2026!` |
| YaVaKa staff | `admin@yavaka.co.zw` | `YaVaKa2026!` |

Set `SEED_DEMO=false` to start with an empty workspace (the supplier directory is
always seeded). On a fresh install with demo seeding enabled, a staff account is
created automatically if none exists.

### Staff portal

YaVaKa staff sign in and use **/admin** (`admin` role only):

- `/admin` — platform totals, every project with client/manager, attention feed
- `/admin/projects` — searchable table of all workspaces; open any project with full controls
- `/admin/people` — change roles, create logins for build managers on the ground
- `/admin/activity` — who changed what, across every workspace
- `/admin/stages` — the Zimbabwe stage plan staff can quote from

Clients and managers get `403` on every `/admin` route.

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

YaVaKa never touches client money: it is a record, not a wallet, bank or escrow.

---

## Going live with WhatsApp

1. Create a Meta app with the WhatsApp product and a business phone number.
2. Set the environment variables (Render dashboard, `.env`, or your host's secret store):

   ```
   WHATSAPP_TOKEN=EAAG...            # permanent system-user token
   WHATSAPP_PHONE_NUMBER_ID=123456789
   WHATSAPP_VERIFY_TOKEN=some-random-string
   WHATSAPP_APP_SECRET=...           # enables X-Hub-Signature-256 checks
   ```

   `WHATSAPP_VERIFY_TOKEN` has **no default**: the webhook returns `403` until it
   is set, so a forgotten variable can never leave a public verification open.

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

The production entrypoint is `wsgi:app` ([wsgi.py](./wsgi.py)). Anything that speaks
WSGI can host it.

### Render (recommended)

`render.yaml` is a ready blueprint:

1. Render Dashboard -> **New -> Blueprint** -> pick this repo.
2. Render creates the web service, generates `SECRET_KEY`, and mounts a **1 GB disk
   at `/var/data`**. The disk is not optional: without it the SQLite file and every
   uploaded receipt are wiped on each deploy.
3. Set the secrets flagged `sync: false` in the dashboard before going live:
   `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`,
   `WHATSAPP_APP_SECRET`.
4. Health checks hit `/health`, which probes the database for read **and** write
   access, so a read-only or missing disk fails the deploy instead of silently
   breaking sign-ups.

The blueprint already sets the values that matter for safety:

| Variable | Production value | Why |
| --- | --- | --- |
| `SEED_DEMO` | `false` | No demo accounts are created, and the login page stops advertising credentials |
| `COOKIE_SECURE` | `1` | Session cookie is `Secure`; HSTS is sent on HTTPS requests |
| `SECRET_KEY` | generated | Sessions cannot be forged across deploys |
| `DATABASE_FILE` | `/var/data/vaka.db` | Lives on the persistent disk |
| `UPLOAD_DIR` | `/var/data/uploads` | Receipts survive redeploys |

`TRUST_PROXY` is on by default so `ProxyFix` honours Render's
`X-Forwarded-Proto`; that is what lets the app detect HTTPS and send HSTS.

### Any other WSGI host

```powershell
python -m pip install waitress
waitress-serve --port=8000 wsgi:app
```

Gunicorn is POSIX-only (`fcntl`), so it cannot run on a Windows dev machine — use
waitress there. On Linux:

```bash
gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 8 --timeout 60 wsgi:app
```

Keep the worker count low. Every worker is a separate process sharing one SQLite
file; threads handle concurrency better than extra processes here.

### Checklist before pointing real clients at it

- `SEED_DEMO` is `false`, and no demo account can log in.
- `SECRET_KEY` is set to a long random value and is not in the repo.
- `COOKIE_SECURE=1`, and the site is served over HTTPS.
- `DATABASE_FILE` and `UPLOAD_DIR` sit on a persistent volume, with backups.
- `WHATSAPP_VERIFY_TOKEN` is set — the webhook returns `403` until it is.
- `/health` returns `200`.

---

## Limitations

- **Stage guidance is a checklist, not legal advice.** Fees, forms and inspection
  rules differ by local authority (Harare, Bulawayo, Mutare, Gweru…). Confirm
  requirements with the council, EMA, ZINWA and ZESA.
- Single SQLite file: perfect for a pilot, swap for Postgres before running many
  concurrent workspaces.
- No card or bank integration: funding is **recorded**, not collected inside the
  app. Where YaVaKa manages the build, payments to builders and suppliers are
  made from the project account and logged against the stage they belong to.
- The supplier directory is a convenience index. YaVaKa takes no commission from
  the suppliers listed in it.
