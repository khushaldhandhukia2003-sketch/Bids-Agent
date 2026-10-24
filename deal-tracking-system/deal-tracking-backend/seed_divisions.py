"""
Seed random RFQ data for empty divisions: C&J, TPE, BB EXPORT, PETROGULF, ISD-EPC, GD
Run from deal-tracking-backend folder: python seed_divisions.py
"""
import sys, os, random
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(override=True)
from database import get_connection

CLIENTS = [
    "ADNOC GAS", "ADNOC L&S", "DEWA", "TAQA", "ENEC", "Emirates Steel",
    "GASCO", "DUBAL", "Mubadala", "ADCO", "Dolphin Energy", "EGA",
    "Dubai Petroleum", "Sharjah Electricity", "RAK Gas",
]

TEAMS = {
    "C&J":       "C&J",
    "TPE":       "TPE",
    "BB EXPORT": "EXP",
    "PETROGULF": "PGF",
    "ISD-EPC":   "ISD",
    "GD":        "GD",
}

PRODUCTS_BY_DIV = {
    "C&J": [
        ("Crane wire rope 6x36 IWRC 32mm", "CRANE", "12 coils", "Dubai"),
        ("Chain block 5T lever hoist", "RIGGING", "20 nos", "Abu Dhabi"),
        ("Manila rope 24mm 3-strand 220m", "ROPES", "10 coils", "Jebel Ali"),
        ("Polyester sling 5T x 3m", "LIFTING", "50 nos", "UAE"),
        ("Shackle bow type 8.5T galvanised", "RIGGING", "100 nos", "Sharjah"),
        ("Steel wire rope 8mm galvanised", "CRANE", "500m", "Fujairah"),
        ("Turnbuckle jaw-jaw M24", "RIGGING", "30 nos", "UAE"),
        ("Pad eye plate 10T welded type", "LIFTING", "25 nos", "Abu Dhabi"),
        ("Ratchet strap 5T x 9m", "TRANSPORT", "40 nos", "Dubai"),
        ("Safety net debris netting 50sqm", "SAFETY", "5 rolls", "UAE"),
    ],
    "TPE": [
        ("PTFE tape 12mm x 10m industrial grade", "SEALING", "500 rolls", "UAE"),
        ("Polypropylene rope 16mm 3-strand", "ROPES", "200m", "Hamriyah"),
        ("Rubber gasket 6mm EPDM sheet 1x1m", "SEALING", "20 sheets", "Dubai"),
        ("Nylon gear 48T module 2 PA66", "MECHANICAL", "5 nos", "Abu Dhabi"),
        ("Plastic bearing housing UCF 205", "BEARINGS", "30 nos", "UAE"),
        ("PVC hose 25mm clear braided", "HOSES", "200m", "Sharjah"),
        ("Polyurethane seal rod 80mm", "SEALING", "10m", "UAE"),
        ("HDPE pipe 63mm SDR17 PN10", "PIPES", "300m", "Dubai"),
        ("Acetal rod 50mm natural", "MECHANICAL", "5m", "UAE"),
        ("Rubber conveyor belt 800mm EP200", "BELTS", "50m", "Jebel Ali"),
    ],
    "BB EXPORT": [
        ("Grundfos pump CM5-4 centrifugal", "PUMPS", "3 nos", "Nigeria"),
        ("ABB motor 22kW 4-pole IE3", "MOTORS", "5 nos", "Kenya"),
        ("Schneider MCCB 160A 3P", "ELECTRICAL", "20 nos", "Ghana"),
        ("Flange ball valve 4 inch 150lb", "VALVES", "10 nos", "Tanzania"),
        ("Pressure gauge 0-10 bar 6 inch", "INSTRUMENTS", "25 nos", "Ethiopia"),
        ("Cable SWA 4x16mm2 armoured", "CABLES", "500m", "Mozambique"),
        ("Gate valve 6 inch cast iron PN16", "VALVES", "8 nos", "Senegal"),
        ("Thermocouple Type K 150mm", "INSTRUMENTS", "15 nos", "Cameroon"),
        ("Transformer 100KVA 11kV/415V", "ELECTRICAL", "2 nos", "Sudan"),
        ("Diesel generator 100kVA Perkins", "POWER", "1 nos", "Uganda"),
    ],
    "PETROGULF": [
        ("Wellhead Christmas tree 5000psi", "WELLHEAD", "1 set", "Qatar"),
        ("Choke manifold 3-1/8 5000psi", "WELLHEAD", "1 set", "Kuwait"),
        ("BOP annular preventer 13-5/8", "DRILLING", "1 nos", "Oman"),
        ("Drill pipe 5 inch S-135 Range 2", "DRILLING", "50 joints", "UAE"),
        ("Cementing plug set top-bottom", "CEMENTING", "10 sets", "Saudi Arabia"),
        ("Casing 9-5/8 inch 47ppf L80 R3", "CASING", "30 joints", "Bahrain"),
        ("Mud pump liner 7.5 inch ceramic", "DRILLING", "4 nos", "Qatar"),
        ("Suction stabiliser 12 inch 1500psi", "PUMPS", "2 nos", "UAE"),
        ("Crown block sheave assembly API 8A", "DRILLING", "1 set", "Kuwait"),
        ("Kelly spinner 4.5 inch OD hex", "DRILLING", "1 nos", "Oman"),
    ],
    "ISD-EPC": [
        ("Structural steel H-beam 250x250x9x14", "STEEL", "20 tonnes", "Abu Dhabi"),
        ("Stainless pipe 316L 2 inch sch40", "PIPING", "100m", "Ruwais"),
        ("Butterfly valve WAFER 8 inch PN16", "VALVES", "15 nos", "Das Island"),
        ("Instrumentation cable 2x1.5mm2 FRLS", "CABLES", "1000m", "Abu Dhabi"),
        ("Centrifugal pump 50m3/h 40m head", "PUMPS", "4 nos", "Habshan"),
        ("Heat exchanger shell & tube 100kW", "HEAT EXCH", "2 nos", "Ruwais"),
        ("Control valve 3 inch globe ANSI150", "VALVES", "8 nos", "Abu Dhabi"),
        ("Pressure vessel ASME VIII 2000L", "VESSELS", "1 nos", "Musaffah"),
        ("Steel grating 30/100 hot-dip galv", "STRUCTURAL", "50 sqm", "Das Island"),
        ("Fire & gas detector ATEX IR H2S", "INSTRUMENTS", "20 nos", "Abu Dhabi"),
    ],
    "GD": [
        ("Office chair ergonomic mesh back", "FURNITURE", "50 nos", "Dubai"),
        ("Industrial shelving 200x100x50cm", "FURNITURE", "20 sets", "Sharjah"),
        ("Safety boots steel toe S3 size 42", "PPE", "100 pairs", "UAE"),
        ("A4 copy paper 80gsm white ream", "STATIONERY", "500 reams", "Dubai"),
        ("Janitorial trolley 90L polyprop", "CLEANING", "15 nos", "Abu Dhabi"),
        ("Fire extinguisher CO2 5kg", "SAFETY", "30 nos", "UAE"),
        ("First aid kit 50 person workplace", "SAFETY", "20 kits", "Dubai"),
        ("High-vis vest class 2 yellow", "PPE", "200 nos", "UAE"),
        ("Hand pallet truck 2500kg forks", "MATERIAL HANDLING", "5 nos", "Jebel Ali"),
        ("Safety harness full-body EN361", "PPE", "50 nos", "Abu Dhabi"),
    ],
}

