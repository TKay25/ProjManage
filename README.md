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
| Money | Funding and expense ledger in integer US cents, stage tagging, category/method/reference, live balance preview, receipts, and manager-recorded payment tracking |
| Documents | Receipts, statutory documents and site photos, image thumbnails, download, delete, access-checked file serving |
| Agreements | Scope, terms, milestone payment schedule, on-screen signature capture, print/PDF view, void |
| Suppliers | Directory of Zimbabwean material suppliers with links out to their own catalogues |
| WhatsApp | Meta Cloud API webhook (verify + signature check), intent router (`BALANCE`, `STATUS`, `PROJECTS`, `PAY 500`, `RECEIPT`), stored conversation history, in-app simulator |
| PWA | Web manifest, service worker, install prompt, offline fallback page, maskable icons; a project can be saved as an explicit read-only offline copy that survives a signal drop |
| Dashboard | Balance, received, spent, weighted progress, 6-month cash flow chart, attention feed (blocked stages, missing receipts, overdraw), project log |
| **Attention inbox** | `/app/attention` — one cross-project list of approvals due (regulatory gates and unsigned agreements), blocked stages and missing receipts, oldest first; the sidebar and topbar carry a live count of the same items |
| Interaction | Action flows run in dialogs (new project, money, agreement, upload, stage update) with an AJAX form enhancer; sidebar navigation swaps the page in place under a branded overlay loader; public sections fade in on scroll, respecting reduced-motion |
| Record reader | Clicking an agreement opens it in a wide dialog over the list, with signing inside the dialog; a direct link still renders the full page for printing and sharing |
| Sign-up | The header "Get started", the landing CTAs and the login link open a registration dialog; `/register` still works standalone for direct links and no-JavaScript browsers |
| Stage planning | A new project starts with the 19-stage Zimbabwe sequence pre-selected; untick stages the build does not need and the budget re-splits across what is left |
| Search | `Ctrl/⌘ K` (or `/`) opens a command palette that jumps to any section and live-searches projects, ledger entries, documents and agreements, limited to builds the user can already open; the full search page remains for deeper results |
| Shortcuts | `?` opens a cheat-sheet of every key that works (palette, arrows, `↵`, `Esc`); the palette also carries quick actions — record money, upload a document, switch project, toggle compact view |
| Display | Row density (comfortable/compact) and rows per page are saved on the account, so the choice follows the person between devices; density applies to card and row spacing on desktop and phone |
| Themes | `System` (follows the device), `Light` and `Dark`; the topbar button cycles them, Settings picks one directly, and the choice is applied before first paint so there is no flash |
| Weekly digest | `POST /api/whatsapp/digest` with `X-Digest-Token` sends each client a progress-and-balance summary per active project |
| Manager updates | Assigned-manager stage changes, document uploads and ledger entries queue prompt progress/balance updates over each configured email and WhatsApp channel |
| Statements | `GET /app/money/export` streams a CSV of the ledger with a running balance, filtered to whatever the user is viewing; spreadsheet-formula cells are neutralised |
| Search & paging | Server-side search and paging on the ledger, document vault, projects and staff activity, with numbered pages, a clamped page window and a per-user page size; off-screen rows skip layout work |
| Backups | `GET /app/settings/backup` (staff only) streams a zip of a consistent SQLite snapshot plus the uploads folder, from the browser or the desktop menu |
| Desktop app | `desktop/` wraps the same Flask app in an Electron window with a native menu, a local-only server, per-user data folder and optional auto-update |
| Accessibility | Skip link, `aria-current` on navigation plus a non-colour active marker in the mobile tab bar, labelled search and filter controls, scoped table headers, focus trapping and focus restore in dialogs, `prefers-contrast` and reduced-motion support |

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

### Desktop app

`desktop/` is an Electron shell around the same Flask app: it starts the server
on a free loopback port and opens it in a native window with a menu (reload,
open data folder, back up database, check for updates).

```powershell
cd desktop
npm install
npm start          # development: uses .venv and instance/vaka.db
npm run dist       # NSIS installer + portable .exe in desktop/dist
```

