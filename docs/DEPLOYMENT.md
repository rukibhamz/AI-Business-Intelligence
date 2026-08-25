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

1. Create the project, copy the pooled connection string.
2. Set `DATABASE_URL=postgresql+asyncpg://USER:PASS@HOST:5432/DB`.
   The `+asyncpg` driver is required; `asyncpg` is already in `requirements.txt`.
3. Tables and the added columns are created on first boot by `init_db()`.
   No manual migration step.

### 3.2 API on Render

1. New → Blueprint → point at this repo. `render.yaml` builds
   `backend/Dockerfile`.
2. Set the secrets marked `sync: false` in the dashboard: `DATABASE_URL`,
   `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `CORS_ORIGINS`, `OPENAI_API_KEY`.
   `SECRET_KEY` is generated for you.
3. The blueprint mounts a 1 GB disk at `/data`. **Without it every uploaded
   CSV is lost on redeploy** — free instances have ephemeral filesystems.
4. Health check is `/api/health`.

> Render's free tier sleeps when idle. The first request after a sleep takes
> ~30 s, which looks like a hang in the UI. Use a paid instance if that matters.

### 3.3 Frontend on Vercel

1. Import the repo, set **Root Directory** to `frontend`.
2. Set `VITE_API_URL` to the public API base, e.g.
   `https://your-api.onrender.com/api`. This is inlined at build time, so
   changing it requires a redeploy.
3. `vercel.json` rewrites unknown paths to `index.html` so `/dashboard`,
   `/findings` etc. deep-link correctly.
4. Add the resulting origin to the API's `CORS_ORIGINS`, then redeploy the API.

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
