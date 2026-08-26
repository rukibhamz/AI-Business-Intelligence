# AI Business Intelligence — Build Plan & Agent Handoff

> **Living document.** Update this file at the end of every work session. The next AI agent (or human) should read **Section 2 (Handoff)** first, then continue from the current phase.

---

## 1. Project Overview

**Goal:** Build an AI-powered Business Intelligence platform for **a single business** — connect that business's data sources, ask natural-language questions, and receive charts, tables, and insights.

**Scope:** One deployment, one organization, shared data. No multi-tenant isolation between companies.

**Stack (decided):**

| Layer | Technology | Rationale |
|-------|------------|-----------|
| Backend API | Python 3.11+ / FastAPI | Strong AI/ML ecosystem, async, OpenAPI docs |
| Database | MySQL (XAMPP) | Matches local dev environment |
| ORM | SQLAlchemy 2.x | Mature, async-capable |
| Frontend | React 18 + Vite + TypeScript | Fast dev, type safety |
| AI | OpenAI-compatible API | NL → SQL, insight generation |
| Auth | JWT (Phase 3, optional) | Protect the app; single shared workspace |

**Repository layout:**

```
AI-Business-Intelligence/
├── docs/BUILD_AND_HANDOFF.md   ← this file
├── backend/                    ← FastAPI application
├── frontend/                   ← React SPA
├── .env.example                ← environment template
└── README.md
```

---

## 2. Agent Handoff (READ THIS FIRST)

### 2.1 Current Status

| Field | Value |
|-------|-------|
| **Last updated** | 2026-08-26 |
| **Last agent/session** | Question planner + SQL repair loop + narrative fluency |
| **Active phase** | Phase 6 — mostly complete (see §3 Phase 6 table) |
| **Phase status** | Phases 1–5 validated against the code; deploy artifacts in place |
| **Blockers** | None for a soft launch. Open gaps listed in `docs/DEPLOYMENT.md` §6 |

### 2.2 What Was Completed

- [x] Phase 1–5 + Settings branding as previously documented
- [x] Data Sources page from Stitch (upload zone, field mapping, dataset cards)
- [x] Field mapping API (`PUT /sources/{id}/mapping`, recompute, canonical fields)
- [x] **Live analytics engine** — `services/analytics.py` computes KPIs, charts,
      and findings from real rows via the source connectors (stdlib only)
- [x] **`GET /api/insights/overview`** and **`GET /api/insights/findings`**
- [x] **UI upgrade** — Manrope + JetBrains Mono, rebuilt token system with a real
      light/dark theme, scheme-driven accents, restructured sidebar (grouped nav,
      collapse, mobile drawer), command palette (Ctrl/Cmd+K), notifications
      popover, theme toggle, account menu, skeletons and empty states
- [x] **All placeholder data removed** — Overview and Findings were hardcoded
      demo content and now render only computed values
- [x] **Bug fix:** deleting a data source that had been queried returned 500
      (FK violation); dependent queries and dashboard widgets are now purged
- [x] **URL routing** (`lib/router.ts`) — every view has a path, so reload,
      bookmarks, and Back/Forward work; `/` lands on New Analysis
- [x] **Nav consolidation** — removed the sidebar "New analysis" button and the
      topbar "Ask AI" button; the renamed **New Analysis** nav item is the single
      entry point and the landing page
- [x] **Ask AI rebuild** — thread persists across navigation and reload, stop a
      running query, retry a failed one, copy answer, result/chart/SQL as
      separate cards, sticky table headers, timestamps
- [x] **Bug fix:** `POST /queries/run` 422'd because `QueryCreate.data_source_id`
      was required while the UI asks workspace-wide (server was serving stale code)
- [x] **Bug fix:** a 422 body (`detail` as an array of objects) was rendered
      straight into JSX and crashed the page
- [x] **Bug fix:** line charts plotted dates in SQL order (e.g. `ORDER BY revenue`),
      drawing a meaningless zig-zag; `ResultChart` now sorts date labels chronologically
- [x] **Answer-format guardrail** (`services/response_planner.py`) — the server
      decides metric / chart / narrative / table per question and returns
      `response_format`; the UI renders that instead of always drawing a chart
- [x] **Grounded natural-language answers** — `answer` is written from the rows
      that came back (LLM with the rows in the prompt when a key is set,
      otherwise computed arithmetically); stored and replayed in history
- [x] **Diagnostic answers** (`services/diagnostics.py`) — "why did revenue fall"
      used to come back empty: one SELECT has nothing to compare, and the
      narrative prompt is forbidden from going beyond the rows. Those questions
      now take a separate path — latest period vs the one before it, the change
      attributed to the segments that carry it (the dimension that concentrates
      the movement wins), plus price-vs-volume, margin, churned segments and a
      partial-period warning. `response_format` is `diagnostic`; the evidence
      ships in `diagnosis` and is replayed from `queries.diagnosis_json`
