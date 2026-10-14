# NestAI

**Live App:** <https://nest--ai--v1.streamlit.app>

Find *your* nest.

---

## Where Everything Is

> Full owner instructions are in [`docs/OWNER_CHEAT_SHEET.md`](docs/OWNER_CHEAT_SHEET.md).

### Application components

| Component | Location | Status |
|-----------|----------|--------|
| **Streamlit app** (current) | `legacy/streamlit/app.py` | Release validation required |
| **FastAPI backend** | `services/api/main.py` | Account persistence and entitlement enforcement |
| **Next.js website** (future) | `apps/web/` | Not started |
| **Mobile app** (future) | `apps/mobile/` | Not started |

### Database

| Item | Location |
|------|----------|
| SQLAlchemy models | `services/api/app/db/models/` |
| Database session | `services/api/app/db/session.py` |
| Alembic migrations | `services/api/alembic/versions/` |
| Alembic config | `services/api/alembic.ini` |
| Legacy SQLite cache | `legacy/streamlit/data/nestai_cache.db` |

### Configuration

| Item | Location |
|------|----------|
| Environment variable template | `.env.example` |
| Your local config (never committed) | `.env` |
| Local database (Docker) | `docker-compose.yml` |

### Running each component locally

```bash
# ── Streamlit (current working app) ──────────────────────────────
cd legacy/streamlit
pip install -r requirements.txt
export NESTAI_API_BASE_URL=http://127.0.0.1:8001
streamlit run app.py
# → http://localhost:8501

# ── Local PostgreSQL database ─────────────────────────────────────
docker compose up -d db

# ── FastAPI backend ───────────────────────────────────────────────
cd services/api
pip install -r requirements.txt
alembic upgrade head          # run migrations first
uvicorn main:app --reload --host 0.0.0.0 --port 8001
# → http://127.0.0.1:8001
# → http://127.0.0.1:8001/docs  (interactive API explorer)
```

Set `NESTAI_API_BASE_URL=http://127.0.0.1:8001` in your local `.env` before starting Streamlit.

For hosted Streamlit Cloud, set this secret:

```toml
NESTAI_API_BASE_URL = "https://YOUR-RENDER-FASTAPI-URL"
```

### Admin dashboard

```bash
# Start the API, then open:
http://127.0.0.1:8001/docs
# Click "Authorize" and enter your admin email + password.
```

### Creating the first admin account

```bash
cd services/api
alembic upgrade head   # run migrations first

export ADMIN_BOOTSTRAP_EMAIL=you@example.com
export ADMIN_BOOTSTRAP_PASSWORD=YourStrongPassword123!
python -m app.cli.seed_admin
```

### Inviting beta testers

```bash
# Create a beta code via the admin API:
curl -X POST "http://127.0.0.1:8001/admin/beta-codes" \
     -u you@example.com:YourPassword \
     -H "Content-Type: application/json" \
     -d '{"email_restriction":"tester@example.com","max_uses":1}'
```

### Inspecting the database

```bash
# psql command line (with Docker running):
docker compose exec db psql -U nestai -d nestai

# Apply pending migrations:
cd services/api && alembic upgrade head
```

### Deploying each component

