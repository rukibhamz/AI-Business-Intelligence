# AI Business Intelligence — Build Plan & Agent Handoff

> **Living document.** Update this file at the end of every work session. The next AI agent (or human) should read **Section 2 (Handoff)** first, then continue from the current phase.

---

## 1. Project Overview

**Goal:** Build an AI-powered Business Intelligence platform that lets users connect data sources, ask natural-language questions, and receive charts, tables, and insights.

**Stack (decided):**

| Layer | Technology | Rationale |
|-------|------------|-----------|
| Backend API | Python 3.11+ / FastAPI | Strong AI/ML ecosystem, async, OpenAPI docs |
| Database | MySQL (XAMPP) | Matches local dev environment |
| ORM | SQLAlchemy 2.x | Mature, async-capable |
| Frontend | React 18 + Vite + TypeScript | Fast dev, type safety |
| AI | OpenAI-compatible API | NL → SQL, insight generation |
| Auth | JWT (Phase 3) | Stateless, API-friendly |

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
| **Last updated** | 2026-08-24 |
| **Last agent/session** | Initial build — Phase 1 foundation |
| **Active phase** | Phase 1 — Foundation |
| **Phase status** | 🟡 Nearly complete — backend smoke test pending |
| **Blockers** | Python not installed on dev machine (Windows Store stub only) |

### 2.2 What Was Completed

- [x] Created this build plan & handoff document
- [x] Backend skeleton: FastAPI app, config, database layer
- [x] Core models: `User`, `DataSource`, `Query`, `Dashboard`
- [x] API routes: health, data sources (CRUD skeleton), queries (skeleton)
- [x] Frontend scaffold: Vite + React + TypeScript (build verified)
- [x] Frontend API client + dashboard shell UI
- [x] Vite dev proxy to backend (`/api` → `:8000`)
- [x] `.env.example` with required variables
- [x] Updated `README.md` with setup instructions
- [ ] Backend smoke test — **blocked**: install Python 3.11+ first

### 2.3 What To Do Next

1. **Install Python 3.11+** (https://python.org/downloads — check "Add to PATH")
2. **Finish Phase 1 verification**
   - Run backend: `cd backend && python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt && uvicorn app.main:app --reload`
   - Create MySQL database: `CREATE DATABASE ai_bi;`
   - Copy `.env.example` → `.env` and set `DATABASE_URL`
   - Confirm `GET http://localhost:8000/api/health` returns `{"status":"ok"}`
   - Run frontend: `cd frontend && npm run dev` — UI should show "API Online"
   - Mark Phase 1 task 1.7 complete in §3
3. **Begin Phase 2 — Data Layer**
   - Implement CSV/Excel file upload connector
   - Add MySQL external connection connector
   - Build schema introspection service
   - Wire data preview endpoint
4. **Update this document** after each sub-task (check boxes, update §2.1 status)

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

### Phase 1 — Foundation 🟡 IN PROGRESS

**Objective:** Runnable monorepo skeleton with health checks, DB models, and empty UI shell.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 1.1 | Project structure & config | ✅ Done | `backend/`, `frontend/`, `.env.example` |
| 1.2 | FastAPI app + CORS + lifespan | ✅ Done | `backend/app/main.py` |
| 1.3 | SQLAlchemy models & DB init | ✅ Done | `backend/app/models/` |
| 1.4 | Health + data source route skeleton | ✅ Done | `backend/app/routes/` |
| 1.5 | React + Vite frontend shell | ✅ Done | `frontend/src/` |
| 1.6 | README setup instructions | ✅ Done | Root `README.md` |
| 1.7 | End-to-end smoke test | ⬜ Pending | Requires Python 3.11+ install |

**Exit criteria:** Backend serves `/api/health`; frontend loads; DB tables created.

---

### Phase 2 — Data Layer ⬜ NOT STARTED

**Objective:** Users can connect data sources and preview data.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 2.1 | File upload connector (CSV, Excel) | ⬜ | Store in `uploads/`, parse with pandas |
| 2.2 | MySQL external connector | ⬜ | Connection test + schema introspection |
| 2.3 | Schema registry service | ⬜ | Tables, columns, types cached in DB |
| 2.4 | Data preview API (`GET /api/sources/{id}/preview`) | ⬜ | Paginated rows |
| 2.5 | Frontend: data source management UI | ⬜ | List, add, delete, preview |

**Exit criteria:** Upload a CSV, see schema + first 100 rows in UI.

---

### Phase 3 — Auth & Multi-tenancy ⬜ NOT STARTED

**Objective:** Secure, user-scoped data access.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 3.1 | User registration & login (JWT) | ⬜ | bcrypt password hashing |
| 3.2 | Auth middleware on all routes | ⬜ | Bearer token |
| 3.3 | Row-level ownership on data sources | ⬜ | `user_id` FK enforcement |
| 3.4 | Frontend login/register pages | ⬜ | Token in localStorage |
| 3.5 | Protected routes | ⬜ | Redirect if unauthenticated |

**Exit criteria:** Two users cannot see each other's data sources.

---

### Phase 4 — AI Query Engine ⬜ NOT STARTED

**Objective:** Natural language → SQL → results + explanation.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 4.1 | Schema context builder for LLM | ⬜ | Inject table/column metadata into prompt |
| 4.2 | NL → SQL generation service | ⬜ | OpenAI function calling or structured output |
| 4.3 | SQL validation & sandbox execution | ⬜ | Read-only, timeout, row limits |
| 4.4 | Query history & caching | ⬜ | `Query` model already defined |
| 4.5 | Frontend chat/query interface | ⬜ | Message thread + result table/chart |

**Exit criteria:** Ask "top 10 customers by revenue" against a connected source, get a table back.

---

### Phase 5 — Visualization & Dashboards ⬜ NOT STARTED

**Objective:** Save and share visual insights.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 5.1 | Chart recommendation from result shape | ⬜ | bar, line, pie heuristics |
| 5.2 | Chart rendering (Recharts) | ⬜ | Frontend components |
| 5.3 | Dashboard CRUD API | ⬜ | `Dashboard` model exists |
| 5.4 | Dashboard builder UI | ⬜ | Drag-and-drop widgets |
| 5.5 | Export (PNG, CSV) | ⬜ | Download endpoints |

**Exit criteria:** Pin a chart to a dashboard, reload page, chart persists.

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
| 2026-08-24 | FastAPI + React monorepo | AI/ML ecosystem, async API, modern frontend DX |
| 2026-08-24 | MySQL over PostgreSQL | User runs XAMPP locally |
| 2026-08-24 | OpenAI-compatible API | Flexible provider swap (OpenAI, Azure, local) |
| 2026-08-24 | JWT auth deferred to Phase 3 | Unblock data/AI work with open API first |

---

## 5. Session Log

| Date | Agent/Human | Work Done |
|------|-------------|-----------|
| 2026-08-24 | Initial agent | Created build plan, Phase 1 foundation scaffold, frontend build verified |

---

*End of document. Next agent: start at §2.3.*
