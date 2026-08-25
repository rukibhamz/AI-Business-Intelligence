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
| **Last updated** | 2026-08-25 |
| **Last agent/session** | Answer-format guardrail + analysis sessions |
| **Active phase** | Core product screens complete; Phase 6 next |
| **Phase status** | All screens render live data; no placeholder content remains |
| **Blockers** | None |

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
- [x] **Chart-type fix:** a date axis is never a pie chart
- [x] **Heuristic planner learned GROUP BY** — "revenue by region" now aggregates
      by region instead of dumping rows sorted by revenue; "over time" groups by
      the date column chronologically; counting questions use `COUNT(*)`
- [x] **Analysis sessions** — `queries.session_id` groups the questions asked in
      one sitting; Q&A History shows them as one collapsible analysis
- [x] Sidebar item renamed **Analysis**; "New session" starts a fresh transcript
- [x] Lightweight column migration in `database.py` (`create_all` cannot add
      columns to an existing table); replace with Alembic in Phase 6

### 2.3 What To Do Next

1. Review the app at http://localhost:5173 (upload a CSV with date/revenue/region
   columns to see the full dashboard populate)
2. Phase 6: Docker, Alembic, tests, CI when ready

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
pip install -r requirements.txt
pip install -r requirements-phase2.txt   # Phase 2: openpyxl for Excel
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev                      # http://localhost:5173

# Database (XAMPP MySQL)
mysql -u root -e "CREATE DATABASE IF NOT EXISTS ai_bi CHARACTER SET utf8mb4;"
```

### 2.6 Environment Variables

See `.env.example`. Minimum for Phase 1:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | MySQL connection string |
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

### Phase 6 — Production Hardening ⬜ NOT STARTED

**Objective:** Deployable, observable, tested system.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 6.1 | Docker Compose (API + MySQL + frontend) | ⬜ | |
| 6.2 | Alembic migrations | ⬜ | Replace create_all |
| 6.3 | Unit + integration tests | ⬜ | pytest + vitest |
| 6.4 | Rate limiting & query cost caps | ⬜ | Protect AI endpoints |
| 6.5 | CI pipeline (lint, test, build) | ⬜ | GitHub Actions |
| 6.6 | Deployment docs | ⬜ | |

**Exit criteria:** `docker compose up` brings full stack; CI green on PR.

---

## 4. Architecture Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-25 | Floating sidebar + Plus Jakarta | Match sidebar mockup; cooler geometric UI font |
| 2026-08-24 | Cognitive Logic design system | Refined Minimalism; Cobalt Indigo; Hanken + Plus Jakarta |
| 2026-08-24 | Single-business scope (not multi-tenant) | One org per deployment; shared data workspace |
| 2026-08-24 | FastAPI + React monorepo | AI/ML ecosystem, async API, modern frontend DX |
| 2026-08-24 | MySQL over PostgreSQL | User runs XAMPP locally |
| 2026-08-24 | OpenAI-compatible API | Flexible provider swap (OpenAI, Azure, local) |
| 2026-08-24 | JWT auth deferred to Phase 3 | Unblock data/AI work with open API first |

---

## 5. Session Log

| Date | Agent/Human | Work Done |
|------|-------------|-----------|
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

*End of document. Next agent: start at §2.3.*
