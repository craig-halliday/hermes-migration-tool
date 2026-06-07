from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass
class ImportResult:
    sessions_in_file: int
    messages_in_file: int
    inserted_sessions: int
    skipped_sessions: int
    inserted_messages: int
    final_sessions: int
    final_messages: int
    backup_path: Path | None


def _load_export(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "sessions" in data:
        data = data["sessions"]
    if not isinstance(data, list):
        raise ValueError("Export must be a JSON list, or an object with a 'sessions' list")
    return data


def _table_columns(cur: sqlite3.Cursor, table: str) -> list[str]:
    cur.execute(f"PRAGMA table_info({table})")
    rows = cur.fetchall()
    if not rows:
        raise ValueError(f"Table not found or has no columns: {table}")
    return [row[1] for row in rows]


def _jsonify(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _session_id(item: dict[str, Any]) -> str | None:
    meta = item.get("meta") or {}
    return item.get("id") or meta.get("id") or meta.get("session_id")


def _session_value(meta: dict[str, Any], sid: str, messages: list[dict[str, Any]], column: str) -> Any:
    if column == "id":
        return meta.get("id") or sid
    if column == "source":
        return meta.get("source") or "railway-import"
    if column == "started_at":
        val = meta.get("started_at") or meta.get("created_at") or meta.get("timestamp")
        if val is None:
            timestamps = [m.get("timestamp") for m in messages if m.get("timestamp") is not None]
            val = min(timestamps) if timestamps else time.time()
        return val
    if column == "ended_at":
        val = meta.get("ended_at") or meta.get("updated_at")
        if val is None:
            timestamps = [m.get("timestamp") for m in messages if m.get("timestamp") is not None]
            val = max(timestamps) if timestamps else None
        return val
    if column == "message_count":
        return meta.get("message_count") if meta.get("message_count") is not None else len(messages)
    if column in {"tool_call_count", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "api_call_count"}:
        return meta.get(column) if meta.get(column) is not None else 0
    if column in {"rewind_count", "archived"}:
        return meta.get(column) if meta.get(column) is not None else 0
    if column == "cwd":
        return meta.get("cwd") or ""
    if column == "model_config":
        return _jsonify(meta.get("model_config"))
    return meta.get(column)


def _message_value(message: dict[str, Any], sid: str, column: str) -> Any:
    if column == "session_id":
        return sid
    if column == "role":
        return message.get("role") or "user"
    if column in {"tool_calls", "reasoning_details", "codex_reasoning_items", "codex_message_items"}:
        return _jsonify(message.get(column))
    if column == "timestamp":
        return message.get("timestamp") if message.get("timestamp") is not None else time.time()
    if column == "observed":
        return message.get("observed") if message.get("observed") is not None else 0
    if column == "active":
        return message.get("active") if message.get("active") is not None else 1
    return message.get(column)


def _insert(cur: sqlite3.Cursor, table: str, columns: Iterable[str], values: Iterable[Any]) -> None:
    cols = list(columns)
    vals = list(values)
    placeholders = ",".join(["?"] * len(cols))
    cur.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})", vals)


def import_sessions(input_path: Path, db_path: Path, *, backup: bool = True, dry_run: bool = False) -> ImportResult:
    input_path = input_path.expanduser().resolve()
    db_path = db_path.expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    data = _load_export(input_path)
    total_messages = sum(len(item.get("messages") or []) for item in data)

    backup_path: Path | None = None
    if backup and not dry_run:
        backup_path = db_path.with_name(db_path.name + ".bak_before_railway_import_" + time.strftime("%Y%m%d_%H%M%S"))
        shutil.copy2(db_path, backup_path)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        cur = conn.cursor()
        session_insert_columns = _table_columns(cur, "sessions")
        message_insert_columns = [c for c in _table_columns(cur, "messages") if c != "id"]

        inserted_sessions = 0
        skipped_sessions = 0
        inserted_messages = 0

        for item in data:
            sid = _session_id(item)
            if not sid:
                raise ValueError(f"Export item is missing a session id: keys={list(item.keys())}")
            meta = item.get("meta") or {}
            messages = item.get("messages") or []

            cur.execute("SELECT COUNT(*) FROM sessions WHERE id=?", (sid,))
            if cur.fetchone()[0] > 0:
                skipped_sessions += 1
                continue

            _insert(cur, "sessions", session_insert_columns, [_session_value(meta, sid, messages, c) for c in session_insert_columns])
            inserted_sessions += 1

            for message in messages:
                _insert(cur, "messages", message_insert_columns, [_message_value(message, sid, c) for c in message_insert_columns])
                inserted_messages += 1

        cur.execute("SELECT COUNT(*) FROM sessions")
        final_sessions = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM messages")
        final_messages = cur.fetchone()[0]

        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return ImportResult(len(data), total_messages, inserted_sessions, skipped_sessions, inserted_messages, final_sessions, final_messages, backup_path)


def verify_import(input_path: Path, db_path: Path) -> int:
    data = _load_export(input_path.expanduser().resolve())
    conn = sqlite3.connect(str(db_path.expanduser().resolve()))
    try:
        cur = conn.cursor()
        missing: list[str] = []
        mismatched: list[tuple[str, int, int]] = []
        for item in data:
            sid = _session_id(item)
            expected = len(item.get("messages") or [])
            cur.execute("SELECT COUNT(messages.id) FROM sessions LEFT JOIN messages ON messages.session_id=sessions.id WHERE sessions.id=? GROUP BY sessions.id", (sid,))
            row = cur.fetchone()
            if row is None:
                missing.append(str(sid))
            elif row[0] != expected:
                mismatched.append((str(sid), expected, row[0]))
    finally:
        conn.close()

    if missing:
        print("Missing sessions:")
        for sid in missing:
            print("  -", sid)
    if mismatched:
        print("Message count mismatches:")
        for sid, expected, actual in mismatched:
            print(f"  - {sid}: expected {expected}, got {actual}")
    if not missing and not mismatched:
        print(f"OK: {len(data)} exported sessions are present with matching message counts")
        return 0
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-railway-migrator")
    sub = parser.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import", help="Import railway_sessions.json into a local Hermes state.db")
    imp.add_argument("--input", required=True, type=Path, help="Path to railway_sessions.json")
    imp.add_argument("--db", required=True, type=Path, help="Path to local Hermes state.db")
    imp.add_argument("--no-backup", action="store_true", help="Do not create a pre-import database backup")
    imp.add_argument("--dry-run", action="store_true", help="Validate and simulate import, then roll back")

    ver = sub.add_parser("verify", help="Verify exported sessions exist in local state.db")
    ver.add_argument("--input", required=True, type=Path, help="Path to railway_sessions.json")
    ver.add_argument("--db", required=True, type=Path, help="Path to local Hermes state.db")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "import":
            result = import_sessions(args.input, args.db, backup=not args.no_backup, dry_run=args.dry_run)
            print(json.dumps({
                "sessions_in_file": result.sessions_in_file,
                "messages_in_file": result.messages_in_file,
                "inserted_sessions": result.inserted_sessions,
                "skipped_sessions": result.skipped_sessions,
                "inserted_messages": result.inserted_messages,
                "final_sessions": result.final_sessions,
                "final_messages": result.final_messages,
                "backup_path": str(result.backup_path) if result.backup_path else None,
                "dry_run": args.dry_run,
            }, indent=2))
            return 0
        if args.command == "verify":
            return verify_import(args.input, args.db)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 2