COUNTS = {
    "C&J":       random.randint(14, 28),
    "TPE":       random.randint(10, 22),
    "BB EXPORT": random.randint(8, 18),
    "PETROGULF": random.randint(12, 25),
    "ISD-EPC":   random.randint(18, 35),
    "GD":        random.randint(6, 15),
}

def main():
    conn = get_connection()
    cur  = conn.cursor()

    # Fetch division IDs
    cur.execute("SELECT name, id FROM divisions")
    div_map = {r[0]: r[1] for r in cur.fetchall()}
    print("Divisions found:", div_map)

    total = 0
    for div_name, count in COUNTS.items():
        div_id = div_map.get(div_name)
        if not div_id:
            print(f"  ⚠️  Division not found: {div_name!r} — skipping")
            continue

        team_code = TEAMS[div_name]
        products  = PRODUCTS_BY_DIV[div_name]

        for i in range(count):
            prod = products[i % len(products)]
            desc, category, qty, delivery = prod
            client = random.choice(CLIENTS)

            # Generate a realistic inquiry ID
            year = 2026
            seq  = random.randint(100, 999)
            inq_id = f"INQ-{year}-{div_name[:3].upper()}-{seq:03d}-{i+1:02d}"

            # Random date in 2026 between Jan and Aug
            month = random.randint(1, 8)
            day   = random.randint(1, 28)
            saved_at = f"2026-{month:02d}-{day:02d}"

            try:
                cur.execute("""
                    INSERT INTO inquiry_master
                        (inquiry_id, client, delivery, closing_date, notes, team,
                         total_items, completed_items, division_id, created_at, updated_at)
                    VALUES (%s, %s, %s, NULL, %s, %s, %s, %s, %s, %s::date, %s::date)
                    ON CONFLICT (inquiry_id) DO NOTHING
                """, (
                    inq_id, client, delivery,
                    f"{category} — {desc}",
                    team_code,
                    1, 1,
                    div_id,
                    saved_at, saved_at,
                ))
                total += 1
            except Exception as e:
                print(f"  ⚠️  Row failed ({inq_id}): {e}")
                conn.rollback()
                continue

        conn.commit()
        print(f"  OK {div_name}: inserted {count} inquiries")

    cur.close()
    conn.close()
    print(f"\nDone — {total} total inquiry records inserted")

if __name__ == "__main__":
    main()
