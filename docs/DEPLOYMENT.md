# Deployment Runbook

Everything needed to take this from a laptop to a live deployment. Read
§1 before doing anything else — the app **refuses to start** in production
until those values are set.

---

## 1. Required configuration

`APP_ENV=production` turns on a startup check
(`backend/app/config.py::validate_runtime`). If any of the following is wrong,
the process logs the reason and exits instead of serving an insecure app.

| Variable | Requirement | Why |
|----------|-------------|-----|
| `SECRET_KEY` | Not the shipped default; ≥ 32 chars | It signs login tokens. The default is public — anyone could mint a valid admin token. |
| `ADMIN_PASSWORD` | Not `admin123`; ≥ 12 chars | Seeds the single admin account on first start. |
| `CORS_ORIGINS` | Exact origins, no `*` | `*` cannot be combined with credentials, and a wildcard exposes the API to any site. |
| | https for non-localhost | Tokens must not cross the network in the clear. |
| `SQL_ECHO` | `false` | Logs every statement and its parameters, including customer data. |

Generate a secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Start from [`.env.production.example`](../.env.production.example).

### Secrets checklist before every `git push`

| Keep out of git | Why |
|-----------------|-----|
| `.env`, `.env.docker`, `.env.production` | Live `SECRET_KEY`, DB passwords, AI keys |
| `uploads/` / `backend/uploads/` | Customer CSVs and Excel files |
| Provider keys pasted into Settings | Stored in the app DB, not in the repo — still rotate if a laptop is shared |
| `*.pem`, `credentials.json`, service-account JSON | Cloud/TLS credentials |

Safe to commit: `.env.example`, `.env.production.example` (placeholders only), and
`render.yaml` where secrets use `sync: false` / `generateValue`.

Quick local check:

```bash
git status
git check-ignore -v .env backend/uploads
# Should show ignored. Never force-add (-f) those paths.
```

If a real key was ever committed, rotate it at the provider and rewrite history
(or treat the key as burned) — removing it from a later commit is not enough.

---

## 2. Verify locally before shipping

```bash
docker compose --env-file .env.docker up --build
```

This runs the production shape: Postgres, the API under a non-root user, and
the UI behind nginx on <http://localhost:8080> with `/api` proxied — so the
browser sees one origin and CORS is not involved.

Run the checks CI will run:

```bash
cd backend && pytest && ruff check app tests
```

```bash
cd frontend && npx tsc -b --force && npm run lint && npm run build
```

---

## 3. Hosted deployment (free tier)

Three pieces. **Do not put FastAPI on Vercel** — it is for the frontend only.

| Piece | Host | Config |
|-------|------|--------|
| Database | Supabase or Neon (Postgres) | Copy the connection string; change the scheme to `postgresql+asyncpg://` |
| API | Render (Docker) | Uses [`render.yaml`](../render.yaml) |
| Frontend | Vercel | Uses [`frontend/vercel.json`](../frontend/vercel.json) |

### 3.1 Database

1. Create the project in Supabase.
2. Set `DATABASE_URL` from **Connect → Connection string → Session pooler**
   (host like `aws-0-<region>.pooler.supabase.com`, port **5432**, user
   `postgres.<project-ref>`). The app rewrites `postgresql://` to
   `postgresql+asyncpg://` automatically.

   **Do not use the Direct connection** (`db.<ref>.supabase.co`). That host is
   IPv6-only; Render’s free tier is IPv4-only and fails with
   `OSError: [Errno 101] Network is unreachable`.

   Example shape (password URL-encoded if it has special characters):

   ```text
   postgresql://postgres.YOUR_REF:YOUR_PASSWORD@aws-0-eu-west-2.pooler.supabase.com:5432/postgres
   ```

3. Tables are created on first boot by `init_db()`, **or** run
   [`docs/supabase_schema.sql`](supabase_schema.sql) in the Supabase SQL Editor
   beforehand. No separate Alembic step yet.

If you deploy as a **native Python** service (not Docker), set the environment
to **Python 3.12** (`backend/runtime.txt`). Python 3.14 often cannot install
`asyncpg`, which shows up as `No module named 'psycopg2'` or a failed wheel build.
Prefer the Docker blueprint in `render.yaml`.

### 3.2 API on Render

