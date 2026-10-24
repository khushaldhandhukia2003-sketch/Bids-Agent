import os
import logging

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import psycopg2
from routes.auth            import router as auth_router
from routes.rfqs            import router as rfqs_router
from routes.vendor_search   import router as vendor_search_router
from routes.supplier_search import router as supplier_search_router
from routes.vendor_discovery import router as vendor_discovery_router
from routes.document_parse  import router as document_parse_router
from routes.chat            import router as chat_router
from routes.ai_proxy        import router as ai_proxy_router
from routes.multi_item_inquiry import router as multi_item_inquiry_router
from routes.vendor_management import router as vendor_management_router
from routes.rfq_import      import router as rfq_import_router
from routes.history         import router as history_router
from routes.bids            import router as bids_router
from routes.zoho_sync       import router as zoho_router
from routes.users           import router as users_router

load_dotenv(override=True)

# Suppress noisy discovery-progress poll requests from uvicorn access log
class _SuppressProgressPoll(logging.Filter):
    def filter(self, record):
        return "discovery-progress" not in (record.getMessage())

logging.getLogger("uvicorn.access").addFilter(_SuppressProgressPoll())

# ── Division seeding ──────────────────────────────────────────
DIVISIONS = [
    ("ISD-EPC",            "ISD"),
    ("RENTAL",             "RNT"),
    ("C&J",                "C&J"),
    ("PRO",                "PRO"),
    ("AUTO",               "AUTO"),
    ("CPD",                "CPD"),
    ("BB EXPORT",          "EXP"),
    ("PETROGULF",          "PGF"),
    ("MRO",                "MRO"),
    ("TPE",                "TPE"),
    ("O&G EPC",            "OGE"),
]

def seed_divisions():
    """Upsert canonical divisions on every startup so the DB always matches."""
    from database import get_connection
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS divisions (
                id   SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                code TEXT NOT NULL
            )
        """)
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_indexes
                    WHERE schemaname = 'public' AND indexname = 'divisions_name_key'
                ) THEN
                    CREATE UNIQUE INDEX divisions_name_key ON divisions (name);
                END IF;
            END $$;
        """)
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'divisions_code_key'
                ) THEN
                    ALTER TABLE divisions ADD CONSTRAINT divisions_code_key UNIQUE (code);
                END IF;
            END $$;
        """)
        for name, code in DIVISIONS:
            cur.execute("""
                INSERT INTO divisions (name, code) VALUES (%s, %s)
                ON CONFLICT (name) DO UPDATE SET code = EXCLUDED.code
            """, (name, code))

        # --- Remove stale divisions and fix user assignments ---
        canonical_names = [name for name, _ in DIVISIONS]
        ph = ",".join(["%s"] * len(canonical_names))

        # Get IDs of divisions that are NOT canonical (to clean up user assignments)
        cur.execute(
            f"SELECT id FROM divisions WHERE name NOT IN ({ph})",
            canonical_names,
        )
        stale_ids = [r[0] for r in cur.fetchall()]

        if stale_ids:
            stale_ph = ",".join(["%s"] * len(stale_ids))
            # Remove user_divisions rows pointing to stale divisions
            cur.execute(
                f"DELETE FROM user_divisions WHERE division_id IN ({stale_ph})",
                stale_ids,
            )
            # Now safe to delete stale divisions
            cur.execute(
                f"DELETE FROM divisions WHERE id IN ({stale_ph})",
                stale_ids,
            )
            print(f"🧹 Removed {len(stale_ids)} stale division(s)")

        # Fetch the final canonical division IDs
        cur.execute(f"SELECT id FROM divisions WHERE name IN ({ph})", canonical_names)
        canonical_ids = [r[0] for r in cur.fetchall()]

        # Re-assign GM and Manager users to ALL canonical divisions
        # (ensures they see the right list after a division rename/cleanup)
        cur.execute("SELECT id FROM users WHERE role IN ('gm', 'manager')")
        gm_manager_ids = [r[0] for r in cur.fetchall()]

        for uid in gm_manager_ids:
            for did in canonical_ids:
                cur.execute("""
                    INSERT INTO user_divisions (user_id, division_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                """, (uid, did))

        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ Divisions seeded ({len(DIVISIONS)} rows), users re-synced")
    except Exception as e:
        print(f"⚠️  Division seed failed: {e}")

seed_divisions()

def migrate_vendors_master():
    """Add division_id, client columns and (normalized_name, country) unique index."""
    from database import get_connection
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            ALTER TABLE vendors_master
                ADD COLUMN IF NOT EXISTS division_id INTEGER REFERENCES divisions(id) ON DELETE SET NULL,
                ADD COLUMN IF NOT EXISTS client      TEXT;
        """)
        # Allow same company in multiple countries — unique per (name, country)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS vendors_master_name_country_key
            ON vendors_master (normalized_name, LOWER(COALESCE(country, '')));
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"⚠️  vendors_master migration failed: {e}")

