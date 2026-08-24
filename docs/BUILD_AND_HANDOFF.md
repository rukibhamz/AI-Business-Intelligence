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
| **Last updated** | 2026-08-24 |
| **Last agent/session** | Ingested Cognitive Logic design system |
| **Active phase** | UI Design (parallel) + Phase 4 next for features |
| **Phase status** | Design system ingested — awaiting Login mockup |
| **Blockers** | None |

### 2.2 What Was Completed

- [x] Phase 1 validated: health API, sources CRUD, frontend build
- [x] Phase 2 validated: upload, MySQL, preview, frontend build
- [x] Phase 3: JWT login (`POST /api/auth/login`), `/me`, bootstrap admin
- [x] Phase 3: Protected source/query API routes (401 without token)
- [x] Phase 3: `user_id` set on create for audit
- [x] Phase 3: Frontend login gate + Bearer token + logout
- [x] Design system **Cognitive Logic** ingested (`docs/DESIGN_SYSTEM.md`, `frontend/src/styles/tokens.css`)

### 2.3 What To Do Next

1. **Review Login UI** at http://localhost:5173 (log out if already signed in)
2. **Upload next screen mockup** (app shell / sidebar recommended)
3. Feature work remains Phase 4+ — prefer mockup-driven UI while design track is active

**Default credentials** (change via `ADMIN_*` env vars): `admin@local.dev` / `admin123`

**Design reference:** [docs/DESIGN_SYSTEM.md](./DESIGN_SYSTEM.md)

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
| 2026-08-24 | Cognitive Logic design system | Refined Minimalism; Cobalt Indigo; Hanken/Inter/Geist |
| 2026-08-24 | Single-business scope (not multi-tenant) | One org per deployment; shared data workspace |
| 2026-08-24 | FastAPI + React monorepo | AI/ML ecosystem, async API, modern frontend DX |
| 2026-08-24 | MySQL over PostgreSQL | User runs XAMPP locally |
| 2026-08-24 | OpenAI-compatible API | Flexible provider swap (OpenAI, Azure, local) |
| 2026-08-24 | JWT auth deferred to Phase 3 | Unblock data/AI work with open API first |

---

## 5. Session Log

| Date | Agent/Human | Work Done |
|------|-------------|-----------|
| 2026-08-24 | Agent | Ingested Cognitive Logic design system (tokens + docs) |
| 2026-08-24 | Agent | Phase 2 validated; Phase 3 JWT auth implemented |
| 2026-08-24 | Agent | Phase 1 validated; Phase 2 data layer implemented |
| 2026-08-24 | Human | Scoped project to single business (removed multi-tenancy) |

---

*End of document. Next agent: start at §2.3.*
