<div align="center">

# Care-Connect

### Telemedicine & Electronic Medical Records, built for Bangladesh

Verified-doctor video consultations, encrypted patient records, and digital
prescriptions — in English and Bangla.

![Next.js](https://img.shields.io/badge/Next.js-14-000000?logo=nextdotjs&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-4169E1?logo=postgresql&logoColor=white)
![Tests](https://img.shields.io/badge/tests-93%20backend%20%2B%2014%20frontend-brightgreen)

</div>

---

## Overview

Care-Connect is a full-stack Electronic Medical Record (EMR) and clinic
management platform with integrated, peer-to-peer video consultations. It models
the full outpatient journey — registration, appointment booking, secure video
visits, clinical record-keeping, and emailed PDF prescriptions — across three
role-based experiences for patients, doctors, and clinic administrators.

The platform is designed for the Bangladeshi health-tech market: mobile-first,
fully localized (English / বাংলা), priced in BDT, and engineered around patient
privacy with field-level encryption and a HIPAA-style audit trail.

## Highlights

- **Peer-to-peer video** — WebRTC media flows directly between browsers; the
  server brokers only SDP/ICE signaling over WebSocket, never the media stream.
- **Encryption at rest** — sensitive patient fields are encrypted with
  AES-256-GCM; keys live only in the environment, never with the data.
- **Digital prescriptions** — doctors issue prescriptions that are rendered to a
  branded PDF and emailed to the patient through a durable, retrying outbox.
- **Role-based access control** — patients, doctors, and admins each see only
  what they are authorized to, enforced at the API and row level with auditing.
- **Bilingual & local** — English/Bangla UI, BDT currency, DD/MM/YYYY dates.
- **Tested to spec** — 53 correctness properties verified with property-based
  tests (Hypothesis on the backend, fast-check on the frontend).

## Roles

| Role    | Capabilities |
|---------|--------------|
| Patient | Register, search doctors, book/cancel/reschedule, join video visits, view records, download prescriptions |
| Doctor  | Manage profile & availability, conduct consultations, record vitals/diagnoses, issue prescriptions |
| Admin   | Approve doctors, manage user accounts, monitor clinic activity |

## Architecture

```
┌────────────────────────┐         HTTPS / WSS          ┌───────────────────────────┐
│  Next.js frontend       │  ───────────────────────▶   │  FastAPI backend (Render)  │
│  (Vercel)               │                              │   REST API + signaling     │
│  • App Router, TS       │                              │   ├─ Auth / RBAC / Audit   │
│  • Tailwind design sys  │   ◀── SDP/ICE signaling ──   │   ├─ Appointments          │
│  • next-intl (en/bn)    │                              │   ├─ EMR (encrypted)       │
└──────────┬─────────────┘                              │   ├─ Prescriptions → PDF   │
           │  direct P2P media (WebRTC)                  │   └─ Notifications         │
           ▼                                             │  Background worker         │
      ┌──────────┐                                       │   reminders + email outbox │
      │  Peer     │                                      └────────────┬──────────────┘
      │  browser  │                                                   │
      └──────────┘                                            ┌───────▼────────┐
                                                              │  PostgreSQL 15  │
                                                              └────────────────┘
```

### Tech stack

| Layer       | Technology |
|-------------|-----------|
| Frontend    | Next.js 14 (App Router), React 18, TypeScript, Tailwind CSS, Radix UI, TanStack Query, Zustand, next-intl |
| Backend     | Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic |
| Database    | PostgreSQL 15 |
| Realtime    | WebRTC (browser) + FastAPI WebSocket signaling |
| Security    | AES-256-GCM, bcrypt, JWT, RBAC, audit logging, HSTS/TLS |
| PDF / Email | fpdf2, SMTP delivery via a DB-backed retry outbox, APScheduler |
| Hosting     | Vercel (frontend) · Render (API + worker + PostgreSQL) |

## Repository layout

```
care-connect/
├── backend/        FastAPI app, services, models, Alembic migrations, worker, tests
│   ├── app/        api · core · models · services · worker
│   └── tests/      property-based + integration tests
├── frontend/       Next.js app
│   └── src/        app (routes) · components · lib · hooks · i18n
├── render.yaml     Render blueprint (API + worker + PostgreSQL)
└── README.md
```

## Getting started

### Prerequisites
- Node.js 20+ and npm
- Python 3.12 (3.10+ works for local dev)
- PostgreSQL 15

### Backend
```bash
cd backend
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt -r requirements-dev.txt
# Configure environment (see backend/.env.example):
#   DATABASE_URL, EMR_ENCRYPTION_KEY, JWT_SECRET, CORS_ALLOW_ORIGINS, SMTP_*
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
# Set NEXT_PUBLIC_API_BASE_URL (see frontend/.env.example)
npm run dev          # http://localhost:3000
```

## Testing

```bash
# Backend (a local PostgreSQL enables the property-based suite)
cd backend
set TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/careconnect_test
pytest                              # fast profile
set HYPOTHESIS_PROFILE=ci&& pytest  # thorough (500 examples per property)

# Frontend
cd frontend
npm test
```

## Deployment

### Backend & database — Render
1. Create a Render Blueprint from `render.yaml`.
2. Provide the secret environment variables: `EMR_ENCRYPTION_KEY` (a 32-byte key,
   identical on the web service and the worker), `CORS_ALLOW_ORIGINS` (your
   Vercel domain), and the `SMTP_*` / `TURN_*` values.
3. Migrations run automatically (`alembic upgrade head`) before each release.

### Frontend — Vercel
1. Import the repository with the project root set to `frontend/`.
2. Set `NEXT_PUBLIC_API_BASE_URL` to the Render API URL.
3. Vercel builds and deploys automatically on every push to `main`.

## Security

- Sensitive patient fields are encrypted at rest with AES-256-GCM; keys are
  sourced only from `EMR_ENCRYPTION_KEY` and never stored alongside the data.
- All client–server traffic is HTTPS/WSS with HSTS enforced.
- Access to patient data is role-scoped and recorded in an audit log.
- All secrets are read from environment variables; none are committed.

## License

Released under the MIT License. See [`LICENSE`](LICENSE).
