import logging
import os
import re
from datetime import datetime

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_SQLITE   = "postgresql" not in DATABASE_URL

if USE_SQLITE:
    import aiosqlite
else:
    import asyncpg


class Row(dict):
    pass


def _to_sqlite(sql: str) -> str:
    return re.sub(r'\$\d+', '?', sql)


class Database:
    def __init__(self):
        self.pool = None
        self._db  = None

    async def connect(self):
        if USE_SQLITE:
            self._db = await aiosqlite.connect("bot.db")
            self._db.row_factory = aiosqlite.Row
            logger.info("SQLite: bot.db")
        else:
            self.pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
            logger.info("PostgreSQL ulandi.")

    async def disconnect(self):
        if USE_SQLITE and self._db:
            await self._db.close()
        elif self.pool:
            await self.pool.close()

    async def create_tables(self):
        if USE_SQLITE:
            await self._db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    role TEXT DEFAULT 'user',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS courses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    course_id INTEGER NOT NULL,
                    lesson_number INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    UNIQUE(course_id, lesson_number)
                );
                CREATE TABLE IF NOT EXISTS lesson_contents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lesson_id INTEGER NOT NULL,
                    media_type TEXT NOT NULL,
                    file_id TEXT,
                    text_content TEXT,
                    order_index INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS authorized_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER UNIQUE NOT NULL,
                    channel_name TEXT DEFAULT '',
                    course_id INTEGER,
                    interval_hours INTEGER DEFAULT 24,
                    current_lesson_number INTEGER DEFAULT 1,
                    next_send_time TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now'))
                );
            """)
            await self._db.commit()
        else:
            async with self.pool.acquire() as c:
                await c.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        telegram_id BIGINT UNIQUE NOT NULL,
                        role VARCHAR(20) DEFAULT 'user',
                        created_at TIMESTAMP DEFAULT NOW()
                    );
                    CREATE TABLE IF NOT EXISTS courses (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        description TEXT DEFAULT '',
                        created_at TIMESTAMP DEFAULT NOW()
                    );
                    CREATE TABLE IF NOT EXISTS lessons (
                        id SERIAL PRIMARY KEY,
                        course_id INTEGER NOT NULL,
                        lesson_number INTEGER NOT NULL,
                        title VARCHAR(255) NOT NULL,
                        UNIQUE(course_id, lesson_number)
                    );
                    CREATE TABLE IF NOT EXISTS lesson_contents (
                        id SERIAL PRIMARY KEY,
                        lesson_id INTEGER NOT NULL,
                        media_type VARCHAR(20) NOT NULL,
                        file_id TEXT,
                        text_content TEXT,
                        order_index INTEGER DEFAULT 0
                    );
                    CREATE TABLE IF NOT EXISTS authorized_channels (
                        id SERIAL PRIMARY KEY,
                        channel_id BIGINT UNIQUE NOT NULL,
                        channel_name VARCHAR(255) DEFAULT '',
                        course_id INTEGER,
                        interval_hours INTEGER DEFAULT 24,
                        current_lesson_number INTEGER DEFAULT 1,
                        next_send_time TIMESTAMP,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT NOW()
                    );
                """)
        logger.info("Jadvallar tayyor.")

    # ── helpers ──────────────────────────────────────────────────────────────

    async def _q(self, sql, *args):
        """fetchrow"""
        if USE_SQLITE:
            async with self._db.execute(_to_sqlite(sql), args) as c:
                r = await c.fetchone()
                return Row(dict(r)) if r else None
        else:
            async with self.pool.acquire() as c:
                r = await c.fetchrow(sql, *args)
                return Row(dict(r)) if r else None

    async def _qa(self, sql, *args):
        """fetchall"""
        if USE_SQLITE:
            async with self._db.execute(_to_sqlite(sql), args) as c:
                rows = await c.fetchall()
                return [Row(dict(r)) for r in rows]
        else:
            async with self.pool.acquire() as c:
                rows = await c.fetch(sql, *args)
                return [Row(dict(r)) for r in rows]

    async def _exec(self, sql, *args):
        if USE_SQLITE:
            await self._db.execute(_to_sqlite(sql), args)
            await self._db.commit()
        else:
            async with self.pool.acquire() as c:
                await c.execute(sql, *args)

    async def _insert(self, sql, *args) -> int:
        if USE_SQLITE:
            async with self._db.execute(_to_sqlite(sql), args) as c:
                await self._db.commit()
                return c.lastrowid
        else:
            async with self.pool.acquire() as c:
                r = await c.fetchrow(sql + " RETURNING id", *args)
                return r["id"]

    # ── users ─────────────────────────────────────────────────────────────────

    async def is_admin(self, tid: int) -> bool:
        r = await self._q("SELECT role FROM users WHERE telegram_id=$1", tid)
        return r is not None and r["role"] == "admin"

    async def add_user(self, tid: int, role="user"):
        if USE_SQLITE:
            await self._db.execute(
                "INSERT OR IGNORE INTO users(telegram_id,role) VALUES(?,?)", (tid, role))
            await self._db.commit()
        else:
            await self._exec(
                "INSERT INTO users(telegram_id,role) VALUES($1,$2) ON CONFLICT DO NOTHING", tid, role)

    async def set_admin(self, tid: int):
        if USE_SQLITE:
            await self._db.execute(
                "INSERT OR REPLACE INTO users(telegram_id,role) VALUES(?,?)", (tid, "admin"))
            await self._db.commit()
        else:
            await self._exec(
                "INSERT INTO users(telegram_id,role) VALUES($1,'admin') "
                "ON CONFLICT(telegram_id) DO UPDATE SET role='admin'", tid)

    # ── courses ───────────────────────────────────────────────────────────────

    async def create_course(self, name: str, desc: str = "") -> int:
        return await self._insert(
            "INSERT INTO courses(name,description) VALUES($1,$2)", name, desc)

    async def get_all_courses(self):
        return await self._qa("SELECT * FROM courses ORDER BY id")

    async def get_course(self, cid: int):
        return await self._q("SELECT * FROM courses WHERE id=$1", cid)

    async def delete_course(self, cid: int):
        await self._exec("DELETE FROM lesson_contents WHERE lesson_id IN "
                         "(SELECT id FROM lessons WHERE course_id=$1)", cid)
        await self._exec("DELETE FROM lessons WHERE course_id=$1", cid)
        await self._exec("DELETE FROM courses WHERE id=$1", cid)

    # ── lessons ───────────────────────────────────────────────────────────────

    async def create_lesson(self, course_id: int, lesson_number: int, title: str) -> int:
        return await self._insert(
            "INSERT INTO lessons(course_id,lesson_number,title) VALUES($1,$2,$3)",
            course_id, lesson_number, title)

    async def get_lessons(self, course_id: int):
        return await self._qa(
            "SELECT * FROM lessons WHERE course_id=$1 ORDER BY lesson_number", course_id)

    async def get_lesson_by_num(self, course_id: int, num: int):
        return await self._q(
            "SELECT * FROM lessons WHERE course_id=$1 AND lesson_number=$2", course_id, num)

    async def get_total_lessons(self, course_id: int) -> int:
        r = await self._q("SELECT COUNT(*) as n FROM lessons WHERE course_id=$1", course_id)
        return r["n"] if r else 0

    async def get_next_lesson_num(self, course_id: int) -> int:
        r = await self._q(
            "SELECT COALESCE(MAX(lesson_number),0)+1 as n FROM lessons WHERE course_id=$1", course_id)
        return r["n"] if r else 1

    # ── lesson contents ───────────────────────────────────────────────────────

    async def add_content(self, lesson_id, media_type, file_id=None, text=None, idx=0):
        return await self._insert(
            "INSERT INTO lesson_contents(lesson_id,media_type,file_id,text_content,order_index)"
            " VALUES($1,$2,$3,$4,$5)",
            lesson_id, media_type, file_id, text, idx)

    async def get_contents(self, lesson_id: int):
        return await self._qa(
            "SELECT * FROM lesson_contents WHERE lesson_id=$1 ORDER BY order_index,id", lesson_id)

    # ── channels ──────────────────────────────────────────────────────────────

    async def upsert_channel(self, channel_id, name, course_id, interval_h, start: datetime):
        ts = start.strftime("%Y-%m-%d %H:%M:%S") if USE_SQLITE else start
        if USE_SQLITE:
            await self._db.execute("""
                INSERT INTO authorized_channels
                  (channel_id,channel_name,course_id,interval_hours,
                   current_lesson_number,next_send_time,is_active)
                VALUES(?,?,?,?,1,?,1)
                ON CONFLICT(channel_id) DO UPDATE SET
                  channel_name=excluded.channel_name,
                  course_id=excluded.course_id,
                  interval_hours=excluded.interval_hours,
                  current_lesson_number=1,
                  next_send_time=excluded.next_send_time,
                  is_active=1
            """, (channel_id, name, course_id, interval_h, ts))
            await self._db.commit()
        else:
            await self._exec("""
                INSERT INTO authorized_channels
                  (channel_id,channel_name,course_id,interval_hours,
                   current_lesson_number,next_send_time,is_active)
                VALUES($1,$2,$3,$4,1,$5,TRUE)
                ON CONFLICT(channel_id) DO UPDATE SET
                  channel_name=$2,course_id=$3,interval_hours=$4,
                  current_lesson_number=1,next_send_time=$5,is_active=TRUE
            """, channel_id, name, course_id, interval_h, ts)

    async def get_channel(self, channel_id: int):
        return await self._q(
            "SELECT * FROM authorized_channels WHERE channel_id=$1", channel_id)

    async def get_all_channels(self):
        return await self._qa("""
            SELECT ac.*, c.name as course_name
            FROM authorized_channels ac
            LEFT JOIN courses c ON ac.course_id=c.id
            ORDER BY ac.id
        """)

    async def get_due_channels(self, now: datetime):
        ts = now.strftime("%Y-%m-%d %H:%M:%S") if USE_SQLITE else now
        sql_s = """
            SELECT ac.*, c.name as course_name
            FROM authorized_channels ac
            JOIN courses c ON ac.course_id=c.id
            WHERE ac.is_active=1
              AND ac.next_send_time IS NOT NULL
              AND ac.next_send_time <= ?
        """
        sql_p = """
            SELECT ac.*, c.name as course_name
            FROM authorized_channels ac
            JOIN courses c ON ac.course_id=c.id
            WHERE ac.is_active=TRUE
              AND ac.next_send_time IS NOT NULL
              AND ac.next_send_time <= $1
        """
        return await self._qa(sql_s if USE_SQLITE else sql_p, ts)

    async def advance_channel(self, channel_id: int, next_num: int, next_time: datetime):
        ts = next_time.strftime("%Y-%m-%d %H:%M:%S") if USE_SQLITE else next_time
        if USE_SQLITE:
            await self._db.execute(
                "UPDATE authorized_channels SET current_lesson_number=?,next_send_time=? WHERE channel_id=?",
                (next_num, ts, channel_id))
            await self._db.commit()
        else:
            async with self.pool.acquire() as c:
                await c.execute(
                    "UPDATE authorized_channels SET current_lesson_number=$2,next_send_time=$3 WHERE channel_id=$1",
                    channel_id, next_num, next_time)

    async def deactivate_channel(self, channel_id: int):
        if USE_SQLITE:
            await self._db.execute(
                "UPDATE authorized_channels SET is_active=0 WHERE channel_id=?", (channel_id,))
            await self._db.commit()
        else:
            async with self.pool.acquire() as c:
                await c.execute(
                    "UPDATE authorized_channels SET is_active=FALSE WHERE channel_id=$1", channel_id)
        logger.warning(f"Kanal {channel_id} deaktiv.")

    async def delete_channel(self, channel_id: int):
        if USE_SQLITE:
            await self._db.execute(
                "DELETE FROM authorized_channels WHERE channel_id=?", (channel_id,))
            await self._db.commit()
        else:
            async with self.pool.acquire() as c:
                await c.execute(
                    "DELETE FROM authorized_channels WHERE channel_id=$1", channel_id)


db = Database()
