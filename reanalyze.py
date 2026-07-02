import sqlite3
from pathlib import Path

con = sqlite3.connect(str(Path(__file__).parent / "fms.db"))

# Delete all existing cases so everything gets re-analyzed clean
con.execute("DELETE FROM case_actions")
con.execute("DELETE FROM fraud_cases")
con.execute("UPDATE processing_state SET last_processed_id = '0' WHERE table_key = 'outward'")
con.execute("UPDATE processing_state SET last_processed_id = '0' WHERE table_key = 'inward'")
con.commit()

remaining = con.execute("SELECT COUNT(*) FROM fraud_cases").fetchone()[0]
print(f"All cases cleared. fraud_cases remaining: {remaining}")
print("Checkpoint reset. Poller will re-analyze all transactions on next cycle.")
con.close()
