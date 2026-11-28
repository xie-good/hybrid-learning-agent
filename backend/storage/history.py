"""SQLite 问答历史存储：按随机会话 UUID 隔离，每次操作使用独立数据库连接。"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.errors import AppError


class HistoryStore:
    """负责保存、查询和删除每个学习会话的问答历史记录。"""

    def __init__(self, database_path: Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute(
                'CREATE TABLE IF NOT EXISTS history ('
                'id TEXT PRIMARY KEY, session_id TEXT NOT NULL, '
                'created_at TEXT NOT NULL, payload TEXT NOT NULL)'
            )
            db.execute(
                'CREATE INDEX IF NOT EXISTS history_session ON history(session_id, created_at DESC)'
            )

    @contextmanager
    def connect(self):
        """打开并在结束后自动关闭 SQLite 连接。"""
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, payload: dict) -> str:
        """新增一条问答历史记录，并返回新生成的记录编号。"""
        record_id = str(uuid4())
        created_time = datetime.now(timezone.utc).isoformat()
        record_item = dict(payload)
        record_item['id'] = record_id
        record_item['created_at'] = created_time
        record_json = json.dumps(record_item, ensure_ascii=False)

        with self.connect() as db:
            db.execute(
                'INSERT INTO history VALUES (?, ?, ?, ?)',
                (record_id, record_item['session_id'], created_time, record_json),
            )
        return record_id

    def recent(self, session_id: str, knowledge_base_id: str | None = None, limit: int = 4) -> list[dict]:
        """按时间从早到晚返回最近几轮问答，供多轮追问时理解上下文。"""
        fetch_count = max(limit * 3, 12)
        with self.connect() as db:
            rows = db.execute(
                'SELECT payload FROM history WHERE session_id=? ORDER BY created_at DESC, id DESC LIMIT ?',
                (session_id, fetch_count),
            ).fetchall()

        matched_records = []
        for row in rows:
            record = json.loads(row['payload'])
            record_kb_id = record.get('kb_id', 'hello_agents')
            if knowledge_base_id is not None and record_kb_id != knowledge_base_id:
                continue
            matched_records.append(record)
            if len(matched_records) >= limit:
                break

        # 查询时是按最新到最旧倒序取的，反转后变成正常的对话先后顺序。
        matched_records.reverse()
        return matched_records

    def list(self, session_id: str, limit: int, offset: int, knowledge_base_id: str | None = None) -> dict:
        """分页读取当前会话的历史问答记录（按时间倒序）。"""
        with self.connect() as db:
            if knowledge_base_id is None:
                total = db.execute(
                    'SELECT count(*) FROM history WHERE session_id=?',
                    (session_id,),
                ).fetchone()[0]
                rows = db.execute(
                    'SELECT payload FROM history WHERE session_id=? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?',
                    (session_id, limit, offset),
                ).fetchall()
                items = []
                for row in rows:
                    items.append(json.loads(row['payload']))
                return {'items': items, 'total': total, 'limit': limit, 'offset': offset}

            all_rows = db.execute(
                'SELECT payload FROM history WHERE session_id=? ORDER BY created_at DESC, id DESC',
                (session_id,),
            ).fetchall()

        filtered_items = []
        for row in all_rows:
            record = json.loads(row['payload'])
            if record.get('kb_id', 'hello_agents') == knowledge_base_id:
                filtered_items.append(record)

        total = len(filtered_items)
        page_items = filtered_items[offset:offset + limit]
        return {'items': page_items, 'total': total, 'limit': limit, 'offset': offset}

    def get(self, record_id: str, session_id: str) -> dict:
        """按记录编号读取当前会话中的单条问答。"""
        with self.connect() as db:
            row = db.execute(
                'SELECT payload FROM history WHERE id=? AND session_id=?',
                (record_id, session_id),
            ).fetchone()
        if row is None:
            raise AppError(404, 'HISTORY_NOT_FOUND', '该会话中没有此历史记录。')
        return json.loads(row['payload'])

    def delete(self, record_id: str, session_id: str) -> None:
        """删除当前会话中的指定问答记录。"""
        with self.connect() as db:
            deleted_count = db.execute(
                'DELETE FROM history WHERE id=? AND session_id=?',
                (record_id, session_id),
            ).rowcount
        if not deleted_count:
            raise AppError(404, 'HISTORY_NOT_FOUND', '该会话中没有此历史记录。')

    def clear(self, session_id: str) -> int:
        """清空当前会话的全部问答历史，并返回删除条数。"""
        with self.connect() as db:
            return db.execute('DELETE FROM history WHERE session_id=?', (session_id,)).rowcount