1. New → Blueprint → point at this repo. `render.yaml` builds
   `backend/Dockerfile`.
2. Set the secrets marked `sync: false` in the dashboard **before the first
   deploy**: `DATABASE_URL`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `CORS_ORIGINS`,
   `OPENAI_API_KEY`. `SECRET_KEY` is generated for you. Supabase sign-in adds
   `SUPABASE_URL`, `SUPABASE_ANON_KEY` and, for older projects,
   `SUPABASE_JWT_SECRET`.
3. Health check is `/api/health`.

**Disks need a paid instance.** A `disk:` block on `plan: free` is rejected
when the blueprint is validated, so the disk in `render.yaml` is commented out.
On the free plan the filesystem is ephemeral: database rows survive a redeploy,
uploaded CSVs do not. To keep them, switch to `plan: starter`, uncomment the
disk, and set `UPLOAD_DIR=/data/uploads`.

### 3.2.1 Which Supabase connection string to copy

Supabase shows two. **Use the pooler**, not the direct connection:

| | Host | Port | Works on Render free? |
|---|---|---|---|
| Direct connection | `db.<ref>.supabase.co` | 5432 | ✗ IPv6-only; Render's free tier is IPv4-only |
| **Transaction pooler** | `aws-0-<region>.pooler.supabase.com` | 6543 | ✓ |

Copy it from **Project Settings → Database → Connection string → URI**, then
**replace `[YOUR-PASSWORD]`** with the real password. Leaving the placeholder in
is the single most common cause of a failed first deploy — the brackets make the
URL unparseable and the error talks about IPv6 addresses.

If the password contains `@ : / ? # [ ]`, percent-encode it (`@` → `%40`).

### 3.2.2 When the deploy fails

Three failures account for nearly all of them. The logs name the cause in each
case — read them before changing anything.

| What you see | Cause | Fix |
|---|---|---|
| Blueprint rejected before any build | `disk:` on a free instance | Keep the disk commented out, or move to `plan: starter` |
| `'aws-0-….pooler.supabase.com' does not appear to be an IPv4 or IPv6 address` | `DATABASE_URL` still contains Supabase's `[YOUR-PASSWORD]` placeholder. `urlsplit` reads the brackets as an IPv6 host and blames the hostname | Replace the placeholder with the real password. The API now refuses to start with a message naming the placeholder instead of this one |
| `connect() got an unexpected keyword argument 'sslmode'` | libpq-only parameters in `DATABASE_URL` reaching asyncpg | Already handled — the API rewrites `sslmode=require` to `ssl=require` and drops `channel_binding` on startup. If you still see it, the service is running an older build |
| `prepared statement "__asyncpg_stmt_…" does not exist` | Supabase's transaction pooler (port 6543) multiplexes connections | Already handled — statement caching is switched off automatically for pooler URLs |
| Render installs Python 3.14 and `asyncpg` fails to build | A native Python service ignoring `backend/runtime.txt` because the service root is the repo root | `.python-version` and `runtime.txt` now exist at both levels. Better: use the Docker blueprint, which pins 3.12 in the image |
| `Refusing to start with N unsafe production setting(s)` | `SECRET_KEY`, `ADMIN_PASSWORD` (min 12 characters) or `CORS_ORIGINS` (exact https origins, never `*`) not set | Set them in the dashboard and redeploy; the log lists exactly which |

A service that builds but never passes the health check is almost always the
third row: the process aborts on purpose, and Render reports it as a timeout.

> Render's free tier sleeps when idle. The first request after a sleep takes
> ~30 s, which looks like a hang in the UI. Use a paid instance if that matters.

### 3.2.3 "Failed to fetch" when signing in

The browser reports a rejected origin and an unreachable server identically, so
the app now tells them apart for you and says which it is:

- *"The API at … is running but refused a request from … Add … to CORS_ORIGINS"* —
  the API is up; its `CORS_ORIGINS` does not list the frontend's origin. Set it
  to the exact origin (scheme + host, no trailing slash, comma-separated for
  several) and redeploy the **API**.
- *"Could not reach the API at …"* — nothing answered. Either the service is
  down or asleep, or `VITE_API_URL` was wrong when the frontend was built. The
  message names the address it tried, which is what makes a bad build obvious.