migrate_vendors_master()

def migrate_discovered_vendors_dedup():
    """Fix de-duplication key: (vendor_name, search_id) → (vendor_name, inquiry_id).
    Old key allowed the same vendor to accumulate across re-runs of the same RFQ.
    New key ensures one canonical row per vendor per inquiry."""
    from database import get_connection
    try:
        conn = get_connection()
        cur = conn.cursor()
        # Drop old unique constraint on (vendor_name, search_id) if it exists
        # Query pg_indexes to find the real index name, then drop it
        cur.execute("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'discovered_vendors'
              AND indexdef ILIKE '%vendor_name%search_id%'
        """)
        old_indexes = [r[0] for r in cur.fetchall()]
        for idx_name in old_indexes:
            cur.execute(f"DROP INDEX IF EXISTS {idx_name}")
            print(f"  dropped old index: {idx_name}")
        conn.commit()
        # Create correct unique index on (vendor_name, inquiry_id)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS discovered_vendors_vendor_inquiry_key
            ON discovered_vendors (vendor_name, inquiry_id);
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ discovered_vendors dedup key migrated to (vendor_name, inquiry_id)")
    except Exception as e:
        print(f"⚠️  discovered_vendors dedup migration failed: {e}")

migrate_discovered_vendors_dedup()

def migrate_preferred_vendors():
    """Add is_preferred, preferred_divisions, preferred_categories to vendors_master."""
    from database import get_connection
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            ALTER TABLE vendors_master
                ADD COLUMN IF NOT EXISTS is_preferred         BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS preferred_divisions  TEXT,
                ADD COLUMN IF NOT EXISTS preferred_categories TEXT,
                ADD COLUMN IF NOT EXISTS preferred_marked_by  TEXT,
                ADD COLUMN IF NOT EXISTS preferred_marked_at  TIMESTAMPTZ;
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS vendors_master_preferred_idx
            ON vendors_master (is_preferred) WHERE is_preferred = TRUE;
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ preferred vendor columns migrated")
    except Exception as e:
        print(f"⚠️  preferred vendor migration failed: {e}")

migrate_preferred_vendors()

def migrate_inquiry_line_items():
    """Add specs and category columns to inquiry_line_items if missing."""
    from database import get_connection
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            ALTER TABLE inquiry_line_items
                ADD COLUMN IF NOT EXISTS specs    TEXT,
                ADD COLUMN IF NOT EXISTS category TEXT;
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ inquiry_line_items migration done")
    except Exception as e:
        print(f"⚠️  inquiry_line_items migration failed: {e}")

migrate_inquiry_line_items()

def create_vendor_import_log():
    """Create vendor_import_log table if it doesn't exist."""
    from database import get_connection
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vendor_import_log (
                id          SERIAL PRIMARY KEY,
                filename    TEXT NOT NULL,
                saved       INTEGER DEFAULT 0,
                updated     INTEGER DEFAULT 0,
                skipped     INTEGER DEFAULT 0,
                total_rows  INTEGER DEFAULT 0,
                imported_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"⚠️  vendor_import_log create failed: {e}")

create_vendor_import_log()

def create_activity_log():
    from database import get_connection
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id         SERIAL PRIMARY KEY,
                event_type TEXT NOT NULL,
                title      TEXT NOT NULL,
                detail     TEXT DEFAULT '',
                meta       JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"⚠️  activity_log create failed: {e}")

create_activity_log()

def migrate_vendor_import_log_id():
    """Add import_log_id to vendors_master so we can cascade-delete by import batch."""
    from database import get_connection
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            ALTER TABLE vendors_master
            ADD COLUMN IF NOT EXISTS import_log_id INTEGER
            REFERENCES vendor_import_log(id) ON DELETE SET NULL
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ import_log_id column migration done")
    except Exception as e:
        print(f"⚠️  import_log_id migration failed: {e}")

migrate_vendor_import_log_id()

def create_discovery_blacklist():
    from database import get_connection
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS discovery_blacklist (
                id           SERIAL PRIMARY KEY,
                company_name TEXT NOT NULL UNIQUE,
                reason       TEXT DEFAULT '',
                created_at   TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"⚠️  discovery_blacklist create failed: {e}")

create_discovery_blacklist()

