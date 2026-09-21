#!/usr/bin/env python3
"""api_server.py — Gladewood Commons operations backend.

Runs on port 8000 locally, or on the port Render provides via $PORT.
Uses Postgres (Supabase) via DATABASE_URL for durable, cross-device storage.
"""
import os
from contextlib import asynccontextmanager

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set — configure the Supabase Postgres connection string.")

db = psycopg2.connect(DATABASE_URL)
db.autocommit = True


def cursor():
    return db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


with cursor() as cur:
    cur.execute("""
    CREATE TABLE IF NOT EXISTS properties (
        id SERIAL PRIMARY KEY,
        address TEXT NOT NULL DEFAULT '',
        area TEXT NOT NULL DEFAULT '',
        beds TEXT NOT NULL DEFAULT '',
        baths TEXT NOT NULL DEFAULT '',
        zoning_fit TEXT NOT NULL DEFAULT '',
        rent TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'Not sourced yet',
        next_action TEXT NOT NULL DEFAULT '',
        updated_at TIMESTAMPTZ DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS prospects (
        id SERIAL PRIMARY KEY,
        initials TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT '',
        room_type TEXT NOT NULL DEFAULT '',
        income_verified TEXT NOT NULL DEFAULT 'Not verified',
        deposit TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'Inquiry',
        notes TEXT NOT NULL DEFAULT '',
        updated_at TIMESTAMPTZ DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS residents (
        id SERIAL PRIMARY KEY,
        initials TEXT NOT NULL DEFAULT '',
        room TEXT NOT NULL DEFAULT '',
        lease_start TEXT NOT NULL DEFAULT '',
        rent_status TEXT NOT NULL DEFAULT '',
        house_rules TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        updated_at TIMESTAMPTZ DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS conflict_log (
        id SERIAL PRIMARY KEY,
        entry_date TEXT NOT NULL DEFAULT '',
        house TEXT NOT NULL DEFAULT '',
        category TEXT NOT NULL DEFAULT '',
        safety_flag TEXT NOT NULL DEFAULT 'None',
        status TEXT NOT NULL DEFAULT '',
        resolution TEXT NOT NULL DEFAULT '',
        updated_at TIMESTAMPTZ DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS financials (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL DEFAULT ''
    );
    """)

FINANCIAL_KEYS = [
    "lease_rent", "utilities", "internet", "cleaning", "insurance", "furnishing",
    "private_room_rate", "shared_room_rate", "net_profit_target", "breakeven_occupancy",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    db.close()


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------- Pydantic models ----------

class Property(BaseModel):
    address: str = ""
    area: str = ""
    beds: str = ""
    baths: str = ""
    zoning_fit: str = ""
    rent: str = ""
    status: str = "Not sourced yet"
    next_action: str = ""


class Prospect(BaseModel):
    initials: str = ""
    source: str = ""
    room_type: str = ""
    income_verified: str = "Not verified"
    deposit: str = ""
    status: str = "Inquiry"
    notes: str = ""


class Resident(BaseModel):
    initials: str = ""
    room: str = ""
    lease_start: str = ""
    rent_status: str = ""
    house_rules: str = ""
    notes: str = ""


class ConflictEntry(BaseModel):
    entry_date: str = ""
    house: str = ""
    category: str = ""
    safety_flag: str = "None"
    status: str = ""
    resolution: str = ""


class FinancialsUpdate(BaseModel):
    values: dict[str, str]


# ---------- Generic CRUD helper ----------

def make_crud(table: str, columns: list[str]):
    def list_rows():
        with cursor() as cur:
            cur.execute(f"SELECT * FROM {table} ORDER BY id")
            return [dict(r) for r in cur.fetchall()]

    def create_row(item):
        data = item.dict()
        cols = ", ".join(columns)
        placeholders = ", ".join("%s" for _ in columns)
        with cursor() as cur:
            cur.execute(
                f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) RETURNING *",
                [data[c] for c in columns],
            )
            return dict(cur.fetchone())

    def update_row(row_id: int, item):
        data = item.dict()
        with cursor() as cur:
            cur.execute(f"SELECT id FROM {table} WHERE id = %s", [row_id])
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Not found")
            set_clause = ", ".join(f"{c} = %s" for c in columns)
            cur.execute(
                f"UPDATE {table} SET {set_clause}, updated_at = now() WHERE id = %s RETURNING *",
                [data[c] for c in columns] + [row_id],
            )
            return dict(cur.fetchone())

    def delete_row(row_id: int):
        with cursor() as cur:
            cur.execute(f"DELETE FROM {table} WHERE id = %s", [row_id])
        return {"deleted": row_id}

    return list_rows, create_row, update_row, delete_row


