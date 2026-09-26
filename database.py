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
            CREATE TABLE IF NOT EXISTS goal_contributions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER PRIMARY KEY,
                expires_at TEXT,
                charge_id TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_categories (
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, category)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS star_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                charge_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sorteo_runs (
                month_key TEXT PRIMARY KEY,
                winner_user_id INTEGER,
                winner_username TEXT,
                registros INTEGER,
                ran_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recurring (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,           -- 'gasto' o 'ingreso'
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                label TEXT,
                day_of_month INTEGER NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                last_run_month TEXT,          -- month_key ("YYYY-MM") de la ultima vez que se aplico
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS debts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                direction TEXT NOT NULL,      -- 'me_deben' o 'yo_debo'
                person TEXT NOT NULL,
                amount REAL NOT NULL,
                description TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                paid_at TEXT
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


def get_last_transaction(user_id: int):
    """Devuelve el ultimo registro del usuario sin borrarlo (o None si no hay)."""
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT id, kind, amount, category FROM transactions
            WHERE user_id = ? ORDER BY id DESC LIMIT 1
            """,
            (user_id,),
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
    # Formato con espacio (no .isoformat(), que usa "T"): created_at viene de
    # CURRENT_TIMESTAMP de SQLite en formato "AAAA-MM-DD HH:MM:SS", y comparar
    # contra un string con "T" rompe la comparacion (" " < "T").
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

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


def get_summary_range(user_id: int, start_iso: str | None, end_iso: str | None):
    """Como get_summary, pero con un rango de fechas explicito (o abierto en
    cualquiera de los dos extremos). start_iso es inclusivo, end_iso es
    exclusivo -- asi se puede pedir "todo un dia" con end = dia siguiente."""
    query = (
        "SELECT kind, category, SUM(amount) as total, COUNT(*) as n "
        "FROM transactions WHERE user_id = ?"
    )
    params: list = [user_id]
    if start_iso:
        query += " AND created_at >= ?"
        params.append(start_iso)
    if end_iso:
        query += " AND created_at < ?"
        params.append(end_iso)
    query += " GROUP BY kind, category ORDER BY kind, total DESC"

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()

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
    # Formato con espacio, no .isoformat(): ver el comentario en get_summary.
    start_of_month = datetime(now.year, now.month, 1).strftime("%Y-%m-%d %H:%M:%S")
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


def delete_goal_and_contributions(user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM goals WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM goal_contributions WHERE user_id = ?", (user_id,))


def delete_budget(user_id: int, category: str):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM budgets WHERE user_id = ? AND category = ?",
            (user_id, category),
        )


def delete_all_budgets(user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM budgets WHERE user_id = ?", (user_id,))


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


# --- Suscripcion mensual (Telegram Stars) -------------------------------
#
# Se guarda solo la fecha hasta la que la suscripcion esta activa. Telegram
# renueva la suscripcion solo cada 30 dias y nos avisa con un nuevo
# successful_payment; si no se puede cobrar, simplemente no llega ese aviso
# y expires_at queda vencido, con lo que is_premium() vuelve a dar False.

def set_subscription(user_id: int, expires_at_iso: str, charge_id: str | None):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO subscriptions (user_id, expires_at, charge_id)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                expires_at = excluded.expires_at,
                charge_id = excluded.charge_id
            """,
            (user_id, expires_at_iso, charge_id),
        )


def get_subscription_expiry(user_id: int) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT expires_at FROM subscriptions WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["expires_at"] if row else None


def is_premium(user_id: int) -> bool:
    expires_at = get_subscription_expiry(user_id)
    if not expires_at:
        return False
    return expires_at > datetime.utcnow().isoformat()


# --- Categorias personalizadas -------------------------------------------
#
# Cuando el usuario escribe una categoria que no esta entre las
# predeterminadas (con "Otra categoria" o al crear un presupuesto), se
# guarda aqui para que la proxima vez aparezca junto a las predeterminadas
# en vez de tener que volver a escribirla a mano.

def add_custom_category(user_id: int, category: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO custom_categories (user_id, category) VALUES (?, ?)",
            (user_id, category),
        )


def get_custom_categories(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT category FROM custom_categories WHERE user_id = ? ORDER BY created_at",
            (user_id,),
        ).fetchall()
        return [r["category"] for r in rows]


def delete_custom_category(user_id: int, category: str) -> bool:
    """Quita una categoria propia de la lista de sugerencias (no toca los
    registros ni presupuestos que ya la usan, solo deja de aparecer para
    elegirla de nuevo). Devuelve True si habia algo que borrar."""
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM custom_categories WHERE user_id = ? AND category = ?",
            (user_id, category),
        )
        return cur.rowcount > 0