A packaged build keeps its database, uploads and session key under `%APPDATA%\YaVaKa`.
Ship a self-contained server by dropping a PyInstaller build in
`desktop/resources/server/` (see [desktop/README.md](desktop/README.md)); until
then the shell expects Python on the machine. Auto-update stays dormant until
`YAVAKA_UPDATE_URL` points at a published generic feed.

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
paging.py               Shared page numbers, clamping and per-user page size
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
routes_attention.py     Cross-project approvals, blocked stages and missing receipts
routes_projects.py      Projects, stage tracking, budget, manager assignment, offline snapshot
routes_money.py         Funding, expenses, receipts
routes_documents.py     Document vault and file serving
routes_agreements.py    Agreements, signing, print view
routes_suppliers.py     In-app supplier directory
routes_whatsapp.py      WhatsApp inbox, simulator, webhook
routes_notifications.py Protected notification outbox dispatcher
routes_settings.py      Profile, password, display preferences, backups

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
static/js/palette.js    Command palette, quick actions, `?` cheat sheet
static/js/offline.js    Opt-in offline snapshot cache and wipe rules
static/sw.js            Service worker (app shell + saved snapshots)
static/icons/           PWA icons
static/img/seed/        Demo receipt images
tests/test_app.py       Smoke and behaviour tests
desktop/                Electron shell, build config and packaging notes
```

---

## Money model

All amounts are stored as **integer US cents** — never floats. Parse with
`parse_money_to_cents()`, render with the `money` Jinja filter. The dashboard
balance is always `SUM(funding) - SUM(expense)` for the project, so it cannot
drift from the ledger.

For YaVaKa-managed builds, payment works one of two ways, at the client's
choice:

- **Client keeps custody.** The client (or their bank) holds the funds. YaVaKa
  verifies progress and **approves** each payment before it is released.
- **YaVaKa is the custodian.** The client places project funds with YaVaKa,
  which **makes the payments** to contractors and suppliers on the project's
  behalf.

Either way, every approval, payment, expense and receipt is written to the
project ledger as it happens. The client can open the record from anywhere in
the world and see it in real time.

The application itself is the auditable record, not a bank account: custody and
release of funds happen under the client's written agreement, outside the app.

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

### Weekly digest

`POST /api/whatsapp/digest` sends every active project's owner a short
progress-and-balance summary. It is protected by its own shared secret, so it is
exempt from the browser CSRF check:

```
DIGEST_TOKEN=another-long-random-string
```

Call it from any scheduler (Render cron job, GitHub Actions, cron + curl):

```bash
curl -X POST https://your-domain/api/whatsapp/digest \
   -H "X-Digest-Token: $DIGEST_TOKEN"
```

With no `DIGEST_TOKEN` the endpoint returns `403`, so an unconfigured deployment
never messages anyone. In simulator mode (no `WHATSAPP_TOKEN`) the sends are
queued locally instead of going out.

Without credentials the app runs in **simulator mode**: `/app/whatsapp` lets you
send messages as the client and see exactly what the assistant would reply, and
messages are stored in the same tables as real traffic.

A client's number is linked to their account by matching `users.phone` (stored
normalised, e.g. `263771234567`).

---

## Automatic project updates

When the assigned build manager changes a stage, uploads a project file or
records funding/an expense, YaVaKa queues a progress-and-balance update for the
project owner. Each channel is enabled independently and only runs when its
credentials are configured.

For email, configure `SMTP_HOST`, `SMTP_PORT`, and `SMTP_FROM_EMAIL`; configure
`SMTP_USERNAME` and `SMTP_PASSWORD` if the relay requires authentication.
`SMTP_USE_TLS=1` uses STARTTLS (the default); set `SMTP_USE_TLS=0` and
`SMTP_USE_SSL=1` for implicit TLS. Do not enable both TLS modes.

For WhatsApp, configure `WHATSAPP_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID`, then
create and approve a Meta message template for proactive updates. Set
`WHATSAPP_UPDATE_TEMPLATE` to its name and `WHATSAPP_UPDATE_LANGUAGE` to the
template language code. The template body must accept the full update in one
text parameter (`{{1}}`).

An in-process worker sends updates immediately and retries transient failures.
The outbox reclaims interrupted sends after a two-minute lease. To recover
pending work after a process restart, configure a scheduler to POST to
`/api/notifications/dispatch` with `X-Notifications-Token`; the endpoint fails
closed until `NOTIFICATIONS_TOKEN` is set:

```bash
curl -X POST https://your-domain/api/notifications/dispatch \
   -H "X-Notifications-Token: $NOTIFICATIONS_TOKEN"
```

Only an assigned manager's changes trigger client notifications. Project
owners, other managers and staff updates are not sent through this event flow.

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
   `WHATSAPP_APP_SECRET`, `WHATSAPP_UPDATE_TEMPLATE`, `SMTP_HOST`,
   `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, and
   `NOTIFICATIONS_TOKEN` when enabling automatic updates.
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