property_cols = ["address", "area", "beds", "baths", "zoning_fit", "rent", "status", "next_action"]
prospect_cols = ["initials", "source", "room_type", "income_verified", "deposit", "status", "notes"]
resident_cols = ["initials", "room", "lease_start", "rent_status", "house_rules", "notes"]
conflict_cols = ["entry_date", "house", "category", "safety_flag", "status", "resolution"]

props_list, props_create, props_update, props_delete = make_crud("properties", property_cols)
prosp_list, prosp_create, prosp_update, prosp_delete = make_crud("prospects", prospect_cols)
resid_list, resid_create, resid_update, resid_delete = make_crud("residents", resident_cols)
conf_list, conf_create, conf_update, conf_delete = make_crud("conflict_log", conflict_cols)


# ---------- Properties ----------

@app.get("/api/properties")
def get_properties():
    return props_list()

@app.post("/api/properties", status_code=201)
def post_property(item: Property):
    return props_create(item)

@app.put("/api/properties/{row_id}")
def put_property(row_id: int, item: Property):
    return props_update(row_id, item)

@app.delete("/api/properties/{row_id}")
def delete_property(row_id: int):
    return props_delete(row_id)


# ---------- Prospects ----------

@app.get("/api/prospects")
def get_prospects():
    return prosp_list()

@app.post("/api/prospects", status_code=201)
def post_prospect(item: Prospect):
    return prosp_create(item)

@app.put("/api/prospects/{row_id}")
def put_prospect(row_id: int, item: Prospect):
    return prosp_update(row_id, item)

@app.delete("/api/prospects/{row_id}")
def delete_prospect(row_id: int):
    return prosp_delete(row_id)


# ---------- Residents ----------

@app.get("/api/residents")
def get_residents():
    return resid_list()

@app.post("/api/residents", status_code=201)
def post_resident(item: Resident):
    return resid_create(item)

@app.put("/api/residents/{row_id}")
def put_resident(row_id: int, item: Resident):
    return resid_update(row_id, item)

@app.delete("/api/residents/{row_id}")
def delete_resident(row_id: int):
    return resid_delete(row_id)


# ---------- Conflict log ----------

@app.get("/api/conflict-log")
def get_conflict_log():
    return conf_list()

@app.post("/api/conflict-log", status_code=201)
def post_conflict(item: ConflictEntry):
    return conf_create(item)

@app.put("/api/conflict-log/{row_id}")
def put_conflict(row_id: int, item: ConflictEntry):
    return conf_update(row_id, item)

@app.delete("/api/conflict-log/{row_id}")
def delete_conflict(row_id: int):
    return conf_delete(row_id)


# ---------- Financials (key/value singleton table) ----------

@app.get("/api/financials")
def get_financials():
    with cursor() as cur:
        cur.execute("SELECT key, value FROM financials")
        rows = cur.fetchall()
    result = {k: "" for k in FINANCIAL_KEYS}
    for r in rows:
        result[r["key"]] = r["value"]
    return result

@app.put("/api/financials")
def put_financials(payload: FinancialsUpdate):
    with cursor() as cur:
        for k, v in payload.values.items():
            if k not in FINANCIAL_KEYS:
                continue
            cur.execute(
                "INSERT INTO financials (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                [k, v],
            )
    return get_financials()


# ---------- Demand KPIs (derived from prospects) ----------

@app.get("/api/demand-summary")
def demand_summary():
    rows = prosp_list()
    raw = len(rows)
    screened = sum(1 for r in rows if r["status"] in ("Screened", "Income-verified", "Deposit received", "Confirmed"))
    verified = sum(1 for r in rows if r["income_verified"] == "Verified")
    deposited = sum(1 for r in rows if r["status"] in ("Deposit received", "Confirmed"))
    return {
        "raw_inquiries": raw,
        "screened_verified": verified,
        "holding_deposit": deposited,
        "target": 6,
    }


@app.get("/api/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