Two things that catch people out:

1. `VITE_API_URL` is inlined **at build time**. Changing it in the dashboard does
   nothing until the frontend is rebuilt. It must include `/api`, e.g.
   `https://ai-bi-api.onrender.com/api`.
2. An https frontend cannot call an http API — the browser blocks it as mixed
   content, which also surfaces as "Failed to fetch".

The API logs its allowed origins on every boot:
`Started in production mode | auth: supabase | CORS allows: https://…`

### 3.3 Frontend on Vercel

1. Import the repo, set **Root Directory** to `frontend` (required — otherwise
   `tsc` is missing because install runs at the monorepo root).
2. Framework preset: Vite. Install/Build are taken from `frontend/vercel.json`
   (`npm install` / `npm run build`).
3. Set `VITE_API_URL` to the public API base, e.g.
   `https://your-api.onrender.com/api`. This is inlined at build time, so
   changing it requires a redeploy.
4. `vercel.json` rewrites unknown paths to `index.html` so `/dashboard`,
   `/findings` etc. deep-link correctly.
5. Add the resulting origin to the API's `CORS_ORIGINS`, then redeploy the API.

---

## 4. Post-deploy checklist

Run against the live URL, in order:

- [ ] `GET /api/health` returns `{"status":"ok"}`
- [ ] `/docs` returns **404** (docs are off in production)
- [ ] Log in with the admin account; **change the password**
- [ ] `POST /api/auth/register` returns **403** (registration closes after the first user)
- [ ] Upload a CSV → it appears under Data Sources with a row count
- [ ] Confirm the field mapping → Dashboard shows KPIs and charts
- [ ] Ask a question → an answer comes back with SQL you can inspect
- [ ] Reload a deep link such as `/findings` → it loads that page, not the landing page
- [ ] Redeploy the API → the uploaded CSV is still there (proves the disk is mounted)
- [ ] Fire >20 questions in a minute → the 21st returns **429**
- [ ] Settings → **Currency** shows Naira (₦ NGN) by default; change it and confirm
      KPIs, charts, and AI answers all switch
- [ ] Connect a multi-table database → the source card offers a table picker and
      the dashboard analyses the business table, not the first one alphabetically

---

## 5. Operational notes

**Rate limiting** is in-process (`services/rate_limit.py`), so the limit is per
instance. Running more than one API instance multiplies the effective limit;
move to Redis before scaling out.

**Uploads** live on disk under `UPLOAD_DIR`. For more than one instance, or for
durability beyond a single volume, move them to object storage (Supabase
Storage / Cloudflare R2) — this is not implemented yet.

**External data-source passwords** are stored in the `data_sources` table as
JSON. They are redacted in every API response, but they are **not encrypted at
rest** — anyone with database access can read them. Restrict database access
accordingly; encrypting them is open work.

**Generated SQL** is constrained by `services/sql_sandbox.py`: one statement,
must start with `SELECT`/`WITH`, no write or DDL keywords, and no filesystem or
code-loading functions. Give the reporting database user **read-only**
permissions as a second layer — do not rely on the sandbox alone.

**Backups** are whatever the database host provides. Supabase and Neon both
snapshot on the free tier; verify the retention window meets your needs.

---

## 6. Known gaps

These are open and deliberately not claimed as done:

| Gap | Impact | Suggested fix |
|-----|--------|---------------|
| One table analysed per source | Dashboard reads the selected table only; no joins across tables or sources | Multi-table joins in the SQL planner |
| Targets compared against the whole loaded period | A monthly target read over six months of data reports inflated attainment | Scope target attainment per period |
| No Alembic | Schema changes rely on `create_all` plus the additive column patch in `database.py`. Column *changes* and drops are not handled. | Adopt Alembic before the schema churns further |
| Uploads not on object storage | Multi-instance deploys cannot share uploaded files | Supabase Storage or R2 adapter behind the connector interface |
| Source passwords unencrypted at rest | DB compromise exposes external DB credentials | Encrypt with a key from the environment |
| In-process rate limiting | Limit is per instance | Redis-backed limiter |
| No frontend tests | UI regressions are caught only by typecheck/lint | Vitest + a few component tests |
| No error tracking | Failures are only in stdout | Sentry or the host's log drain |