| Component | Recommended host | Notes |
|-----------|-----------------|-------|
| Streamlit app | [Streamlit Cloud](https://share.streamlit.io/) | Main file path: `legacy/streamlit/app.py` |
| FastAPI backend | Render | Use repository root; include `shared/` and legacy parsers |
| PostgreSQL | Supabase / Neon free tier | Free up to 500 MB |
| Next.js website | Vercel | Not built yet |

### Render FastAPI Configuration

Root directory:
Repository root (leave Render's Root Directory empty).

Build command:
`pip install -r services/api/requirements.txt`

Start command:
`uvicorn --app-dir services/api main:app --host 0.0.0.0 --port $PORT`

Required Render environment variables:

- `DATABASE_URL`
- `NESTAI_OWNER_EMAIL`
- `JWT_SECRET_KEY`
- `JWT_ALGORITHM`
- `ACCESS_TOKEN_EXPIRE_MINUTES`

### MVP regression and release validation

The frontend entrypoint is `legacy/streamlit/app.py`; the backend entrypoint is
`services/api/main.py`. The new API shares `shared/` and the existing legacy
parsers, so deployment must include those repository directories. Use the
repository root for the backend service, install
`services/api/requirements.txt`, and start
`uvicorn --app-dir services/api main:app --host 0.0.0.0 --port "$PORT"`.
The previously documented `services/api` service root is safe only if the host
also makes its sibling directories available. Verify hosting settings and
deployed commit identifiers; matching local traceback lines do not establish
either. No hosting settings have been changed by this implementation.

Install both components' requirements and `requirements-dev.txt`, then install
the test browser with `python -m playwright install chromium`. Supply an
**isolated** PostgreSQL `NESTAI_TEST_DATABASE_URL` and set `TEST_POSTGRES_URL`
to that same test URL for PostgreSQL quota/migration coverage. Set
`NESTAI_BROWSER_DATABASE_URL` to a separate database named `nestai_browser`;
its fixture creates that database using the configured local test PostgreSQL
role. Never point regression tests at a production database.

```bash
make -C /home/runner/work/NestAI/NestAI regression
make -C /home/runner/work/NestAI/NestAI live-smoke
```

`regression` covers deterministic unit tests, API/database tests and actual
Streamlit browser journeys. Legacy unit files run in separate processes because
they replace Streamlit with module mocks. `live-smoke` is separate: configured
provider calls and deployed journeys are required for release, and missing
credentials/access are explicitly blocked rather than counted as passing.
The machine-readable acceptance record is `docs/acceptance-ledger.json`.

Live account-service checks require `NESTAI_RUN_LIVE_TESTS=1`,
`NESTAI_LIVE_API_BASE_URL` (HTTPS), and securely provisioned
`NESTAI_LIVE_FREE_EMAIL`/`NESTAI_LIVE_FREE_PASSWORD`,
`NESTAI_LIVE_PREMIUM_EMAIL`/`NESTAI_LIVE_PREMIUM_PASSWORD`, and
`NESTAI_LIVE_PLUS_EMAIL`/`NESTAI_LIVE_PLUS_PASSWORD`. Use dedicated accounts
with saved samples, not customer accounts. Set
`NESTAI_LIVE_ALLOW_ACCOUNT_OPERATIONS=1` only when provider spending and
report/AI quota consumption on those accounts are authorized. These checks
exercise reauthentication, actual grounded advisor/negotiation calls, neighborhood
enrichment, a public-destination commute, strict filtering, Plus analytics,
and downloaded report/export content. Provider credential-read checks alone
do not prove the advisor works. Neither service smoke checks nor local browser
tests replace the required deployed browser journeys across all three tiers.
Never put credential values in shell history, chat, or repository files.

Account quotas are shared across apartments and houses and reset at midnight
UTC on the first day of each calendar month. A saved apartment building counts
as one property regardless of unit count. Free has 5 successful analyses and
2 active properties; Premium has 100/50; Premium Plus has 500/200, not unlimited.
The separate starting Premium/Plus monthly limits are AI 100/500, enrichment
50/200, commute 100/400 and reports 20/100. Consult the shared entitlement
configuration for supported environment overrides.

Repeated successful requests use account-scoped idempotency; failed requests
must not consume successful-operation quota. Legacy credits and complimentary
grants remain separate and must not be silently converted or discarded.
Downgrades preserve saved records. CSV and decision report downloads require
Premium or Plus, including native table-download controls.

Provider execution belongs in FastAPI. Configure `OPENAI_API_KEY`,
`GOOGLE_MAPS_API_KEY` and `WALKSCORE_API_KEY` there, not only in Streamlit secrets.
Billing additionally needs `STRIPE_SECRET_KEY`, `STRIPE_PREMIUM_PRICE_ID`,
`STRIPE_PREMIUM_PLUS_PRICE_ID`, `STRIPE_WEBHOOK_SECRET` and
`NESTAI_STREAMLIT_URL`. Use Stripe sandbox credentials for all test operations;
never create real charges or send real feedback emails during tests. Optional
integration failures must not prevent authentication, saving or ranking.

**Price reconciliation remains required:** existing UI advertises $12/$25,
the legacy mock service advertised $19/$49, and older documentation advertises
$24.99 for Premium. Verify approved Stripe products before changing prices or
claiming billing readiness. Referrals/support/early-access promises are outside
this MVP; preserve their existing records.

**Legacy recovery:** apartment session DataFrames were not durable database
records. House SQLite rows have random session ownership without an established
account mapping. Back up the hosted SQLite database before changing deployment;
retain unassigned records and their event history. Do not infer ownership from
addresses, timestamps, arbitrary session identifiers or the next signed-in
account. Recovery requires trustworthy historical evidence and an audited
privileged process. Do not delete or automatically import unowned data.

### Deployment acceptance checklist (no hosting changes performed)

1. **Revision and entrypoints:** use branch `copilot/implementation-plan-for-mvp`
   for an authorized acceptance deployment, not an implicit default branch.
   Streamlit main file is `legacy/streamlit/app.py`. Render must use the same
   tested revision, repository root, build command and start command above.
   Record the actual hosting settings and both deployed commit identifiers;
   local traceback correspondence is not deployment verification.
2. **Backups and migrations:** take and verify a restorable PostgreSQL backup;
   separately preserve the hosted legacy `nestai_cache.db` and its SQLite
   journal/WAL consistently. Retain session-owned homes/events without assigning
   unproven owners. Rehearse migrations on an isolated restore, then run the
   authorized pre-deploy command `cd services/api && python -m alembic upgrade head`
   from the repository checkout with the backend environment loaded. Verify
   `python -m alembic current` there. Do not use test database variables for
   production migrations or downgrade/drop tables to roll back application code.
3. **Streamlit secrets:** set `NESTAI_API_BASE_URL` to the verified HTTPS API.
   Provider and Stripe secrets belong only in FastAPI. Leave developer/owner
   preview flags disabled. Reload restores authentication within the same tab;
   saved data must return afterward.
4. **Render environment:**
   - Core: `DATABASE_URL`, `ENVIRONMENT=production`, `JWT_SECRET_KEY`,
     `JWT_ALGORITHM=HS256`, `ACCESS_TOKEN_EXPIRE_MINUTES`,
     `NESTAI_STREAMLIT_URL` (HTTPS frontend), and `SQL_ECHO=false`.
     `PORT` is supplied by Render. Leave `NESTAI_OWNER_EMAIL` unset: it is no longer
     used to grant privileges. Public registration/login never promote an account.
     In an authorized backend operator shell, use `python -m app.cli.seed_admin`
     with securely supplied `ADMIN_BOOTSTRAP_EMAIL` and `ADMIN_BOOTSTRAP_PASSWORD`
     (at least 12 characters), then remove those variables. Bootstrap creates a
     new operator-controlled account and refuses to promote an existing non-admin.
     Audit previously email-promoted administrators against trusted operator
     evidence; do not blindly revoke legitimate administrators or assume these
     previously stored flags become safe just because automatic promotion stopped.
   - Providers: `NESTAI_PROVIDER_MODE=live`, `OPENAI_API_KEY`,
     `OPENAI_MODEL`, `GOOGLE_MAPS_API_KEY`, and `WALKSCORE_API_KEY` if testing
     Walk Score enrichment. Optional output cap: `NESTAI_AI_MAX_OUTPUT_TOKENS`.
     Enable the Google APIs actually called by the backend and restrict keys
     appropriately. Never deploy deterministic mock mode as live acceptance.
   - Billing: sandbox `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
     `STRIPE_PREMIUM_PRICE_ID`, `STRIPE_PREMIUM_PLUS_PRICE_ID`.
     Product-default fallback supports `STRIPE_PREMIUM_PRODUCT_ID` and
     `STRIPE_PREMIUM_PLUS_PRODUCT_ID`, but explicit distinct approved recurring
     price IDs are preferred. Leave `STRIPE_ALLOW_LIVE` unset/false for acceptance.
   - Optional quota overrides: `NESTAI_QUOTA_PREMIUM_AI`,
     `NESTAI_QUOTA_PREMIUM_ENRICHMENT`, `NESTAI_QUOTA_PREMIUM_COMMUTE`,
     `NESTAI_QUOTA_PREMIUM_REPORTS`, and their `NESTAI_QUOTA_PREMIUM_PLUS_*`
     counterparts. Keep approved defaults unless deliberately reviewed.
   - Email: `NESTAI_DISABLE_EMAIL=true` during acceptance to avoid external
     messages. A separately authorized password-reset delivery check requires
     `RESEND_API_KEY`; the existing `onboarding@resend.dev` sender has sandbox
     recipient restrictions. SMTP examples are not substitutes for the active
     Resend reset-email implementation.
5. **Stripe sandbox portal:** in the same sandbox as the backend key, activate
   the default customer-portal configuration, enable subscription updates, and
   include both approved products/recurring prices. Review proration and
   cancellation behavior. Existing plan changes require a real sandbox customer
   and single-item quantity-one subscription created through sandbox checkout,
   not just a complimentary tier grant. Configure HTTPS `/billing/webhook` for
   `checkout.session.completed`, `customer.subscription.created`,
   `customer.subscription.updated`, `customer.subscription.deleted`,
   `invoice.payment_failed`, and `invoice.paid`. Verify signed event delivery,
   then `/billing/status` and `/entitlements` after reauthentication; redirects
   and browser state do not activate a plan.
   Also enable `checkout.session.async_payment_succeeded` if accepting delayed
   sandbox payment methods.
6. **Accounts and CI:** securely provision separate dedicated Free apartment,
   Free house, Free mixed-limit, Premium and Plus acceptance accounts, plus a
   second account for isolation checks. Never use customer data or public
   privileged provisioning. Configure the live-check variables listed above;
   authorize provider spending explicitly. In GitHub Actions approve the latest
   `MVP regression` run for the tested revision, wait for the actual regression
   job (not zero-job `action_required`), and require its successful check.
   CI uses isolated PostgreSQL and mocks; live checks remain separate.
7. **Release evidence:** run `make regression` with isolated PostgreSQL, then
   authorized `make live-smoke` and the deployed desktop/mobile tier journeys.
   Inspect real downloaded files and provider responses, record deployed
   revisions and every skipped/blocked check. Missing credentials, hosting access,
   historical ownership evidence or CI approval are blockers, not passes.

### Authentication remediation and safe deployment order

Migration `0009_auth_version` adds `users.auth_version` with a non-null database
default of zero; it preserves accounts, listings, credits and administrator flags.
Registration/login issue the account version in each access token. All bearer
paths (including administrator endpoints) reject absent, malformed or stale
versions. Deploying the new code therefore requires **every existing user to sign
in again**, even if their old token has not expired. Successful password resets
atomically consume all outstanding reset links, change the password and increment
the version. Old sessions then fail; new-password login restores saved data.
There is no refresh-token issuer, endpoint or stored refresh-token model in this
application; refresh-type JWTs are rejected, not treated as access sessions.

Do not apply these instructions to production until deployment is authorized:

1. Record each service's current revision/settings and current Alembic revision.
   Confirm the new code revision passes `MVP regression`. Schedule maintenance and
   disable automatic deployments so the API cannot start before the schema is ready.
2. Take an access-restricted custom-format PostgreSQL backup (`pg_dump -Fc` using
   securely supplied libpq connection settings), checksum it and verify its archive
   with `pg_restore --list`. Preserve required roles/extensions separately through
   the hosting backup facility. Supply `PGHOST`, `PGPORT`, `PGUSER`, `PGDATABASE`
   and the provider-required `PGSSLMODE`, with `PGPASSFILE` in restricted secret
   storage (or securely injected `PGPASSWORD`); do not place passwords in commands
   or pass the SQLAlchemy `postgresql+psycopg2` URL directly to `pg_dump`.
   Take a consistent SQLite online backup using
   `sqlite3.Connection.backup`, or stop writers before copying the database and
   associated WAL/journal. Keep original ownership/event data unchanged.
3. Restore PostgreSQL into a **new isolated database**, using
   `pg_restore --exit-on-error --no-owner --no-acl`; verify the recorded Alembic
   revision and table counts. Test migrations and login/reset recovery there.
   Restore SQLite into a new file and check `PRAGMA integrity_check` and counts.
   A sandbox backup is not a backup of the hosted production database.
4. With all API writers stopped, run `python -m alembic upgrade head` from
   `services/api` in the full repository checkout, using the authorized backend
   database connection. Verify `python -m alembic current` reports
   `0010_browser_sessions` (verify `alembic heads` before deployment). This is an additive schema change; never assign historical
   SQLite ownership as part of migration.
5. Start Render on the exact tested revision, with repository root, build
   `pip install -r services/api/requirements.txt` and start
   `uvicorn --app-dir services/api main:app --host 0.0.0.0 --port $PORT`.
   Check health, fresh login, revoked-token rejection and preserved listings.
   Then deploy Streamlit on the same revision with `legacy/streamlit/app.py` and
   the verified HTTPS `NESTAI_API_BASE_URL`.
6. Execute dedicated-account desktop/mobile journeys, actual provider responses,
   actual downloaded files and sandbox checkout/portal/webhook transitions.
   Keep deployed acceptance Blocked until these pass; never activate real billing.

**Rollback:** if migration fails, keep writers stopped and verify PostgreSQL's
transaction rolled back before retrying. For an application defect, prefer a
forward fix or a rollback artifact **retaining authentication revocation and
removal of email-only promotion**, leaving the additive column in place.
Redeploying pre-remediation authentication would reactivate stolen tokens and the
admin vulnerability; do not do that. If a data restore is necessary, restore into
a new isolated database, verify integrity, reconcile writes made after the backup,
then obtain explicit approval before switching connections. A pre-reset backup
also restores old passwords/versions: retain newer password/reset state or rotate
the signing key and require fresh account recovery before reopening. Do not
`alembic downgrade` production or drop preserved tables for a code rollback.

**Verification access:** repository files are not hosting-console evidence.
Without authorized Streamlit/Render settings access, deployed commit identifiers,
environment key inventories and remote database/filesystem access, actual hosting
configuration and production backups remain unverified. Do not label required
variables as missing from production merely because they are absent in the agent
sandbox. Provide names/status only, never secret values.

### Reload authentication

Streamlit uses a dedicated opaque restoration credential in tab-scoped
`sessionStorage`, not a bearer JWT in a URL or persistent `localStorage`.
The API stores only its SHA-256 hash in the additive `0010_browser_sessions`
table. Deploy that migration before the matching backend/frontend code.
The credential expires seven days after issuance; logout revokes it, and a
password reset deletes all account restoration credentials atomically with
the password/version update. Restored access tokens still enforce `auth_version`.
Saved properties, preferences and usage remain account-owned database records.

This is reload continuity, not a permanent sign-in guarantee: storage restrictions,
expiry or closing the tab can require sign-in. Browser storage is script-readable,
not an HttpOnly cookie; keep HTTPS and same-origin script protections enabled.
An API outage blocks restoration without discarding the credential. Logout
always clears local authentication/storage, but server revocation requires API
availability; a password reset revokes all outstanding account sessions.

---

User Instructions:
- You may paste text copied from apartments.com (web scraping is not acceptable per apartment.com terms so it must be pasted manually into the app)
- I have pre-loaded 2 sample texts that you can click on
- Click on 'Sample Text 1'
- Then, 'Extract Text' to see the unstructured data become structured
- Click 'Add to comparison table'
- Repeat for the second sample text
- Once both are in the comparison table, you can adjust filters
- There is an LLM powered search tool that will give you the top 3 units based on your specifications, and explain why they are ordered as such

I am looking for apartments and so I created an app to automate and simplify the tedious tasks of manually parsing through apartment listings. This is an AI-powered tool that converts unstructured apartment listing text into structured data and ranks units based on user preferences.

The application helps renters quickly evaluate multiple apartments by extracting pricing, square footage, availability, amenities, and walkability information from copied listing pages and presenting them in a searchable comparison interface.

---

# Product Vision

Apartment search platforms often make it difficult to compare multiple listings because information is spread across different pages and presented inconsistently.

The goal of Apartment Compare AI is to create a lightweight decision-support tool that:

- Converts messy listing text into structured datasets
- Enables side-by-side unit comparison
- Uses AI to match listings with user preferences
- Surfaces the best value units automatically

The product acts as a **personal apartment analysis assistant** for renters evaluating multiple options.

---

# Target Users

Primary users include:

### Urban renters
Evaluating multiple apartment buildings simultaneously.

### Relocating professionals
Comparing listings quickly without manually copying data.

### Students or interns
Trying to maximize value while staying within a budget.

---

# Product Requirements

## Listing Parsing

The system must accept pasted apartment listing text and extract:

- property title
- floorplan information
- unit number
- rent price
- square footage
- availability date
- amenities
- apartment features
- walkability metrics (Walk Score, Transit Score, Bike Score)

---

## Data Structuring

The system converts unstructured listing text into structured rows and calculates additional metrics including:

- rent per square foot
- best deal score
- floor level derived from unit number

---

## Comparison Engine

Users can compare units across listings using:

- price
- size
- availability
- walkability
- building amenities

---

## Filtering & Sorting

Users can filter results by:

- budget
- minimum square footage
- availability window
- floor level

Users can sort results by:

- best deal score
- lowest price
- largest unit
- price per square foot
- soonest availability
- highest floor
- walk score

---

## AI Matching

Users can describe what they want in natural language.

Example:

"I want the best value one-bedroom under $2500 with as much space as possible and available soon."

The system:

1. Converts the prompt into structured preferences using an LLM  
2. Ranks all units against those preferences  
3. Returns the best matches with an explanation  

---

# Design Intent

This project intentionally focuses on three core product design principles.

---

## Reduce Cognitive Load

Apartment listing pages contain large amounts of information that are difficult to compare.

This product simplifies the decision process by:

- structuring data into a table
- computing value metrics automatically
- ranking the best units

Users should be able to identify strong options within seconds.

---

## Augment Decision Making With AI

Instead of manually filtering dozens of listings, users can describe preferences in natural language.

AI converts qualitative user intent into structured filters and scoring logic.

This creates a more intuitive search experience.

---

## Extract Value From Unstructured Data

Most apartment websites do not expose structured listing data for easy comparison.

The parser transforms messy listing text into structured datasets enabling:

- filtering
- ranking
- scoring
- analysis

This demonstrates how lightweight parsing + AI can unlock value from semi-structured web content.

---

# System Architecture
User Interface (Streamlit)
│
▼
Listing Parser
(parser/apartment_listing.py)
│
▼
Structured Dataset
(Pandas DataFrame)
│
├── Value Calculations
│ rent per sqft
│ deal score
│ floor level
│
▼
AI Preference Engine
(llm_helpers.py)
│
▼
AI Ranking Engine
(ranking.py)
│
▼
Interactive Comparison UI

---

# Key Product Features

## Automated Unit Extraction

The parser identifies unit blocks such as:
Unit 1631
price $2,656
square feet 724
availability Now

and converts them into structured records.

---

## Derived Value Metrics

The system calculates signals useful for apartment evaluation:

- rent per square foot
- best deal score
- floor level
- availability timing

---

## Natural Language Apartment Search

Users can describe preferences in plain English.

Example:

and converts them into structured records.

---

## Derived Value Metrics

The system calculates signals useful for apartment evaluation:

- rent per square foot
- best deal score
- floor level
- availability timing

---

## Natural Language Apartment Search

Users can describe preferences in plain English.

Example:

The system translates this into structured ranking criteria.

---

## Intelligent Ranking

Listings are scored based on:

- price efficiency
- size
- availability
- walkability
- AI preference matching

---

# Example Use Case

A renter evaluating several buildings can:

1. Copy listing pages from apartment websites  
2. Paste the content into the tool  
3. Automatically extract unit data  
4. Filter by budget and size  
5. Ask AI to recommend the best units  

The tool produces a ranked shortlist with explanations.

---

# Technology Stack

- Python
- Streamlit
- Pandas
- Regex-based parsers
- OpenAI API (LLM preference parsing & explanations)

---

# Future Enhancements

Potential roadmap improvements include:

- multi-floorplan parsing
- direct listing URL ingestion
- commute-time analysis
- neighborhood scoring
- historical rent trend tracking
- interactive map visualization

---

# Why This Project Matters

This project demonstrates the ability to:

- identify a real user pain point
- design a product around it
- translate product requirements into working software
- integrate AI into a user-facing decision workflow

It showcases both **technical execution and product thinking**, which are critical for product management roles in AI-driven products.