def log_star_payment(user_id: int, amount: int, charge_id: str | None):
    """Registra cada pago con Stars que llega (primer pago o renovacion), para
    poder ver cuantas suscripciones y cuantas Stars se han cobrado en total."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO star_payments (user_id, amount, charge_id) VALUES (?, ?, ?)",
            (user_id, amount, charge_id),
        )


def get_active_subscribers_count() -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as n FROM subscriptions WHERE expires_at > ?",
            (datetime.utcnow().isoformat(),),
        ).fetchone()
        return row["n"]


def get_total_star_payments_count() -> int:
    """Cuantos pagos con Stars se han recibido en total (primeros pagos +
    renovaciones), no usuarios unicos."""
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as n FROM star_payments").fetchone()
        return row["n"]


def get_total_stars_revenue() -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM star_payments"
        ).fetchone()
        return row["total"]


def get_stars_revenue_since(since_iso: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM star_payments WHERE created_at >= ?",
            (since_iso,),
        ).fetchone()
        return row["total"]


def get_recent_star_payments(limit: int = 10):
    with get_conn() as conn:
        return conn.execute(
            "SELECT user_id, amount, created_at FROM star_payments ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()


# --- Sorteo mensual -------------------------------------------------------
#
# Es una promocion pagada por quien administra el bot (no un pozo con
# dinero de otros usuarios): participa gratis cualquier usuario que llegue
# al minimo de registros EN TOTAL (de por vida -- no se reinicia cada mes,
# asi que una vez que un usuario llega al minimo sigue participando en
# todos los sorteos siguientes). sorteo_runs guarda un registro por mes
# para no volver a sortear el mismo mes dos veces si el bot se reinicia.

def get_username(user_id: int) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT username FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["username"] if row else None


def get_registro_counts_total():
    """Cuantos movimientos (gastos/ingresos) ha registrado cada usuario en
    total, de por vida (sin filtro de fecha -- el conteo nunca se reinicia)."""
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT user_id, COUNT(*) as n
            FROM transactions
            GROUP BY user_id
            """
        ).fetchall()


def get_registro_count_total(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as n FROM transactions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return row["n"]


def has_sorteo_run(month_key: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM sorteo_runs WHERE month_key = ?", (month_key,)
        ).fetchone()
        return row is not None


def record_sorteo_run(
    month_key: str,
    winner_user_id: int | None,
    winner_username: str | None,
    registros: int | None,
):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO sorteo_runs (month_key, winner_user_id, winner_username, registros)
            VALUES (?, ?, ?, ?)
            """,
            (month_key, winner_user_id, winner_username, registros),
        )


def get_sorteo_history(limit: int = 12):
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT month_key, winner_user_id, winner_username, registros
            FROM sorteo_runs ORDER BY month_key DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()


def get_recent_winner_ids(month_keys: list[str]) -> set[int]:
    """IDs de quienes ganaron en cualquiera de esos month_key -- se usa para
    excluirlos temporalmente de un sorteo nuevo."""
    if not month_keys:
        return set()
    placeholders = ",".join("?" for _ in month_keys)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT winner_user_id FROM sorteo_runs
            WHERE month_key IN ({placeholders}) AND winner_user_id IS NOT NULL
            """,
            month_keys,
        ).fetchall()
        return {r["winner_user_id"] for r in rows}


