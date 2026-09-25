"""Capa de datos de Finzo: usuarios, transacciones y resumenes, sobre SQLite."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

# En Railway esto apunta a un volumen persistente (ver DB_PATH en las
# variables del servicio); localmente cae en el archivo junto al codigo.
DB_PATH = os.getenv("DB_PATH", "finzo.db")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                currency TEXT DEFAULT 'USD',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,           -- 'gasto' o 'ingreso'
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                raw_text TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS budgets (
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                limit_amount REAL NOT NULL,
                PRIMARY KEY (user_id, category)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_usage (
                user_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, day)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS goals (
                user_id INTEGER PRIMARY KEY,
                target_amount REAL NOT NULL,
                label TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS achievements (
                user_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                earned_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, code)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pet (
                user_id INTEGER PRIMARY KEY,
                mood INTEGER NOT NULL DEFAULT 70
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS challenges (
                user_id INTEGER PRIMARY KEY,
                category TEXT NOT NULL,
                started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                ends_at TEXT NOT NULL,
                accepted INTEGER NOT NULL DEFAULT 0,
                resolved INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS goal_contributions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Migraciones suaves: agregan columnas nuevas si la base de datos
        # viene de una version anterior que no las tenia.
        for statement in (
            "ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'es'",
            "ALTER TABLE goals ADD COLUMN label TEXT",
        ):
            try:
                conn.execute(statement)
            except sqlite3.OperationalError:
                pass  # ya existe


def ensure_user(user_id: int, username: str | None):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username),
        )


def user_exists(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row is not None


def get_language(user_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT language FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return (row["language"] if row and row["language"] else "es")


def set_language(user_id: int, lang: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET language = ? WHERE user_id = ?",
            (lang, user_id),
        )


def set_currency(user_id: int, currency: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET currency = ? WHERE user_id = ?",
            (currency.upper(), user_id),
        )


def get_currency(user_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT currency FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["currency"] if row else "USD"


def add_transaction(user_id: int, kind: str, amount: float, category: str, raw_text: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO transactions (user_id, kind, amount, category, raw_text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, kind, amount, category, raw_text),
        )
        return cur.lastrowid


def update_transaction_category(transaction_id: int, category: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE transactions SET category = ? WHERE id = ?",
            (category, transaction_id),
        )


def update_transaction_kind(transaction_id: int, kind: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE transactions SET kind = ? WHERE id = ?",
            (kind, transaction_id),
        )


def get_transaction(transaction_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, user_id, kind, amount, category FROM transactions WHERE id = ?",
            (transaction_id,),
        ).fetchone()


def delete_last_transaction(user_id: int):
    """Elimina el ultimo registro del usuario y lo devuelve (o None si no hay)."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, kind, amount, category FROM transactions
            WHERE user_id = ? ORDER BY id DESC LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM transactions WHERE id = ?", (row["id"],))
        return row


def get_categories_summary(user_id: int):
    """Categorias que el usuario ha usado en la practica, con conteo y total.

    Esto es lo que le mostramos como "tus categorias": no una lista fija,
    sino la que se fue formando segun sus propios registros.
    """
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT kind, category, COUNT(*) as n, SUM(amount) as total
            FROM transactions
            WHERE user_id = ?
            GROUP BY kind, category
            ORDER BY kind, total DESC
            """,
            (user_id,),
        ).fetchall()


def get_summary(user_id: int, period: str = "semana"):
    """period: 'semana' o 'mes'. Devuelve totales y desglose por categoria."""
    days = 7 if period == "semana" else 30
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT kind, category, SUM(amount) as total, COUNT(*) as n
            FROM transactions
            WHERE user_id = ? AND created_at >= ?
            GROUP BY kind, category
            ORDER BY kind, total DESC
            """,
            (user_id, since),
        ).fetchall()

    ingresos = [r for r in rows if r["kind"] == "ingreso"]
    gastos = [r for r in rows if r["kind"] == "gasto"]
    total_ingresos = sum(r["total"] for r in ingresos)
    total_gastos = sum(r["total"] for r in gastos)

    return {
        "total_ingresos": total_ingresos,
        "total_gastos": total_gastos,
        "balance": total_ingresos - total_gastos,
        "ingresos_por_categoria": ingresos,
        "gastos_por_categoria": gastos,
    }


def set_budget(user_id: int, category: str, limit_amount: float):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO budgets (user_id, category, limit_amount)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, category) DO UPDATE SET limit_amount = excluded.limit_amount
            """,
            (user_id, category, limit_amount),
        )


def get_budgets(user_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT category, limit_amount FROM budgets WHERE user_id = ? ORDER BY category",
            (user_id,),
        ).fetchall()


def get_month_spent(user_id: int, category: str) -> float:
    """Total gastado en una categoria desde el dia 1 del mes actual (UTC)."""
    now = datetime.utcnow()
    start_of_month = datetime(now.year, now.month, 1).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) as total
            FROM transactions
            WHERE user_id = ? AND kind = 'gasto' AND category = ? AND created_at >= ?
            """,
            (user_id, category, start_of_month),
        ).fetchone()
        return row["total"]


def get_all_transactions(user_id: int):
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT kind, amount, category, raw_text, created_at
            FROM transactions
            WHERE user_id = ?
            ORDER BY created_at
            """,
            (user_id,),
        ).fetchall()


def get_ai_usage_count(user_id: int, day: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT count FROM ai_usage WHERE user_id = ? AND day = ?",
            (user_id, day),
        ).fetchone()
        return row["count"] if row else 0


def increment_ai_usage(user_id: int, day: str):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO ai_usage (user_id, day, count) VALUES (?, ?, 1)
            ON CONFLICT(user_id, day) DO UPDATE SET count = count + 1
            """,
            (user_id, day),
        )


