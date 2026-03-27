"""
PostgreSQL connection pool — psycopg2 (adapted from GhostlyPost).
Usage:
    conn = get_db()
    rows = conn.execute("SELECT * FROM users WHERE id = %s", (uid,)).fetchall()
    conn.commit()
    conn.close()
"""

import psycopg2
import psycopg2.pool
import psycopg2.extras
from lib.config import DATABASE_URL

_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=DATABASE_URL,
        )
    return _pool


class DictRow:
    """Dict-like row wrapper — supports row["col"], row[0], row.get("col")."""

    def __init__(self, keys, values):
        self._keys = keys
        self._values = values
        self._map = dict(zip(keys, values))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._map[key]

    def get(self, key, default=None):
        return self._map.get(key, default)

    def keys(self):
        return self._keys

    def values(self):
        return self._values

    def items(self):
        return self._map.items()

    def __contains__(self, key):
        return key in self._map

    def __repr__(self):
        return repr(self._map)


class WrappedCursor:
    def __init__(self, cursor):
        self._cursor = cursor
        self._description = None

    def execute(self, query, params=None):
        self._cursor.execute(query, params)
        self._description = self._cursor.description
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        keys = [d[0] for d in self._description]
        return DictRow(keys, row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        if not rows:
            return []
        keys = [d[0] for d in self._description]
        return [DictRow(keys, r) for r in rows]

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._cursor.lastrowid


class PooledConnection:
    def __init__(self):
        self._pool = _get_pool()
        self._conn = self._pool.getconn()
        self._conn.autocommit = False

    def execute(self, query, params=None):
        cur = WrappedCursor(self._conn.cursor())
        cur.execute(query, params)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._pool.putconn(self._conn)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        self.close()


def get_db():
    return PooledConnection()


def init_db():
    conn = get_db()
    try:
        # Districts
        conn.execute("""
            CREATE TABLE IF NOT EXISTS districts (
                id SERIAL PRIMARY KEY,
                number INT UNIQUE NOT NULL,
                name VARCHAR(200),
                representative_name VARCHAR(200),
                representative_party VARCHAR(100),
                representative_email VARCHAR(200),
                representative_phone VARCHAR(50)
            )
        """)

        # Users
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                display_name VARCHAR(100),
                address_street VARCHAR(300) NOT NULL,
                address_zip VARCHAR(10),
                district_id INT REFERENCES districts(id),
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Issues
        conn.execute("""
            CREATE TABLE IF NOT EXISTS issues (
                id SERIAL PRIMARY KEY,
                title VARCHAR(300) NOT NULL,
                description TEXT NOT NULL,
                category VARCHAR(50) NOT NULL,
                location VARCHAR(300),
                district_id INT REFERENCES districts(id) NOT NULL,
                user_id INT REFERENCES users(id) NOT NULL,
                status VARCHAR(20) DEFAULT 'new',
                ai_urgency VARCHAR(20),
                ai_category_suggestion VARCHAR(50),
                ai_duplicate_of INT REFERENCES issues(id),
                vote_score INT DEFAULT 0,
                comment_count INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                resolved_at TIMESTAMP
            )
        """)

        # Votes
        conn.execute("""
            CREATE TABLE IF NOT EXISTS votes (
                id SERIAL PRIMARY KEY,
                issue_id INT REFERENCES issues(id) ON DELETE CASCADE,
                user_id INT REFERENCES users(id),
                direction SMALLINT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(issue_id, user_id)
            )
        """)

        # Comments
        conn.execute("""
            CREATE TABLE IF NOT EXISTS comments (
                id SERIAL PRIMARY KEY,
                issue_id INT REFERENCES issues(id) ON DELETE CASCADE,
                user_id INT REFERENCES users(id),
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Issue media
        conn.execute("""
            CREATE TABLE IF NOT EXISTS issue_media (
                id SERIAL PRIMARY KEY,
                issue_id INT REFERENCES issues(id) ON DELETE CASCADE,
                filename VARCHAR(300) NOT NULL,
                original_name VARCHAR(300),
                mime_type VARCHAR(50),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Security log
        conn.execute("""
            CREATE TABLE IF NOT EXISTS security_log (
                id SERIAL PRIMARY KEY,
                event_type VARCHAR(50),
                ip_address VARCHAR(50),
                details TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Indexes
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_issues_district ON issues(district_id)",
            "CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status)",
            "CREATE INDEX IF NOT EXISTS idx_issues_created ON issues(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_issues_vote_score ON issues(vote_score DESC)",
            "CREATE INDEX IF NOT EXISTS idx_votes_issue ON votes(issue_id)",
            "CREATE INDEX IF NOT EXISTS idx_votes_user ON votes(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_comments_issue ON comments(issue_id)",
            "CREATE INDEX IF NOT EXISTS idx_security_log_ip ON security_log(ip_address, created_at)",
        ]:
            conn.execute(idx_sql)

        # Seed districts
        from districts import DISTRICTS
        for d in DISTRICTS:
            conn.execute("""
                INSERT INTO districts (number, name, representative_name, representative_party,
                                       representative_email, representative_phone)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (number) DO NOTHING
            """, (d["number"], d["name"], d["representative_name"],
                  d["representative_party"], d.get("representative_email", ""),
                  d.get("representative_phone", "")))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