- [x] **Recommendations** — questions that ask what to do ("what should we do
      about the loss", "how do we prevent this") come back with `recommendations`:
      each action names the figure that justifies it and a now/next/watch
      priority. Derived arithmetically from the diagnosis; the model only rewords
      them and never sees raw rows, so it has nothing to miscalculate. A "why"
      answer offers follow-up chips rather than unasked-for advice
- [x] **A "why" question never dead-ends** — when the data cannot support a period
      comparison (no date column, one period, no mapped measure), the question is
      not dropped back onto the SQL path that returned nothing. The measured
      comparison that *does* exist plus an explicit list of what is missing goes
      to the model, which states what cannot be answered and why
- [x] **Progress copy** — the thread said "Writing SQL and querying your data…"
      for every question, including the ones that never write SQL. Now a phased,
      implementation-neutral label ("Thinking…" → "Working through your data…")
- [x] **Network errors read as network errors** — a dropped request rendered the
      raw "Failed to fetch"; it now says the server could not be reached
- [x] **Offline planner understands management questions** (`schema_context.metric_sql`)
      — the case study's questions name a metric and a dimension without ever
      saying "by" ("Which products have unusually high return rates?"), so all
      nine fell to `SELECT * LIMIT 10` when no AI key was set. They are now
      planned from the canonical field mapping: return rate, campaign ROI (with
      a repeated budget counted once), delivery days and rating, stock cover,
      target attainment scoped to the latest period, and revenue/profit/margin
      by any named dimension. Verified end to end on all nine
- [x] **An untargeted answer says so** — when the planner cannot target the
      question the reply states that these are sample rows, rather than
      summarising an arbitrary column as though it answered
- [x] **Profit alongside revenue everywhere** — dimension breakdowns carry both
      series, and a new finding names the segment that leads on revenue while
      earning the thinnest margin (`-margin-mix`)
- [x] **Inventory beyond zero** — findings for cover below the reorder level or
      far under the typical level, and for excess stock sitting on capital
- [x] **Campaign ROI on spread, not just break-even** — a 10x efficiency gap
      between two profitable campaigns used to pass silently; ROI per campaign
      is also charted
- [x] **Targets compared period for period** — a target repeated on every row
      describes a period, so attainment reads the latest period against it, and
      locations with no rows in that period are excluded rather than reported at
      0%. Previously showed 541% on six months of data
- [x] **Rates are never summed, mixed, or drawn as a pie** — "total return rate"
      is not a figure, a rate does not share an axis with a count, and rates are
      not slices of a whole
- [x] **Measurement rules in the SQL prompt** (`schema_context.build_measurement_rules`)
      — validated against the configured provider (Mistral `mistral-medium-latest`),
      the model summed a campaign budget repeated on every row (reporting 1.1x
      return where the true figure is 152x), divided returned units by the row
      count instead of units sold (30% vs 14.5%), and stacked six months of
      revenue against a one-period target. None of that is visible in a schema
      listing, so the prompt now carries the dataset's own measurement rules,
      built from the canonical mapping. Re-tested live: 9 of 9 brief questions
      correct, matching the findings engine figure for figure
- [x] **Answers stopped dismissing questions they could answer** — "The data does
      not show stockouts or excess inventory" was returned beside a chart of the
      stock levels. The narrative prompt now requires the figures either way:
      when nothing crosses the threshold the answer says so *and* names the
      highest and lowest. A stock rule also defines what a stockout is, so a
      low-but-nonzero level is reported as thin cover, not a stockout
- [x] **Result charts label their series** — `ResultChart` rendered no legend at
      all, so three bars per group were unreadable. Legend on bar and line
      whenever there is more than one series
- [x] **A hyphen is not a date** — `_looks_temporal` treated any first value
      containing "-" as temporal, so "Abuja-Central" drew a trend line across
      four unrelated stores. Labels now have to parse as periods, and all of
      them, not just the first
- [x] **Averages share an axis with what they average** — avg stock and lowest
      stock are both stock; only percentages and 1-5 ratings get their own scale
- [x] **Supabase authentication** (`services/supabase_auth.py`) — sign-in moves to
      Supabase as soon as `SUPABASE_URL` and `SUPABASE_ANON_KEY` are set, and
      stays local until then, so nothing breaks before the project exists. The
      API verifies the access token itself (HS256 shared secret, or the
      project's JWKS for signing keys), then provisions a local account from
      the verified claims. Local password endpoints close while Supabase is in
      charge — a second front door with different rules is not a fallback
- [x] **Roles** — `users.role` is "admin" or "member". The first account to sign
      in becomes admin, as does `ADMIN_EMAIL`. Admin unlocks Settings and
      nothing else: it is not a key to other people's data
- [x] **Per-account isolation** (`services/ownership.py`) — a dataset belongs to
      whoever uploaded it. Sources, questions, chats, dashboards, findings and
      the overview are all scoped to the caller; another account's row reports
      404, not 403, because "exists but is not yours" is itself information.
      Covered by HTTP-level tests in `tests/test_isolation.py`
- [x] **Settings gated** — writes require an admin, and a member's `GET
      /api/settings` carries branding only: no provider, model, endpoint or key
      state. The UI hides the nav item and refuses the view if the URL is typed
- [x] **`python -m app.scripts.reset_workspace --yes`** — clears datasets,
      questions, chats and dashboards left over from local accounts. A script,
      never a startup step: a live database should not be wiped by a restart
- [x] **Returns recorded as a flag** — a live test reported "All return rates are
      0.0" on a dataset where one product came back 30% of the time. Three
      causes: the AI mapping prompt described Returns as "a count of returns,
      **not a flag name**", so `return_flag` was left unmapped; the text "True"
      sums to zero in both SQL and Python; and `return_flag = TRUE` in SQLite
      compares text to 1 and matches nothing. The mapping now accepts both
      encodings, the analytics read either, and the SQL prompt says how to
      compare a text boolean. A flag counts orders, a quantity counts units —
      the KPI and finding say which
- [x] **No `LIMIT 1` on a ranking** — asked which store earns most, the model
      returned one row, which cannot be compared, cannot be charted, and led to
      answers like "the only store in the results" and "there are no other
      segments to compare". The prompt now requires the whole ranking, and the
      narrative may not claim anything about rows the query did not ask for
- [x] **No filtering a "which" question to nothing** — `HAVING MIN(stock) = 0`
      matched no rows and answered "nothing matches those criteria" while one
      store sat on a sixth of everyone else's cover. Rank, never filter
- [x] **Charts plot the answer, not its ingredients** — the column a query sorts
      by is what it was asked about, so `ORDER BY return_rate_pct` charts the
      rate rather than the order counts beside it. A profitability question
      charts the margin line, not the revenue line. Pie charts are reserved for
      share questions; a ranking is bars
- [x] **Rate limits are waited out, then handed to the next provider** — three
      questions in a row hit the provider's limit mid-demo and failed with an
      httpx URL in the message. Now retried with backoff and, when Settings
      holds more than one provider, retried against the next one in priority
      order — which is what that ordering was always for. If every provider is
      busy the answer says so plainly
- [x] **Charts are readable at a glance** — a store/product answer labelled every
      bar by store alone, printing "Lagos" three times with no way to tell them
      apart, and the vertical axis silently dropped 16 of 20 names because they
      did not fit. A result identified by two columns is now labelled by both
      ("Ibadan · Home Theater System"), and a crowded or long-labelled ranking
      is drawn as horizontal bars, which give every label its own row. Series
      names are written out — "Average stock level", not `avg_stock_level` —
      in the legend, the tooltip and the overview charts
- [x] **Verified against the real NexaSphere dataset** — all ten ground-truth
      questions, 9 exact matches plus one (campaign ROI) correct in ranking and
      reported as net return rather than gross
- [x] **Chart-type fix:** a date axis is never a pie chart
- [x] **Heuristic planner learned GROUP BY** — "revenue by region" now aggregates
      by region instead of dumping rows sorted by revenue; "over time" groups by
      the date column chronologically; counting questions use `COUNT(*)`
- [x] **Analysis sessions** — `queries.session_id` groups the questions asked in
      one sitting; Q&A History shows them as one collapsible analysis
- [x] Sidebar item renamed **Analysis**; "New session" starts a fresh transcript
- [x] Lightweight column migration in `database.py` (`create_all` cannot add
      columns to an existing table); replace with Alembic in Phase 6
- [x] **Phases 1–5 validated against the code** (not just the checkboxes) — see §7
- [x] **Security fix:** `GET /api/sources` returned `connection_config` verbatim,
      leaking external database passwords to any authenticated client. Now redacted,
      with the stored secret preserved on round-trip updates
- [x] **Security fix:** the SQL sandbox allowed `load_extension()`, `readfile()`,
      `pg_read_file()`, `load_file()`, `benchmark()`, `sleep()` — a read-only
      SELECT that still reads files or runs native code. Now blocked, with comments
      stripped first so they cannot mask a keyword
- [x] **Production config guardrail** — `APP_ENV=production` refuses to boot on the
      default `SECRET_KEY`/`ADMIN_PASSWORD`, wildcard or plain-http CORS, or `SQL_ECHO`
- [x] **Portability fix:** the column migration emitted MySQL backticks and would
      have crashed on the Postgres target named in §6. Now dialect-aware; `asyncpg` added
- [x] `/docs`, `/redoc`, `/openapi.json` disabled in production
- [x] Per-user rate limit on `POST /queries/run` (each call can hit a paid provider)
- [x] Dropped the dead `passlib` dependency (unused, and its pin conflicts with bcrypt 4.x)
- [x] **Chat conversations** — new `conversations` table + `/api/conversations`
      (list, open, rename, delete). History is now a list of chats, not single
      questions; opening one loads the whole thread at `/ask?c=<id>` and you can
      keep asking in it. Rows predating conversations still list, each on its own
- [x] **Transcripts moved to the server** — the chat no longer rebuilds from
      `sessionStorage`; it loads from `/api/conversations/{id}`, so a reload or a
      different browser shows the same thread
- [x] Deleting a chat removes its questions and any dashboard widget pinned from
      them (shared `services/cleanup.py`, also used by data-source deletion)
- [x] Sign-in always lands on `/ask`, whatever URL was open before
- [x] Sidebar "Q&A History" renamed **History**
- [x] **Bug fix: date-range questions returned nothing.** "how much did we make
      between march and may?" produced SQL filtering on **2023** against 2026
      data. The planner prompt only listed column names and types, so the model
      guessed a year. Three parts:
      - **Column profiling** (`services/profiling.py`) — date spans, numeric
        bounds, and category values are computed at ingest and stored in
        `schema_json`; the prompt now shows them and states the dataset's span
      - **Prompt rules** — never invent a year; derive it from the shown range
      - **Empty results** — `SUM()` over zero rows returns one NULL row, which
        was reported as "One matching record: total revenue None". Now detected
        as empty and answered with the range the data actually covers
- [x] The offline fallback planner also learned month ranges and `SUM()` totals,
      taking the year from the profile so it cannot invent one either

- [x] **AI field mapping** (`services/ai_mapping.py`) — on upload, MySQL connect,
      or Recompute, the model maps columns to canonical fields using the profiled
      ranges, category values, and real sample rows, not just column names.
      Auto-confirms when the mapping yields at least one measure, so the dashboard
      works with no manual step; otherwise it stays pending for review
      - The model's answer is validated: unknown columns and non-canonical field
        names are discarded and the keyword heuristic fills any gap
      - Falls back silently to the heuristic when no provider is configured or the
        call fails — ingestion never breaks on it
      - `POST /sources/{id}/automap` re-runs it; **Auto-map** button in the UI
      - Sources show **Mapped by AI** vs **Needs mapping**, and the mapping panel
        no longer interrupts every upload

- [x] **Critical fix: reported margin was double the truth.** Two columns could
      claim one canonical field — AI mapping put both `cost` and `marketing_spend`
      on "Cost", and `column_for()` silently returned the first. On a test dataset
      the dashboard reported 60.51% margin against a true 30.84%.
      `resolve_conflicts()` now enforces one column per field across the AI,
      heuristic, and manual paths, demoting losers to Unmapped and surfacing the
      clash as `mapping_conflicts`
- [x] **Vocabulary extended for the case study** — added Employee, Campaign,
      Marketing Spend, Returns, Rating, Delivery Days, Target, Stock, Reorder
      Level, Channel, Customer Segment, Discount
- [x] **Word-aware keyword matching** — `sales_rep` used to map to Revenue on a
      substring match; short tokens now require a whole-word hit so `report_date`
      is not read as an Employee column
- [x] **Grain-aware totals** — a campaign budget repeated on every row was summed
      per row, inflating spend 2.2x and crushing ROI. `total_by_grain()` /
      `aggregate_by_grain()` count a per-group value once
- [x] **New KPIs** — Return Rate, Marketing ROI, Avg Rating, Avg Delivery Days,
      Target Attainment, Stock On Hand
- [x] **New findings** — revenue-up/margin-down divergence (the case study's
      headline risk), high-return products, weak campaign ROI, slow or poorly
      rated delivery partners, locations behind target, stockouts
- [x] Comparison charts cover all six dimensions the case study names, and only
      dimensions that actually vary are charted

- [x] **Multi-table sources** — analytics used to read `tables[0]`, so a database
      connection was analysed on whichever table came first. `pick_primary_table()`
      now scores tables by the business meaning of their columns, the choice is
      stored per source, `POST /sources/{id}/primary-table` changes it, and the UI
      offers a picker. An explicit choice survives a recompute
- [x] **Driver analysis on findings** — a trend finding now names the segments that
      caused the move ("Mostly category: Electronics (-5,040)"), choosing whichever
      dimension concentrates the change and staying silent when it is spread evenly
- [x] **Currency setting** — admins pick from 12 currencies in Settings, defaulting
      to **Naira**. Applies to KPIs, charts, and AI answers (the narrative prompt is
      told the currency so the model does not write dollar signs)
- [x] **Structured question planner** (`services/question_planner.py`) — before SQL,
      factual questions are rewritten into slots (measure, dimension, time window,
      ranking, limit). Heuristic offline; LLM JSON when a key is set. The plan is
      injected into the SQL prompt so the model follows intent instead of guessing.
- [x] **SQL self-check + repair** (`execute_sql_with_repair` in `ai_query.py`) — on
      execution error or blank results (when filters/ranking/time make emptiness
      suspicious), the model gets the failed SQL + reason and rewrites up to twice.
      Mode is reported as `openai+repair` when a repair was used.
- [x] **Narrative fluency** — manager-brief tone in `NARRATIVE_SYSTEM`; slightly
      higher temperature/token budget so answers read as speech, not field dumps

> **Existing sources need a one-off recompute** to gain profiles — open Data
> Sources and press **Recompute** (new uploads profile automatically).

### 2.3 What To Do Next

1. **Deploy:** follow `docs/DEPLOYMENT.md` — it is the runbook, §6 below is the
   hosting rationale
2. Remaining Phase 6 work: Alembic (6.2) and object storage for uploads
3. Close the gaps in `docs/DEPLOYMENT.md` §6 before treating this as production-grade
4. Optional accuracy follow-ups: SQL result shape check vs plan slots; richer
   offline planner coverage without an API key

**Default credentials:** `admin@local.dev` / `admin123`

### 2.4 Conventions for All Agents

- **Minimize scope** — one phase sub-task per PR/session when possible
- **Update §2.2 and §2.3** before ending any session
- **Do not commit secrets** — use `.env` (gitignored), document keys in `.env.example`
- **Match existing patterns** — read surrounding code before adding files
- **Run linters/tests** before marking a task complete
- **Commit only when user asks**

### 2.5 Key Commands

```bash
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt          # runtime (openpyxl + both DB drivers included)
pip install -r requirements-dev.txt      # adds pytest + ruff
uvicorn app.main:app --reload --port 8000

# Checks (same as CI)
pytest
ruff check app tests

# Frontend
cd frontend
npm install
npm run dev                      # http://localhost:5173

# Checks (same as CI)
npx tsc -b --force
npm run lint
npm run build

# Database (XAMPP MySQL)
mysql -u root -e "CREATE DATABASE IF NOT EXISTS ai_bi CHARACTER SET utf8mb4;"

# Full production-shaped stack (Postgres + API + nginx)
cp .env.production.example .env.docker    # then edit the secrets
docker compose --env-file .env.docker up --build
```

> If backend edits appear not to take effect, kill every `uvicorn` process and
> delete `backend/app/**/__pycache__`. Duplicate processes and stale bytecode
> both bit during development; `--reload` was unreliable on this machine.

### 2.6 Environment Variables

See `.env.example`. Minimum for Phase 1:

For production see `.env.production.example` and `docs/DEPLOYMENT.md` §1 — the
API **refuses to start** with `APP_ENV=production` if the security-critical
values are still at their defaults.

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | MySQL (`+aiomysql`) or Postgres (`+asyncpg`) connection string |
| `SECRET_KEY` | JWT signing (Phase 3) |
| `OPENAI_API_KEY` | AI queries (Phase 4) |
| `CORS_ORIGINS` | Frontend URL(s) |

---

## 3. Phase-by-Phase Implementation Plan

### Phase 1 — Foundation ✅ COMPLETE

**Objective:** Runnable monorepo skeleton with health checks, DB models, and empty UI shell.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 1.1 | Project structure & config | ✅ Done | `backend/`, `frontend/`, `.env.example` |
| 1.2 | FastAPI app + CORS + lifespan | ✅ Done | `backend/app/main.py` |
| 1.3 | SQLAlchemy models & DB init | ✅ Done | `backend/app/models/` |
| 1.4 | Health + data source route skeleton | ✅ Done | `backend/app/routes/` |
| 1.5 | React + Vite frontend shell | ✅ Done | `frontend/src/` |
| 1.6 | README setup instructions | ✅ Done | Root `README.md` |
| 1.7 | End-to-end smoke test | ✅ Done | Health, CRUD, frontend build verified |

**Exit criteria:** Backend serves `/api/health`; frontend loads; DB tables created. ✅

---

### Phase 2 — Data Layer ✅ COMPLETE

**Objective:** Connect data sources and preview data.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 2.1 | File upload connector (CSV, Excel) | ✅ Done | stdlib csv + openpyxl; `POST /api/sources/upload` |
| 2.2 | MySQL external connector | ✅ Done | `POST /api/sources/mysql`, test endpoint |
| 2.3 | Schema registry service | ✅ Done | `backend/app/services/schema_registry.py` |
| 2.4 | Data preview API | ✅ Done | Paginated `GET /api/sources/{id}/preview` |
| 2.5 | Frontend: data source management UI | ✅ Done | Upload, MySQL form, list, preview, delete |

**Exit criteria:** Upload a CSV, see schema + first 100 rows in UI. ✅

---

### Phase 3 — Auth & Access Control ✅ COMPLETE

**Objective:** Login to protect the app. All authenticated users share the same business data.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 3.1 | Admin login (JWT) | ✅ Done | Bootstrap admin on empty DB; bcrypt hashing |
| 3.2 | Auth on API routes | ✅ Done | Bearer token via `get_current_user` |
| 3.3 | `user_id` on records for audit | ✅ Done | Set on source/query create |
| 3.4 | Frontend login page | ✅ Done | Token in localStorage |
| 3.5 | Protected routes | ✅ Done | UI gated; 401 clears session |

**Exit criteria:** Unauthenticated users cannot access protected API routes or UI. ✅

---

### Phase 4 — AI Query Engine ✅ COMPLETE (functional)

**Objective:** Natural language → SQL → results + explanation.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 4.1 | Schema context builder for LLM | ✅ Done | `services/schema_context.py` |
| 4.2 | NL → SQL generation service | ✅ Done | OpenAI via httpx; heuristic fallback |
| 4.3 | SQL validation & sandbox execution | ✅ Done | Read-only + LIMIT; CSV/XLSX→SQLite |
| 4.4 | Query history & caching | ✅ Done | Persist + list; no result cache yet |
| 4.5 | Frontend chat/query interface | ✅ Done | Ask AI panel (table; charts → Phase 5) |

**Exit criteria:** Ask "top 10 customers by revenue" against a connected source, get a table back. ✅

---

### Phase 5 — Visualization & Dashboards ✅ COMPLETE (functional)

**Objective:** Save and share visual insights.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 5.0 | App shell + Overview UI | ✅ Done | Live KPIs/charts from `/api/insights/overview` |
| 5.0b | Ask AI chat interface | ✅ Done | Stitch mockup; live `/queries/run` |
| 5.1 | Chart recommendation from result shape | ✅ Done | `services/chart_recommend.py` |
| 5.2 | Chart rendering (Recharts) | ✅ Done | bar / line / pie |
| 5.3 | Dashboard CRUD API | ✅ Done | `/api/dashboards` + widgets |
| 5.4 | Dashboard builder UI | ✅ Done | Findings page; pin from Ask AI (no DnD yet) |
| 5.5 | Export (CSV) | ✅ Done | `GET /queries/{id}/export`; PNG deferred |
| 5.6 | Live findings engine | ✅ Done | `services/analytics.py` + `/api/insights/findings` |
| 5.7 | Theming (light/dark + colour schemes) | ✅ Done | `styles/tokens.css`, `lib/theme.ts` |
| 5.8 | Command palette search | ✅ Done | `components/CommandPalette.tsx` (Ctrl/Cmd+K) |

**Exit criteria:** Pin a chart to a dashboard, reload page, chart persists. ✅

---

### Phase 6 — Production Hardening 🟡 MOSTLY COMPLETE

**Objective:** Deployable, observable, tested system.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 6.1 | Docker Compose (API + Postgres + frontend) | 🟡 Written, unbuilt | `docker-compose.yml`, both Dockerfiles, `frontend/nginx.conf`. **Docker was unavailable on this machine — images have never been built.** CI builds them on first push |
| 6.2 | Alembic migrations | ⬜ Not done | `create_all` + additive column patch in `database.py`. Handles new tables/columns; not changes or drops |
| 6.3 | Unit + integration tests | 🟡 Backend only | 72 pytest tests (sandbox, planner, config guardrails, auth coverage, redaction, rate limiter). No frontend tests |
| 6.4 | Rate limiting & query cost caps | ✅ Done | Per-user limiter on `/queries/run`; `MAX_QUERY_ROWS` caps result size |
| 6.5 | CI pipeline (lint, test, build) | ✅ Written | `.github/workflows/ci.yml` — ruff + pytest, tsc + oxlint + vite build, Docker builds. **Never executed — no push yet** |
| 6.6 | Deployment docs | ✅ Done | `docs/DEPLOYMENT.md` — config, local verification, hosted setup, post-deploy checklist, known gaps |
| 6.7 | Production config guardrail | ✅ Done | Startup aborts on unsafe production settings |
| 6.8 | Secret redaction in API responses | ✅ Done | Source credentials never leave the server |

**Exit criteria:** `docker compose up` brings the full stack; CI green on PR.
**Status:** both are written but neither has been executed here — see the notes above.

---

## 4. Architecture Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-25 | Free deploy: Vercel + Supabase + Render | Frontend on Vercel; Postgres+Storage on Supabase; FastAPI on Render (not Vercel) |
| 2026-08-25 | Floating sidebar + Plus Jakarta | Match sidebar mockup; cooler geometric UI font |
| 2026-08-24 | Cognitive Logic design system | Refined Minimalism; Cobalt Indigo; Hanken + Plus Jakarta |
| 2026-08-24 | Single-business scope (not multi-tenant) | One org per deployment; shared data workspace |
| 2026-08-24 | FastAPI + React monorepo | AI/ML ecosystem, async API, modern frontend DX |
| 2026-08-24 | MySQL over PostgreSQL | User runs XAMPP locally; prod may move to Supabase Postgres |
| 2026-08-24 | OpenAI-compatible API | Flexible provider swap (OpenAI, Azure, local) |
| 2026-08-24 | JWT auth deferred to Phase 3 | Unblock data/AI work with open API first |

---

## 5. Session Log

| Date | Agent/Human | Work Done |
|------|-------------|-----------|
| 2026-08-25 | Agent | Management answers: meta intent (no SQL), prefer narrative, quiet ⋯ tools |
| 2026-08-25 | Agent | Multi AI provider profiles (priority + active switch); fix connection test feedback |
| 2026-08-25 | Agent | Documented free-tier deploy plan (Vercel / Supabase / Render) in handoff §6 |
| 2026-08-25 | Agent | Ask AI: ChatGPT/Claude-style composer; workspace-wide queries (no source picker) |
| 2026-08-25 | Agent | Q&A History screen from Stitch; AI Insights → history, New Analysis → chat |
| 2026-08-25 | Agent | Findings/Reports UI from Stitch; severity cards + color cleanup |
| 2026-08-25 | Agent | Sidebar redesign (floating rail, collapse, tooltips) + Plus Jakarta Sans |
| 2026-08-25 | Agent | Data Sources UI + field mapping from Stitch mockup |
| 2026-08-25 | Agent | Settings: AI provider + branding (name/logo/colors) |
| 2026-08-25 | Agent | Phase 5: Recharts, dashboard CRUD, pin, CSV export |
| 2026-08-25 | Agent | Ask AI chat UI from Stitch; Cognitive Logic shell brand |
| 2026-08-24 | Agent | Overview dashboard + app shell from Stitch mockup |
| 2026-08-24 | Agent | Phase 4 AI Query Engine: run API, sandbox, Ask AI UI |
| 2026-08-24 | Agent | Ingested Cognitive Logic design system (tokens + docs) |
| 2026-08-24 | Agent | Phase 2 validated; Phase 3 JWT auth implemented |
| 2026-08-24 | Agent | Phase 1 validated; Phase 2 data layer implemented |
| 2026-08-24 | Human | Scoped project to single business (removed multi-tenancy) |

---

## 6. Deployment (free tier)

Phases 1–5 are complete. You can soft-launch before finishing all of Phase 6, but you need a hosted API, database, and durable file storage. **Do not put FastAPI on Vercel** — Vercel is for the frontend only.

### 6.1 Two kinds of storage

| Need | Today (local) | Free production options |
|------|---------------|-------------------------|
| App DB (users, sources, queries, dashboards) | XAMPP MySQL | **Supabase** or **Neon** Postgres (migrate from MySQL); managed MySQL is rare on free tiers |
| File uploads (CSV/Excel under `UPLOAD_DIR`) | Local disk | **Supabase Storage** or **Cloudflare R2**; platform volumes if the host offers them |

Ephemeral disks on Render/Railway/Fly lose uploads on redeploy unless you use object storage or a persistent volume.

### 6.2 Recommended free stack

| Piece | Free option | Notes |
|-------|-------------|-------|
| Frontend | **Vercel** Hobby | Build from `frontend/`; set `VITE_API_URL` to the public API (e.g. `https://your-api.onrender.com/api`) |
| Backend | **Render** free web service (or Railway trial / Fly free allowance) | FastAPI + uvicorn; Render **sleeps when idle** (cold starts) |
| Database + files | **Supabase** free (Postgres + Storage) | One account covers both; migrate `DATABASE_URL` to Postgres |
| Alt DB only | **Neon** free Postgres | Pair with R2 or Supabase Storage for files |
| Alt files only | **Cloudflare R2** | Generous free storage; no egress to Workers |

**Simplest all-in-one free path:** Supabase (Postgres + Storage) + Render (API) + Vercel (UI).

### 6.3 Minimum env / config for a live deploy

| Variable | Production value |
|----------|------------------|
| `DATABASE_URL` | Supabase/Neon Postgres connection string (or managed MySQL if kept) |
| `SECRET_KEY` | Strong random secret (not the local default) |
| `OPENAI_API_KEY` | Provider key (or configure via Settings after deploy) |
| `CORS_ORIGINS` | Include the Vercel origin, e.g. `https://your-app.vercel.app` |
| `UPLOAD_DIR` / object storage | Prefer Supabase Storage or R2 over bare disk |
| `VITE_API_URL` (frontend) | Public backend `/api` base URL |

### 6.4 What Supabase does *not* replace

- FastAPI AI/query engine, SQL sandbox, analytics
- Existing JWT auth (optional later: Supabase Auth)

Keep FastAPI as the API; use Supabase for **DB + file blobs**.

### 6.5 Tradeoffs

- Free tiers: size limits, sleep/cold starts, Postgres instead of MySQL
- Fine for demo/portfolio; always-on production usually needs a small paid plan later
- Soft-launch checklist: login → upload → Ask AI → Overview/Findings against prod data

---

*End of document. Next agent: start at §2.3; deploy notes in §6.*

---

## 7. Phase Validation (2026-08-25)

Each phase was re-checked against the code rather than trusting the checkbox.
Verification commands are in §2.5.

| Phase | Claim | Verdict | Evidence |
|-------|-------|---------|----------|
| 1 Foundation | Health, models, routes, UI shell | ✅ Confirmed | `/api/health` → 200; `create_all` + additive column patch; `vite build` passes |
| 2 Data Layer | CSV/Excel + MySQL connectors, schema, preview | ✅ Confirmed | Live upload → schema + row count + preview; MySQL source connects |
| 3 Auth | JWT, protected routes, bootstrap admin | ✅ Confirmed **after a fix** | 36 routes audited by AST; all guarded except login, bootstrap register, and the logo (fetched by `<img>`). Registration self-closes after the first user. Test: `test_every_route_requires_authentication` |
| 4 AI Query | NL→SQL, sandbox, history | 🟡 Confirmed **with fixes** | Sandbox allowed file-reading and code-loading functions — fixed and covered by 30 sandbox tests. Heuristic planner (no-API-key path) is keyword-based and only handles simple shapes |
| 5 Visualization | Charts, dashboards, export, findings | ✅ Confirmed | Live KPIs/charts/findings from real rows; pin persists; CSV export works |
| 6 Hardening | — | 🟡 Mostly done | See the Phase 6 table |

### 7.1 Defects found during validation

All fixed and regression-tested:

1. **External DB passwords returned to the client.** `GET /api/sources` serialized
   `connection_config` verbatim, including `password`. Now redacted; the stored
   secret is preserved if a client sends the mask back.
2. **SQL sandbox allowed dangerous functions.** `SELECT load_extension('evil.so')`
   passed — read-only, but it loads native code in SQLite (used for every CSV/Excel
   query). Also `readfile`, `pg_read_file`, `load_file`, `benchmark`, `sleep`.
   Blocked, and comments are stripped before validation so they cannot mask a keyword.
3. **Postgres-incompatible migration.** The column patch emitted MySQL backticks
   and would have crashed on the Postgres target named in §6. Now dialect-aware.
4. **Missing Postgres driver.** `asyncpg` was absent while §6 recommends Supabase.
5. **Insecure defaults were deployable.** `SECRET_KEY=dev-secret-change-in-production`
   and `ADMIN_PASSWORD=admin123` would have shipped silently. Startup now aborts.
6. **Dead dependency.** `passlib` was pinned but unused, and `passlib==1.7.4` is
   incompatible with `bcrypt>=4.1`. Removed.

### 7.2 Not verified here

Stated plainly so the next person does not assume otherwise:

- **Docker images have never been built** — Docker is not installed on this machine.
  The Dockerfiles and compose file are written and syntactically valid; the CI
  workflow builds them on first push.
- **CI has never run** — no push has happened yet.
- **No Postgres run** — the dialect-aware DDL was exercised against SQLite (which
  shares the standard-quoting path), not against a real Postgres server.
- **No frontend tests exist** — the UI is covered only by typecheck, lint, and build.
