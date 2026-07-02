"""
Seed three benchmark scenarios into fms_demo (MSSQL) and set the poller checkpoint
so each "trigger" transaction is picked up fresh on the next poll.

Test Case 1 (account 2019004521) — Industrial supplier, $275k routine payment -> LOW risk (~10)
Test Case 2 (account 3045678901) — Construction company, $150k invoice fraud  -> HIGH risk (~67)
Test Case 3 (account 4012345678) — Manufacturing, $425k account takeover      -> CRITICAL (~80)

Run from the FMS root:
    python seed_scenarios.py
"""

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
import random
import pyodbc

MSSQL_CONN = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=.;"
    "DATABASE=fms_demo;"
    "TrustServerCertificate=yes;"
    "Trusted_Connection=yes;"
)
FMS_DB = str(Path(__file__).parent / "fms.db")

random.seed(42)


def connect_mssql():
    try:
        return pyodbc.connect(MSSQL_CONN, autocommit=True)
    except Exception as e:
        print(f"[ERROR] Cannot connect to MSSQL: {e}")
        sys.exit(1)


def insert_outward(conn, account_id, amount, beneficiary_account, beneficiary_name,
                   channel, currency, reference, created_at):
    sql = """
        INSERT INTO outward_transactions
            (account_id, amount, beneficiary_account, beneficiary_name,
             channel, currency, reference, created_at)
        OUTPUT INSERTED.id
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    cursor = conn.execute(sql, (
        account_id, amount, beneficiary_account, beneficiary_name,
        channel, currency, reference, created_at,
    ))
    return cursor.fetchone()[0]


def clean_scenario_accounts(conn):
    """Remove any previous seed data for these accounts so the script is idempotent."""
    accounts = ("2019004521", "3045678901", "4012345678")
    placeholders = ",".join("?" for _ in accounts)
    conn.execute(
        f"DELETE FROM outward_transactions WHERE account_id IN ({placeholders})",
        accounts,
    )
    print("Cleaned previous scenario data from outward_transactions.")


IND_VENDORS = [
    ("0112233445", "Atlas Steel Co"),
    ("0223344556", "Pacific Machinery"),
    ("0334455667", "Global Parts Ltd"),
    ("0445566778", "Westline Industrial"),
    ("0556677889", "Summit Materials"),
    ("0667788990", "CoreTech Supplies"),
    ("0778899001", "Northern Resources"),
    ("0889900112", "Apex Manufacturing"),
]
IND_AMOUNTS = [50000, 75000, 100000, 125000, 150000, 175000, 200000, 225000,
               250000, 275000, 300000, 325000, 350000, 375000, 400000, 450000, 500000]

CON_VENDORS = [
    (acc, name) for acc, name in zip(
        ["0910112233", "0921223344", "0932334455", "0943445566", "0954556677",
         "0965667788", "0976778899", "0987889900", "0998990011", "1009001122",
         "1010112233", "1021223344"],
        ["Brickwork Nigeria Ltd", "SafeLink Construction", "Eagle Scaffold Co",
         "Premier Cement Supplies", "Ironclad Roofing", "Delta Tiles & Fittings",
         "Promax Equipment Hire", "Skyline Electrical", "Buildrite Hardware",
         "FastFix Plumbing", "TrustGuard Security", "GreenScape Landscaping"],
    )
]
CON_AMOUNTS = [5000, 6500, 7200, 8000, 9500, 10000, 11500, 12000, 13000, 14500, 16000, 18000]

MFG_SUPPLIERS = [
    ("1100112233", "Texaco Industrial Parts"),
    ("1211223344", "Lone Star Machinery"),
    ("1322334455", "Gulf Coast Components"),
    ("1433445566", "Dallas Steel Works"),
    ("1544556677", "Houston Supply Group"),
]
MFG_AMOUNTS = [20000, 25000, 30000, 35000, 40000, 45000, 50000, 55000, 60000, 65000,
               70000, 75000, 80000, 45000, 55000, 35000, 65000, 50000, 40000, 60000]


def seed_history_industrial(conn) -> int:
    last_id = None
    for i in range(30):
        days_ago = random.randint(3, 85)   # keep within 90-day history window
        hour = random.randint(9, 16)
        ts = datetime.now().replace(hour=hour, minute=random.randint(0, 59),
                                     second=0, microsecond=0) - timedelta(days=days_ago)
        acc, name = IND_VENDORS[i % len(IND_VENDORS)]
        last_id = insert_outward(conn, "2019004521", random.choice(IND_AMOUNTS),
                                  acc, name, "WIRE", "USD", f"IND-HIST-{i+1:04d}", ts)
    print(f"  [IND] 30 history records (ID ends at {last_id})")
    return last_id


def seed_history_construction(conn) -> int:
    last_id = None
    for i in range(12):
        days_ago = random.randint(5, 85)   # keep within 90-day history window
        hour = random.randint(9, 16)
        ts = datetime.now().replace(hour=hour, minute=random.randint(0, 59),
                                     second=0, microsecond=0) - timedelta(days=days_ago)
        acc, name = CON_VENDORS[i]
        last_id = insert_outward(conn, "3045678901", CON_AMOUNTS[i],
                                  acc, name, "INTERNET_BANKING", "USD", f"CON-HIST-{i+1:04d}", ts)
    print(f"  [CON] 12 history records (ID ends at {last_id})")
    return last_id


def seed_history_manufacturing(conn) -> int:
    last_id = None
    for i in range(20):
        days_ago = random.randint(2, 85)   # keep within 90-day history window
        hour = random.randint(8, 16)
        ts = datetime.now().replace(hour=hour, minute=random.randint(0, 59),
                                     second=0, microsecond=0) - timedelta(days=days_ago)
        acc, name = MFG_SUPPLIERS[i % len(MFG_SUPPLIERS)]
        last_id = insert_outward(conn, "4012345678", MFG_AMOUNTS[i],
                                  acc, name, "WIRE", "USD", f"MFG-HIST-{i+1:04d}", ts)
    print(f"  [MFG] 20 history records (ID ends at {last_id})")
    return last_id


def seed_trigger_industrial(conn) -> int:
    trigger_ts = datetime.now().replace(hour=10, minute=30, second=0, microsecond=0)
    tid = insert_outward(conn, "2019004521", 275_000, "0334455667", "Global Parts Ltd",
                         "WIRE", "USD", "Test Case 1", trigger_ts)
    print(f"  [TC1] Trigger ID {tid} — $275k to Global Parts Ltd (existing vendor, 10:30am, WIRE)")
    return tid


def seed_trigger_construction(conn) -> int:
    trigger_ts = datetime.now().replace(hour=14, minute=30, second=0, microsecond=0)
    tid = insert_outward(conn, "3045678901", 150_000, "9876543210", "Swift Payment Services Ltd",
                         "INTERNET_BANKING", "USD", "Test Case 2", trigger_ts)
    print(f"  [TC2] Trigger ID {tid} — $150k to Swift Payment Services Ltd (new vendor, 2:30pm)")
    return tid


def seed_trigger_manufacturing(conn) -> int:
    trigger_ts = datetime.now().replace(hour=2, minute=0, second=0, microsecond=0)
    tid = insert_outward(conn, "4012345678", 425_000, "8765432109",
                         "International Trade Solutions",
                         "MOBILE", "USD", "Test Case 3", trigger_ts)
    print(f"  [TC3] Trigger ID {tid} — $425k via MOBILE at 02:00 to new beneficiary")
    return tid


def set_checkpoint(sqlite_path: str, table_key: str, last_id: str):
    """Point the poller checkpoint to just before the trigger transactions."""
    now = datetime.utcnow().isoformat()
    db = sqlite3.connect(sqlite_path)
    db.execute("""
        INSERT INTO processing_state (table_key, last_processed_id, last_processed_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(table_key) DO UPDATE SET
            last_processed_id = excluded.last_processed_id,
            last_processed_at = excluded.last_processed_at,
            updated_at = excluded.updated_at
    """, (table_key, last_id, now, now))
    db.commit()
    db.close()
    print(f"  Checkpoint for '{table_key}' set to ID {last_id}")


def main():
    print("=== FMS Scenario Seeder ===\n")

    conn = connect_mssql()
    print("Connected to fms_demo (MSSQL)\n")

    # Remove previous scenario data first
    clean_scenario_accounts(conn)
    print()

    # IMPORTANT: Insert ALL historical records first, then ALL triggers.
    # The MSSQL id column is IDENTITY (auto-increment), so insertion order determines ID order.
    # The poller fetches IDs > checkpoint, so histories must have lower IDs than triggers.
    print("Inserting historical baselines (all accounts)...")
    ind_hist_id = seed_history_industrial(conn)
    con_hist_id = seed_history_construction(conn)
    mfg_hist_id = seed_history_manufacturing(conn)

    # All history inserted — checkpoint stops here. Triggers come next.
    checkpoint_id = str(mfg_hist_id)
    print(f"\nSetting outward checkpoint to {checkpoint_id} (all historical records now behind this).")
    set_checkpoint(FMS_DB, "outward", checkpoint_id)

    print("\nInserting trigger transactions (poller will pick these up)...")
    ind_trigger_id = seed_trigger_industrial(conn)
    con_trigger_id = seed_trigger_construction(conn)
    mfg_trigger_id = seed_trigger_manufacturing(conn)
    print()

    print("\n=== Done ===")
    print(f"Trigger transaction IDs: IND={ind_trigger_id}, CON={con_trigger_id}, MFG={mfg_trigger_id}")
    print("Start the backend -- the poller will pick up all three triggers on the first poll.")
    print()
    print("Expected results:")
    print("  Test Case 1  acct 2019004521  $275,000  =>  CLEAN      (risk ~10  -- routine large transfer)")
    print("  Test Case 2  acct 3045678901  $150,000  =>  HIGH FRAUD (risk ~67  -- invoice fraud)")
    print("  Test Case 3  acct 4012345678  $425,000  =>  CRITICAL   (risk ~80  -- account takeover)")


if __name__ == "__main__":
    main()
