# Gladewood Commons Operations API

FastAPI backend for the Gladewood Commons operations dashboard
(Property/landlord pipeline, Demand validation, Financial model, Resident operations).

Requires a `DATABASE_URL` environment variable pointing to a Postgres
database (Supabase). Runs on the port provided via `$PORT` (Render sets this).
