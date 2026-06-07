import json
import sqlite3
from pathlib import Path

from hermes_railway_migrator.cli import import_sessions, verify_import


def create_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            user_id TEXT,
            model TEXT,
            model_config TEXT,
            system_prompt TEXT,
            parent_session_id TEXT,
            started_at REAL NOT NULL,
            ended_at REAL,
            end_reason TEXT,
            message_count INTEGER DEFAULT 0,
            tool_call_count INTEGER DEFAULT 0,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cache_read_tokens INTEGER DEFAULT 0,
            cache_write_tokens INTEGER DEFAULT 0,
            reasoning_tokens INTEGER DEFAULT 0,
            cwd TEXT,
            billing_provider TEXT,
            billing_base_url TEXT,
            billing_mode TEXT,
            estimated_cost_usd REAL,
            actual_cost_usd REAL,
            cost_status TEXT,
            cost_source TEXT,
            pricing_version TEXT,
            title TEXT,
            api_call_count INTEGER DEFAULT 0,
            handoff_state TEXT,
            handoff_platform TEXT,
            handoff_error TEXT,
            rewind_count INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_call_id TEXT,
            tool_calls TEXT,
            tool_name TEXT,
            timestamp REAL NOT NULL,
            token_count INTEGER,
            finish_reason TEXT,
            reasoning TEXT,
            reasoning_content TEXT,
            reasoning_details TEXT,
            codex_reasoning_items TEXT,
            codex_message_items TEXT,
            platform_message_id TEXT,
            observed INTEGER DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.commit()
    conn.close()


def test_import_and_verify(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    create_db(db)
    export = tmp_path / "railway_sessions.json"
    export.write_text(json.dumps([
        {
            "id": "s1",
            "meta": {"id": "s1", "title": "Test", "started_at": 100.0, "source": "tui"},
            "messages": [
                {"role": "user", "content": "hello", "timestamp": 100.0},
                {"role": "assistant", "content": "hi", "timestamp": 101.0, "tool_calls": [{"id":"x"}]},
            ],
        }
    ]), encoding="utf-8")

    result = import_sessions(export, db, backup=True)
    assert result.inserted_sessions == 1
    assert result.inserted_messages == 2
    assert result.backup_path is not None
    assert result.backup_path.exists()
    assert verify_import(export, db) == 0

    again = import_sessions(export, db, backup=False)
    assert again.inserted_sessions == 0
    assert again.skipped_sessions == 1
    assert again.inserted_messages == 0


def test_dry_run_rolls_back(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    create_db(db)
    export = tmp_path / "railway_sessions.json"
    export.write_text(json.dumps([{"id": "s1", "meta": {"started_at": 1}, "messages": []}]), encoding="utf-8")
    result = import_sessions(export, db, backup=False, dry_run=True)
    assert result.inserted_sessions == 1
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    finally:
        conn.close()