def get_last_win_month(user_id: int) -> str | None:
    """El month_key mas reciente en el que este usuario gano el sorteo, o
    None si nunca ha ganado."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT month_key FROM sorteo_runs
            WHERE winner_user_id = ? ORDER BY month_key DESC LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        return row["month_key"] if row else None


def get_last_win_timestamps() -> dict[int, str]:
    """Para cada usuario que alguna vez gano el sorteo, la fecha (ran_at) de
    su victoria mas reciente. Se usa para reiniciar su conteo de registros
    despues de ganar -- vuelve a necesitar SORTEO_MIN_REGISTROS registros
    NUEVOS (hechos despues de esa fecha) para participar otra vez, no le
    alcanza con el total historico que ya tenia antes de ganar."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT winner_user_id, MAX(ran_at) as last_win
            FROM sorteo_runs
            WHERE winner_user_id IS NOT NULL
            GROUP BY winner_user_id
            """
        ).fetchall()
        return {r["winner_user_id"]: r["last_win"] for r in rows}


def get_registro_count_since_win(user_id: int, since_iso: str) -> int:
    """Cuantos registros ha hecho este usuario DESPUES de una fecha dada
    (su ultima victoria en el sorteo) -- ambas columnas usan el mismo
    formato de CURRENT_TIMESTAMP de SQLite, asi que la comparacion de
    strings es directa."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as n FROM transactions WHERE user_id = ? AND created_at > ?",
            (user_id, since_iso),
        ).fetchone()
        return row["n"]


# --- Gastos/ingresos recurrentes ---

def add_recurring(user_id: int, kind: str, amount: float, category: str, label: str, day_of_month: int) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO recurring (user_id, kind, amount, category, label, day_of_month)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, kind, amount, category, label, day_of_month),
        )
        return cur.lastrowid


def get_recurring(user_id: int):
    """Las reglas recurrentes activas de este usuario, mas nuevas primero."""
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT id, kind, amount, category, label, day_of_month FROM recurring
            WHERE user_id = ? AND active = 1
            ORDER BY id DESC
            """,
            (user_id,),
        ).fetchall()


def get_recurring_by_id(recurring_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM recurring WHERE id = ?", (recurring_id,)
        ).fetchone()


def deactivate_recurring(recurring_id: int, user_id: int) -> bool:
    """Desactiva una regla recurrente (no se vuelve a aplicar). Verifica que
    sea del usuario que la pide borrar. Devuelve True si se borro algo."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE recurring SET active = 0 WHERE id = ? AND user_id = ? AND active = 1",
            (recurring_id, user_id),
        )
        return cur.rowcount > 0


def set_recurring_last_run(recurring_id: int, month_key: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE recurring SET last_run_month = ? WHERE id = ?",
            (month_key, recurring_id),
        )


def get_due_recurring(today: int, last_day_of_month: int, month_key: str):
    """Reglas activas que tocan hoy: su dia programado (recortado al ultimo
    dia del mes si el mes es mas corto, ej. el 31 cae el 28/29/30 en meses
    cortos) coincide con el dia de hoy, y todavia no se aplicaron este mes."""
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT id, user_id, kind, amount, category, label FROM recurring
            WHERE active = 1
              AND (last_run_month IS NULL OR last_run_month != ?)
              AND MIN(day_of_month, ?) = ?
            """,
            (month_key, last_day_of_month, today),
        ).fetchall()


# --- Registro de deudas (me deben / yo debo) ---

def add_debt(user_id: int, direction: str, person: str, amount: float, description: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO debts (user_id, direction, person, amount, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, direction, person, amount, description),
        )
        return cur.lastrowid


def get_pending_debts(user_id: int):
    """Deudas sin marcar como pagadas, mas nuevas primero."""
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT id, direction, person, amount, description FROM debts
            WHERE user_id = ? AND paid_at IS NULL
            ORDER BY id DESC
            """,
            (user_id,),
        ).fetchall()


def get_debt(debt_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM debts WHERE id = ?", (debt_id,)).fetchone()


def mark_debt_paid(debt_id: int, user_id: int) -> bool:
    """Marca una deuda como pagada/cobrada. Verifica que sea del usuario que
    lo pide. Devuelve True si se actualizo algo."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE debts SET paid_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ? AND paid_at IS NULL",
            (debt_id, user_id),
        )
        return cur.rowcount > 0


def get_debts_totals(user_id: int) -> dict:
    """Suma de deudas pendientes por direccion: cuanto le deben al usuario y
    cuanto debe el usuario."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT direction, COALESCE(SUM(amount), 0) as total FROM debts
            WHERE user_id = ? AND paid_at IS NULL
            GROUP BY direction
            """,
            (user_id,),
        ).fetchall()
        totals = {"me_deben": 0.0, "yo_debo": 0.0}
        for r in rows:
            totals[r["direction"]] = r["total"]
        return totals


