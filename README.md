# AI Business Intelligence

An AI-powered Business Intelligence platform. Connect data sources, ask questions in natural language, and get charts, tables, and insights.

## Quick Start

### Prerequisites

- Python 3.11+
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

## Build Plan

See **[docs/BUILD_AND_HANDOFF.md](docs/BUILD_AND_HANDOFF.md)** for the full phase-by-phase plan and agent handoff instructions.

| Phase | Status | Focus |
|-------|--------|-------|
| 1 | In progress | Foundation & skeleton |
| 2 | Planned | Data layer & connectors |
| 3 | Planned | Auth & multi-tenancy |
| 4 | Planned | AI query engine |
| 5 | Planned | Dashboards & charts |
| 6 | Planned | Production hardening |

## License

Apache 2.0 — see [LICENSE](LICENSE).
