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


def ensure_user(user_id: int, username: str | None):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username),
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
