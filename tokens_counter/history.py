import os
import sqlite3
from datetime import datetime

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.db")

def init_db():
    """Create the history table if it does not exist."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_summary TEXT NOT NULL,
            mode TEXT NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            cached_read_tokens INTEGER DEFAULT 0,
            cached_write_tokens INTEGER DEFAULT 0,
            total_cost REAL NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def log_call(model, prompt_summary, mode, input_tokens, output_tokens, total_cost, cached_read_tokens=0, cached_write_tokens=0):
    """Log an LLM call or simulation into the SQLite database."""
    init_db()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Cap prompt summary for database storage
    if len(prompt_summary) > 60:
        prompt_summary = prompt_summary[:57] + "..."
        
    cursor.execute("""
        INSERT INTO calls (timestamp, model, prompt_summary, mode, input_tokens, output_tokens, cached_read_tokens, cached_write_tokens, total_cost)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        model,
        prompt_summary,
        mode,
        input_tokens,
        output_tokens,
        cached_read_tokens,
        cached_write_tokens,
        total_cost
    ))
    conn.commit()
    conn.close()

def get_high_scores(limit=10):
    """Retrieve the top most expensive calls (high scores style)."""
    init_db()
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT timestamp, model, prompt_summary, mode, (input_tokens + output_tokens) as total_tokens, total_cost
        FROM calls
        ORDER BY total_cost DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_totals():
    """Retrieve aggregate usage statistics."""
    init_db()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            COUNT(id) as total_calls,
            SUM(input_tokens) as sum_in,
            SUM(output_tokens) as sum_out,
            SUM(cached_read_tokens) as sum_cache_read,
            SUM(cached_write_tokens) as sum_cache_write,
            SUM(total_cost) as sum_cost
        FROM calls
    """)
    row = cursor.fetchone()
    conn.close()
    
    return {
        "total_calls": row[0] or 0,
        "total_input_tokens": row[1] or 0,
        "total_output_tokens": row[2] or 0,
        "total_cache_read_tokens": row[3] or 0,
        "total_cache_write_tokens": row[4] or 0,
        "total_cost": row[5] or 0.0
    }

def clear_history():
    """Clear all records from the history database."""
    init_db()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM calls")
    conn.commit()
    conn.close()