def create_pipeline_decisions():
    """Create pipeline_decisions table for self-learning foundation (Phase 5B)."""
    from database import get_connection
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_decisions (
                id               SERIAL PRIMARY KEY,
                inquiry_id       TEXT NOT NULL,
                search_id        TEXT,
                item_description TEXT,
                vendor_name      TEXT NOT NULL,
                vendor_source    TEXT,          -- 'database', 'ai_discovered', 'legacy'
                channel_used     TEXT,          -- sourcing channel code e.g. 'LAD', 'OEM'
                semantic_score   NUMERIC(4,3),  -- relevance score from Claude/GPT (0.0-1.0)
                confidence_score NUMERIC(4,2),
                was_selected     BOOLEAN DEFAULT FALSE,  -- did user include in final RFQ?
                outcome          TEXT,          -- 'won', 'lost', 'no_response', NULL=pending
                outcome_date     TIMESTAMPTZ,
                decided_at       TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS pipeline_decisions_inquiry_idx
            ON pipeline_decisions (inquiry_id);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS pipeline_decisions_vendor_idx
            ON pipeline_decisions (vendor_name);
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ pipeline_decisions table created")
    except Exception as e:
        print(f"⚠️  pipeline_decisions create failed: {e}")

create_pipeline_decisions()

def migrate_suppliers_extended_fields():
    """Add UAE-sourcing columns to the suppliers table."""
    from database import get_connection
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute("""
            ALTER TABLE suppliers
                ADD COLUMN IF NOT EXISTS city                    TEXT,
                ADD COLUMN IF NOT EXISTS phone                   TEXT,
                ADD COLUMN IF NOT EXISTS website                 TEXT,
                ADD COLUMN IF NOT EXISTS priority_rank           INTEGER,
                ADD COLUMN IF NOT EXISTS rfq_response_probability TEXT,
                ADD COLUMN IF NOT EXISTS quotation_speed         TEXT,
                ADD COLUMN IF NOT EXISTS authorization_type      TEXT;
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ suppliers extended fields migrated")
    except Exception as e:
        print(f"⚠️  suppliers migration failed: {e}")

migrate_suppliers_extended_fields()

def migrate_columns_to_text():
    """Widen all VARCHAR columns that can receive long values to TEXT."""
    from database import get_connection
    migrations = {
        "inquiry_history": ("part_number", "description", "specs", "quantity", "delivery", "customer", "team", "channel_codes"),
        "inquiry_master":       ("inquiry_id", "client", "delivery", "notes", "team"),
        "inquiry_line_items":   ("inquiry_id", "line_ref", "description", "quantity", "unit", "category", "channel_codes"),
        "inquiry_search_log":   ("search_id", "inquiry_id", "team", "engineer", "items_searched", "search_mode", "channels_used"),
        "discovered_vendors":   ("vendor_name", "country", "city", "email", "phone", "website", "brands", "description", "sourcing_rationale", "source", "search_id", "inquiry_id"),
        "vendors":         ("email", "phone", "address", "website", "name"),
        "vendors_master":  ("email", "phone", "address", "website", "name", "contact_person"),
    }
    try:
        conn = get_connection()
        cur = conn.cursor()
        for table, cols in migrations.items():
            for col in cols:
                try:
                    cur.execute(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE TEXT")
                    conn.commit()
                    print(f"  ✅ {table}.{col} → TEXT")
                except Exception:
                    conn.rollback()  # column already TEXT or doesn't exist — skip
        cur.close()
        conn.close()
        print("✅ migrate_columns_to_text done")
    except Exception as e:
        print(f"⚠️  Column migration failed: {e}")

migrate_columns_to_text()

def migrate_inquiry_draft_flag():
    """Add is_draft column so unsaved (in-progress) inquiries are hidden from the RFQ list."""
    from database import get_connection
    try:
        conn = get_connection()
        cur  = conn.cursor()
        # DEFAULT FALSE so the column type is set correctly
        cur.execute("ALTER TABLE inquiry_master ADD COLUMN IF NOT EXISTS is_draft BOOLEAN DEFAULT FALSE")
        # Mark ALL existing rows as saved (is_draft=FALSE) — they were created before this feature
        cur.execute("UPDATE inquiry_master SET is_draft = FALSE")
        conn.commit()
        cur.close()
        conn.close()
        print("✅ migrate_inquiry_draft_flag done")
    except Exception as e:
        print(f"⚠️  migrate_inquiry_draft_flag failed: {e}")

migrate_inquiry_draft_flag()

def create_bids_tracking():
    """
    Create bids_tracking table and add outcome columns to inquiry_master.
    Status lifecycle: bid_sent → quoted → won | lost | no_response
    """
    from database import get_connection
    try:
        conn = get_connection()
        cur = conn.cursor()

        # Main bids tracking table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bids_tracking (
                id                  SERIAL PRIMARY KEY,
                inquiry_id          TEXT REFERENCES inquiry_master(inquiry_id) ON DELETE SET NULL,
                division_id         INTEGER REFERENCES divisions(id) ON DELETE SET NULL,
                client              TEXT,
                salesperson_name    TEXT,
                bid_ref             TEXT,
                status              TEXT NOT NULL DEFAULT 'bid_sent'
                                    CHECK (status IN ('bid_sent','quoted','won','lost','no_response')),
                quotation_value     NUMERIC(15,2),
                quotation_currency  TEXT DEFAULT 'AED',
                order_value         NUMERIC(15,2),
                lost_reason         TEXT,
                competitor_name     TEXT,
                notes               TEXT,
                zoho_deal_id        TEXT,
                bid_sent_date       DATE,
                quoted_date         DATE,
                outcome_date        DATE,
                created_at          TIMESTAMPTZ DEFAULT NOW(),
                updated_at          TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Indexes
        cur.execute("CREATE INDEX IF NOT EXISTS bids_tracking_inquiry_idx ON bids_tracking (inquiry_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS bids_tracking_status_idx  ON bids_tracking (status)")
        cur.execute("CREATE INDEX IF NOT EXISTS bids_tracking_division_idx ON bids_tracking (division_id)")

        # Add outcome columns to inquiry_master for quick access
        cur.execute("""
            ALTER TABLE inquiry_master
                ADD COLUMN IF NOT EXISTS bid_status      TEXT DEFAULT 'bid_sent',
                ADD COLUMN IF NOT EXISTS outcome_date    DATE,
                ADD COLUMN IF NOT EXISTS order_value     NUMERIC(15,2),
                ADD COLUMN IF NOT EXISTS zoho_deal_id    TEXT;
        """)

        conn.commit()
        cur.close()
        conn.close()
        print("✅ bids_tracking table and outcome columns created")
    except Exception as e:
        print(f"⚠️  bids_tracking migration failed: {e}")

create_bids_tracking()

default_origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "https://gentle-flower-039b7890f.7.azurestaticapps.net",
]
raw_origins = os.getenv("ALLOWED_ORIGINS", "")
configured_origins = [
    origin.strip()
    for origin in raw_origins.split(",")
    if origin.strip()
]
ALLOWED_ORIGINS = list(dict.fromkeys(default_origins + configured_origins))

app = FastAPI(title="Bhatia Brothers FZE — Procurement API")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import logging
    logging.error(f"Global exception caught: {exc}", exc_info=True)
    
    # Manually add CORS headers to ensure the browser doesn't block the error response
    origin = request.headers.get("origin", "*")
    headers = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "*",
        "Access-Control-Allow-Headers": "*",
    }
    return JSONResponse(
        status_code=500,
        content={"success": False, "detail": "Internal Server Error", "error": str(exc)},
        headers=headers
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_BODY_BYTES = 25 * 1024 * 1024  # 25 MB

@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BODY_BYTES:
        return JSONResponse(status_code=413, content={"detail": "Request body too large. Max 25MB."})
    return await call_next(request)

@app.exception_handler(psycopg2.DatabaseError)
async def db_exception_handler(request: Request, exc: psycopg2.DatabaseError):
    response = JSONResponse(
        status_code=503,
        content={"detail": "Database unavailable. Please try again later."},
    )
    response.headers["Access-Control-Allow-Origin"] = "http://localhost:3000"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

app.include_router(auth_router,            prefix="/api")
app.include_router(rfqs_router,            prefix="/api")
app.include_router(vendor_search_router,   prefix="/api")
app.include_router(supplier_search_router, prefix="/api")
app.include_router(vendor_discovery_router,prefix="/api")
app.include_router(document_parse_router,  prefix="/api")
app.include_router(chat_router,            prefix="/api")
app.include_router(ai_proxy_router,        prefix="/api")
app.include_router(multi_item_inquiry_router, prefix="/api")
app.include_router(vendor_management_router, prefix="/api")
app.include_router(rfq_import_router,      prefix="/api")
app.include_router(history_router,         prefix="/api")
app.include_router(bids_router,            prefix="/api")
app.include_router(zoho_router,            prefix="/api")
app.include_router(users_router,           prefix="/api")
@app.get("/")
def root():
    return {"message": "Bhatia Brothers FZE — Procurement API Running"}  # Trigger reload