def get_total_ai_usage(day: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(count), 0) as total FROM ai_usage WHERE day = ?",
            (day,),
        ).fetchone()
        return row["total"]


def set_goal(user_id: int, target_amount: float, label: str | None = None):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO goals (user_id, target_amount, label, created_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                target_amount = excluded.target_amount,
                label = excluded.label,
                created_at = excluded.created_at
            """,
            (user_id, target_amount, label),
        )


def get_goal(user_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT target_amount, label, created_at FROM goals WHERE user_id = ?",
            (user_id,),
        ).fetchone()


# --- Aportes a la meta de ahorro --------------------------------------
#
# El avance de la meta se mide por aportes que el usuario registra a
# proposito (con /aportar), no por el balance general de ingresos y
# gastos: ese balance mezcla gastos necesarios (alquiler, mercaderia,
# etc.) con el ahorro real, lo que hacia que la meta subiera o bajara
# por movimientos que no tenian nada que ver con ella.

def add_goal_contribution(user_id: int, amount: float) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO goal_contributions (user_id, amount) VALUES (?, ?)",
            (user_id, amount),
        )
        return cur.lastrowid


def get_goal_contributions_sum(user_id: int, since: str) -> float:
    """Total aportado desde una fecha (normalmente desde que se definio
    la meta actual, para que un aporte de una meta anterior no cuente)."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) as total
            FROM goal_contributions
            WHERE user_id = ? AND created_at >= ?
            """,
            (user_id, since),
        ).fetchone()
        return row["total"]


def get_net_since(user_id: int, since: str) -> float:
    """Ingresos menos gastos del usuario desde una fecha (para el avance de metas)."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN kind = 'ingreso' THEN amount ELSE 0 END), 0) -
                COALESCE(SUM(CASE WHEN kind = 'gasto' THEN amount ELSE 0 END), 0) as net
            FROM transactions
            WHERE user_id = ? AND created_at >= ?
            """,
            (user_id, since),
        ).fetchone()
        return row["net"]


def get_all_user_ids():
    with get_conn() as conn:
        rows = conn.execute("SELECT user_id FROM users").fetchall()
        return [r["user_id"] for r in rows]


def get_user_count() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as n FROM users").fetchone()
        return row["n"]


def delete_all_user_data(user_id: int):
    """Borra todo el historial del usuario (registros, presupuestos, meta y
    uso de IA), pero mantiene su moneda e idioma configurados."""
    with get_conn() as conn:
        conn.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM budgets WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM goals WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM goal_contributions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM ai_usage WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM achievements WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM challenges WHERE user_id = ?", (user_id,))
        conn.execute("UPDATE pet SET mood = 70 WHERE user_id = ?", (user_id,))


def get_transaction_count(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as n FROM transactions WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["n"]


# --- Logros -----------------------------------------------------------

def award_achievement(user_id: int, code: str) -> bool:
    """Intenta otorgar un logro. Devuelve True si es nuevo, False si ya lo tenia."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO achievements (user_id, code) VALUES (?, ?)",
            (user_id, code),
        )
        return cur.rowcount > 0


def get_achievements(user_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT code, earned_at FROM achievements WHERE user_id = ?",
            (user_id,),
        ).fetchall()


# --- Mascota virtual ----------------------------------------------------

def get_pet_mood(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT mood FROM pet WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            conn.execute("INSERT INTO pet (user_id, mood) VALUES (?, 70)", (user_id,))
            return 70
        return row["mood"]


def adjust_pet_mood(user_id: int, delta: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO pet (user_id, mood) VALUES (?, 70) ON CONFLICT(user_id) DO NOTHING",
            (user_id,),
        )
        conn.execute(
            "UPDATE pet SET mood = MAX(0, MIN(100, mood + ?)) WHERE user_id = ?",
            (delta, user_id),
        )


# --- Retos de ahorro ------------------------------------------------------

def get_top_expense_category(user_id: int, days: int = 30):
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT category, SUM(amount) as total
            FROM transactions
            WHERE user_id = ? AND kind = 'gasto' AND created_at >= ?
            GROUP BY category
            ORDER BY total DESC
            LIMIT 1
            """,
            (user_id, since),
        ).fetchone()


def get_category_spent_since(user_id: int, category: str, since: str) -> float:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) as total
            FROM transactions
            WHERE user_id = ? AND kind = 'gasto' AND category = ? AND created_at >= ?
            """,
            (user_id, category, since),
        ).fetchone()
        return row["total"]


def propose_challenge(user_id: int, category: str, ends_at: str):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO challenges (user_id, category, started_at, ends_at, accepted, resolved)
            VALUES (?, ?, CURRENT_TIMESTAMP, ?, 0, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                category = excluded.category,
                started_at = CURRENT_TIMESTAMP,
                ends_at = excluded.ends_at,
                accepted = 0,
                resolved = 0
            """,
            (user_id, category, ends_at),
        )


def accept_challenge(user_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE challenges SET accepted = 1, started_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (user_id,),
        )


def resolve_challenge(user_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE challenges SET resolved = 1 WHERE user_id = ?", (user_id,)
        )


def get_challenge(user_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT category, started_at, ends_at, accepted, resolved FROM challenges WHERE user_id = ?",
            (user_id,),
        ).fetchone()
