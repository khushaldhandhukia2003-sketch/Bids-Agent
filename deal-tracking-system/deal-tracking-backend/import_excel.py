import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from dotenv import load_dotenv
import os

load_dotenv()

DB_USER     = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_HOST     = os.getenv('DB_HOST')
DB_PORT     = os.getenv('DB_PORT')
DB_NAME     = os.getenv('DB_NAME')

EXCEL_FILE  = 'RFQ & Bids Tracking Report.xlsx'
SHEET_NAME  = 'BIDS format'

print("Reading Excel file...")
df = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_NAME, header=9)

df.columns = [str(c).strip() for c in df.columns]
print("Columns found:", list(df.columns))

df = df.dropna(subset=['Enquiry Ref. No.'])
df = df.reset_index(drop=True)
print(f"Total data rows: {len(df)}")

connection_url = URL.create(
    drivername="postgresql+psycopg2",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=DB_PORT,
    database=DB_NAME
)

engine = create_engine(connection_url)

with engine.connect() as conn:

    for i, row in df.iterrows():
        try:

            rfq_no = str(row.get('Enquiry Ref. No.', '')).strip()
            title  = str(row.get('Package Description', '')).strip()
            status = 'Open'

            # -----------------------------
            # FIX 1: Proper date handling
            # -----------------------------
            closing = row.get('Closing Date', None)

            if pd.isna(closing):
                closing = None
            else:
                closing = pd.to_datetime(
                    closing,
                    dayfirst=True,
                    errors='coerce'
                )

                if pd.isna(closing):
                    closing = None
                else:
                    closing = closing.date()

            # -----------------------------
            # Insert RFQ
            # -----------------------------
            existing = conn.execute(
                text("SELECT id FROM rfqs WHERE rfq_number = :rfq_number"),
                {"rfq_number": rfq_no}
            ).fetchone()

            if existing:
                rfq_id = existing[0]
                print(f"Row {i+1}: RFQ '{rfq_no}' already exists.")
            else:
                result = conn.execute(
                    text("""
                        INSERT INTO rfqs 
                        (rfq_number, content, submission_deadline, status)
                        VALUES (:rfq_number, :content, :deadline, :status)
                        RETURNING id
                    """),
                    {
                        "rfq_number": rfq_no,
                        "content": title,
                        "deadline": closing,
                        "status": status
                    }
                )
                rfq_id = result.fetchone()[0]
                print(f"Row {i+1}: RFQ inserted → id={rfq_id}")

            # -----------------------------
            # Insert Item
            # -----------------------------
            item_result = conn.execute(
                text("""
                    INSERT INTO rfq_items 
                    (rfq_id, item_name, description)
                    VALUES (:rfq_id, :item_name, :description)
                    RETURNING id
                """),
                {
                    "rfq_id": rfq_id,
                    "item_name": title if title else "N/A",
                    "description": str(row.get('Client', '')).strip()
                }
            )
            item_id = item_result.fetchone()[0]

            # -----------------------------
            # Vendor Quote Columns
            # -----------------------------
            quote_columns = {
                'Vendor A': row.get('Quotation  Value', None),
                'Vendor B': row.get('Unnamed: 14', None),
                'Vendor C': row.get('Unnamed: 15', None),
                'Vendor D': row.get('Unnamed: 16', None),
            }

            for vendor_name, quote_val in quote_columns.items():

                if pd.isna(quote_val) or quote_val in ['', None]:
                    continue

                try:
                    quote_amount = float(str(quote_val).replace(',', '').strip())
                except:
                    continue

                # Check vendor
                vendor_row = conn.execute(
                    text("SELECT id FROM vendors WHERE vendor_name = :name"),
                    {"name": vendor_name}
                ).fetchone()

                if vendor_row:
                    vendor_id = vendor_row[0]
                else:
                    v_result = conn.execute(
                        text("""
                            INSERT INTO vendors (vendor_name)
                            VALUES (:name)
                            RETURNING id
                        """),
                        {"name": vendor_name}
                    )
                    vendor_id = v_result.fetchone()[0]

                # Insert quote
                conn.execute(
                    text("""
                        INSERT INTO rfq_vendor_quotes
                        (rfq_id, rfq_item_id, vendor_id, quote_amount_aed)
                        VALUES
                        (:rfq_id, :rfq_item_id, :vendor_id, :amount)
                        ON CONFLICT (rfq_item_id, vendor_id) DO NOTHING
                    """),
                    {
                        "rfq_id": rfq_id,
                        "rfq_item_id": item_id,
                        "vendor_id": vendor_id,
                        "amount": quote_amount
                    }
                )

            conn.commit()

        except Exception as e:
            print(f"❌ Error on row {i+1} ({rfq_no}): {e}")
            conn.rollback()

print("\n✅ ALL DONE! Data imported successfully.")