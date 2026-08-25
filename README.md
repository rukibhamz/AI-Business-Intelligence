# AI Business Intelligence

An AI-powered Business Intelligence platform for **a single business**. Connect your data sources, ask questions in natural language, and get charts, tables, and insights.

## Quick Start

### Prerequisites

- **Python 3.11–3.13** recommended (3.14 may fail on Phase 2 data packages)
- Node.js 18+
- MySQL (XAMPP or standalone)

### 1. Database

```sql
CREATE DATABASE IF NOT EXISTS ai_bi CHARACTER SET utf8mb4;
```

### 2. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy ..\.env.example ..\.env  # edit DATABASE_URL if needed
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

App: http://localhost:5173

**Default login:** `admin@local.dev` / `admin123` (change via `ADMIN_EMAIL` / `ADMIN_PASSWORD` in `.env`)

## Deploying

See **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** for the production runbook —
required configuration, local verification with Docker, hosted setup, and the
post-deploy checklist.

## Build Plan

See **[docs/BUILD_AND_HANDOFF.md](docs/BUILD_AND_HANDOFF.md)** for the full phase-by-phase plan and agent handoff instructions.

| Phase | Status | Focus |
|-------|--------|-------|
| 1 | Complete | Foundation & skeleton |
| 2 | Complete | Data layer & connectors |
| 3 | Complete | Auth & access control |
| 4 | Next | AI query engine |
| 5 | Planned | Dashboards & charts |
| 6 | Planned | Production hardening |

## License

Apache 2.0 — see [LICENSE](LICENSE).
