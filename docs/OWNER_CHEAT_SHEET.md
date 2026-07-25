# NestAI Owner Cheat Sheet

A plain-English guide for managing your NestAI application.
No technical background required for most tasks.

---

## Starting the Application

### Start the Streamlit app (current working version)

```bash
cd legacy/streamlit
pip install -r requirements.txt
streamlit run app.py
```

Open your browser at: **http://localhost:8501**

> This is the working app you have been using. Keep using it until the new
> web application is ready.

---

### Start the local database (PostgreSQL via Docker)

You only need this when running the new FastAPI backend.

```bash
# Make sure Docker Desktop is running, then:
docker compose up -d db
```

The database starts silently in the background and stays running until you
stop it with `docker compose down`.

---

### Start the FastAPI backend

```bash
cd services/api
pip install -r requirements.txt
uvicorn main:app --reload
```

Open your browser at:
- **http://localhost:8000/docs** — interactive API explorer
- **http://localhost:8000/admin/** — admin dashboard (JSON)
- **http://localhost:8000/health** — quick health check

---

## Logging Into the Admin Dashboard

The admin dashboard is a JSON API.  You can explore it using:

1. **Swagger UI** — go to http://localhost:8000/docs, click "Authorize",
   enter your admin email and password
2. **REST client** — use Basic Authentication with your admin credentials

---

## Creating the First Admin Account

You only do this once, right after running database migrations for the first time.

**Step 1 — Run database migrations**

```bash
cd services/api
alembic upgrade head
```

**Step 2 — Set your credentials in environment variables**

```bash
export ADMIN_BOOTSTRAP_EMAIL=you@example.com
export ADMIN_BOOTSTRAP_PASSWORD=YourStrongPassword123!
```

**Step 3 — Run the seed command**

```bash
python -m app.cli.seed_admin
```

You will see:

```
✅  Admin account created for 'you@example.com'
    Log in at http://localhost:8000/admin
    Remove ADMIN_BOOTSTRAP_PASSWORD from your environment once done.
```

**Step 4 — Remove the password from your environment**

```bash
unset ADMIN_BOOTSTRAP_PASSWORD
```

> The seed command is safe to run multiple times.  If the account already
> exists it will tell you and make no changes.

---

## Inviting Beta Testers

### Option A — Via the API (recommended)

```bash
# Create a beta invite code called BETA2025
curl -X POST "http://localhost:8000/admin/beta-codes?code=BETA2025&email_hint=friend@example.com" \
     -u you@example.com:YourPassword
```

### Option B — Legacy Streamlit method

Add the code to your Streamlit secrets under `BETA_CODES`:

```toml
# .streamlit/secrets.toml (local) or Streamlit Cloud dashboard
BETA_CODES = "BETA2025,FRIEND2025"
```

---

## Granting Beta Access to an Existing User

If someone already signed up and you want to mark them as a beta tester:

```bash
# Replace 42 with the user's numeric ID (find it via GET /admin/users)
curl -X POST "http://localhost:8000/admin/users/42/promote-beta" \
     -u you@example.com:YourPassword
```

---

## Reviewing Feedback

```bash
# See all open feedback
curl "http://localhost:8000/admin/feedback?status=new" \
     -u you@example.com:YourPassword

# See all feedback (no filter)
curl "http://localhost:8000/admin/feedback" \
     -u you@example.com:YourPassword
```

Or use the Swagger UI at http://localhost:8000/docs → GET /admin/feedback.

---

## Viewing API Costs

```bash
# Last 30 days of AI usage and estimated cost
curl "http://localhost:8000/admin/ai-costs" \
     -u you@example.com:YourPassword

# Last 7 days
curl "http://localhost:8000/admin/ai-costs?days=7" \
     -u you@example.com:YourPassword
```

---

## Managing Credits

User credit balances are stored in the `credit_balances` table.
You can inspect and adjust them directly in the database (see below)
or through the API once billing endpoints are added in a future phase.

---

## Accessing the Database

### Option A — PostgreSQL command line

```bash
# With Docker running:
docker compose exec db psql -U nestai -d nestai

# Or with the DATABASE_URL from your .env:
psql ******localhost:5432/nestai
```

Common psql commands:

```sql
\dt                          -- list all tables
SELECT * FROM users;
SELECT * FROM feedback_reports ORDER BY created_at DESC LIMIT 10;
SELECT * FROM credit_balances;
\q                           -- quit
```

### Option B — GUI client (DBeaver, TablePlus, pgAdmin)

Connection settings:
| Field    | Value         |
|----------|---------------|
| Host     | localhost     |
| Port     | 5432          |
| Database | nestai        |
| Username | nestai        |
| Password | (from .env)   |

### Option C — Managed cloud provider dashboard

If you deploy to Supabase, Railway, Neon, or Render, each provides a
built-in database browser in their web dashboard.

---

## Running Database Migrations

```bash
cd services/api

# Apply all pending migrations (run this after every deploy)
alembic upgrade head

# Check what migration you are currently on
alembic current

# Roll back the last migration (use with caution)
alembic downgrade -1

# Create a new migration after changing a model
alembic revision --autogenerate -m "describe your change"
```

---

## Finding Each Part of the Codebase

| What you are looking for | Where it lives |
|--------------------------|----------------|
| Working Streamlit app    | `legacy/streamlit/app.py` |
| Streamlit dependencies   | `legacy/streamlit/requirements.txt` |
| Streamlit data / cache   | `legacy/streamlit/data/` |
| FastAPI backend          | `services/api/` |
| Database models          | `services/api/app/db/models/` |
| Database session setup   | `services/api/app/db/session.py` |
| Alembic migrations       | `services/api/alembic/versions/` |
| Alembic config           | `services/api/alembic.ini` |
| Admin API endpoints      | `services/api/app/admin/router.py` |
| Admin seed command       | `services/api/app/cli/seed_admin.py` |
| Environment variables    | `.env` (your local copy, never committed) |
| Environment template     | `.env.example` |
| Docker Compose (local DB)| `docker-compose.yml` |
| Documentation            | `docs/` |

---

## Understanding Which Version Is Which

| Version | Description | Run command |
|---------|-------------|-------------|
| **Streamlit (current)** | The app you have been using. Works today. | `streamlit run legacy/streamlit/app.py` |
| **FastAPI backend (new)** | The new backend being built. Not user-facing yet. | `uvicorn main:app --reload` (from `services/api/`) |
| **Next.js website (future)** | Will become the main user interface. Not built yet. | TBD |
| **Mobile app (future)** | Not started yet. | TBD |

> The Streamlit app will remain the primary user-facing app until the
> Next.js website reaches feature parity and is explicitly retired.

---

## Quick Reference — All Commands

```bash
# Streamlit (always works)
cd legacy/streamlit && streamlit run app.py

# Local database
docker compose up -d db          # start
docker compose down              # stop (data kept)
docker compose down -v           # stop and wipe all data

# FastAPI
cd services/api
pip install -r requirements.txt
alembic upgrade head             # apply migrations
python -m app.cli.seed_admin     # create first admin (once)
uvicorn main:app --reload        # start API server

# Database inspection
psql ******localhost:5432/nestai

# Admin API (Swagger UI)
open http://localhost:8000/docs
```
