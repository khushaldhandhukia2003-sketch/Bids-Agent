import psycopg2
from dotenv import load_dotenv
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv(override=True)

# ── Deal Tracking DB (Neon) ───────────────────────────────────
DB_HOST            = os.getenv("DB_HOST")
DB_PORT            = os.getenv("DB_PORT", "5432")
DB_NAME            = os.getenv("DB_NAME")
DB_USER            = os.getenv("DB_USER")
DB_PASSWORD        = os.getenv("DB_PASSWORD")
DB_SSLMODE         = os.getenv("DB_SSLMODE", "require")
DB_CONNECT_TIMEOUT = os.getenv("DB_CONNECT_TIMEOUT", "5")

DATABASE_URL = (
    f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    f"?sslmode={DB_SSLMODE}&connect_timeout={DB_CONNECT_TIMEOUT}"
)

# ── SQLAlchemy setup with pool limits ────────────────────────
engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=300,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base         = declarative_base()

# ── psycopg2 — raw connection ─────────────────────────────────
def get_connection():
    try:
        return psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            sslmode=DB_SSLMODE,
            connect_timeout=int(DB_CONNECT_TIMEOUT),
        )
    except Exception as e:
        print("Database connection failed:", e)
        raise

def release_connection(conn):
    try:
        conn.close()
    except Exception:
        pass

# ── psycopg2 — FastAPI dependency (deal tracking) ────────────
def get_db():
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        sslmode=DB_SSLMODE,
        connect_timeout=int(DB_CONNECT_TIMEOUT),
    )
    try:
        yield conn
    finally:
        conn.close()

# ── SQLAlchemy — FastAPI dependency ──────────────────────────
def get_db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ── Suppliers + Inquiry History DB (falls back to the main DB config) ─────────
SUPPLIERS_DB_HOST     = os.getenv("SUPPLIERS_DB_HOST", DB_HOST)
SUPPLIERS_DB_PORT     = os.getenv("SUPPLIERS_DB_PORT", DB_PORT)
SUPPLIERS_DB_NAME     = os.getenv("SUPPLIERS_DB_NAME", DB_NAME)
SUPPLIERS_DB_USER     = os.getenv("SUPPLIERS_DB_USER", DB_USER)
SUPPLIERS_DB_PASSWORD = os.getenv("SUPPLIERS_DB_PASSWORD", DB_PASSWORD)
SUPPLIERS_DB_SSLMODE  = os.getenv("SUPPLIERS_DB_SSLMODE", DB_SSLMODE)

def get_suppliers_db():
    """psycopg2 connection to the shared database.
    Used by supplier search, vendor discovery, and inquiry history."""
    conn = psycopg2.connect(
        host=SUPPLIERS_DB_HOST,
        port=SUPPLIERS_DB_PORT,
        database=SUPPLIERS_DB_NAME,
        user=SUPPLIERS_DB_USER,
        password=SUPPLIERS_DB_PASSWORD,
        sslmode=SUPPLIERS_DB_SSLMODE,
        connect_timeout=int(DB_CONNECT_TIMEOUT),
    )
    try:
        yield conn
    finally:
        conn.close()

# ── Quick connection test ─────────────────────────────────────
if __name__ == "__main__":
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✅ Deal Tracking DB connected!")
        print(f"   Host: {DB_HOST} | DB: {DB_NAME}")
    except Exception as e:
        print("❌ Deal Tracking DB failed:", e)

    try:
        conn = psycopg2.connect(
            host=SUPPLIERS_DB_HOST, port=SUPPLIERS_DB_PORT,
            database=SUPPLIERS_DB_NAME, user=SUPPLIERS_DB_USER,
            password=SUPPLIERS_DB_PASSWORD, sslmode=SUPPLIERS_DB_SSLMODE,
            connect_timeout=3
        )
        conn.close()
        print("✅ Suppliers DB connected!")
        print(f"   Host: {SUPPLIERS_DB_HOST} | DB: {SUPPLIERS_DB_NAME}")
    except Exception as e:
        print("❌ Suppliers DB failed:", e)