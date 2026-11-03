"""SQLite 问答历史；按随机会话 UUID 隔离，每次操作独立连接。"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.errors import AppError


class HistoryStore:
    def __init__(self, database_path: Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS history (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS history_session ON history(session_id, created_at DESC)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, payload: dict) -> str:
        record_id = str(uuid4())
        item = dict(payload, id=record_id, created_at=datetime.now(timezone.utc).isoformat())
        with self.connect() as db:
            db.execute('INSERT INTO history VALUES (?, ?, ?, ?)', (
                record_id, item['session_id'], item['created_at'], json.dumps(item, ensure_ascii=False)))
        return record_id

    def list(self, session_id: str, limit: int, offset: int) -> dict:
        with self.connect() as db:
            total = db.execute('SELECT count(*) FROM history WHERE session_id=?', (session_id,)).fetchone()[0]
            rows = db.execute('SELECT payload FROM history WHERE session_id=? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?', (session_id, limit, offset)).fetchall()
        return {'items': [json.loads(row['payload']) for row in rows], 'total': total, 'limit': limit, 'offset': offset}

    def get(self, record_id: str, session_id: str) -> dict:
        with self.connect() as db:
            row = db.execute('SELECT payload FROM history WHERE id=? AND session_id=?', (record_id, session_id)).fetchone()
        if row is None:
            raise AppError(404, 'HISTORY_NOT_FOUND', '该会话中没有此历史记录。')
        return json.loads(row['payload'])

    def delete(self, record_id: str, session_id: str):
        with self.connect() as db:
            count = db.execute('DELETE FROM history WHERE id=? AND session_id=?', (record_id, session_id)).rowcount
        if not count:
            raise AppError(404, 'HISTORY_NOT_FOUND', '该会话中没有此历史记录。')

    def clear(self, session_id: str) -> int:
        with self.connect() as db:
            return db.execute('DELETE FROM history WHERE session_id=?', (session_id,)).rowcount
