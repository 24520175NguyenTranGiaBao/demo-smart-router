import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'router_data.db')

def get_db_connection():
    """Create and return a SQLite connection configured for dict-like rows.

    Returns:
        sqlite3.Connection: Open connection to the router database.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row 
    return conn

def init_db():
    """Initialize required database schema if it does not exist.

    Creates the Devices table with default values used by scanning and
    firewall workflows.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Devices (
            MacAddress TEXT PRIMARY KEY,
            IpAddress TEXT,
            OriginalName TEXT,
            CustomName TEXT,
            IsBlocked INTEGER DEFAULT 0,
            LastSeen DATETIME DEFAULT (datetime('now', 'localtime'))
        )
    ''')
    conn.commit()
    conn.close()