"""Meow (ex-Finzo): bot de Telegram para finanzas personales.

Comandos:
  /start               - registra al usuario (pide moneda si es nuevo)
  /moneda USD          - define la moneda principal del usuario
  /resumen             - menu para elegir el periodo (hoy, semana, mes,
                         un dia, un rango o todo) y ver un resumen completo:
                         ingresos/gastos, presupuestos y meta de ahorro
  /categorias          - ve las categorias que se formaron segun tus registros
  /presupuesto         - ve tus limites de gasto y desde ahi crea, actualiza
                         o borra un presupuesto (tambien acepta
                         /presupuesto comida 200 directo)
  /meta                - menu para crear tu meta de ahorro o aportar a ella
                         (tambien acepta /meta 500 viaje a Cusco directo)
  /exportar            - descargar todo tu historial en un archivo Excel
  /borrar              - menu para borrar: ultimo registro, presupuestos,
                         meta de ahorro o todo el historial (con confirmacion)
  /logros              - ve tus medallas ganadas
  /mascota             - revisa el animo de Meow (tamagotchi financiero)
  /suscripcion         - ve tu estado (registros gratis restantes o tu
                         suscripcion activa) y suscribete con Telegram Stars
  /recurrente          - menu para crear un gasto o ingreso que se registre
                         solo cada mes (ej. alquiler, sueldo), o borrar uno
  /deuda               - menu para anotar "me deben" o "yo debo", ver tus
                         deudas pendientes y marcarlas como pagadas
  /feedback            - mandale un comentario o reporte a quien mantiene el bot
  /idioma es|en        - elegir idioma (afecta el mensaje de bienvenida y
                         las respuestas de /resumen y /presupuesto)
  /ayuda               - vuelve a mostrar las instrucciones

Cualquier otro mensaje de texto se interpreta como un registro de gasto o
ingreso, ej: "gaste 50 en el mercado" o "spent $20 on groceries". Como la
categoria la decide una IA, despues de cada registro el bot pregunta si
esta bien; si no, deja elegir la correcta o cambiar el tipo con botones.

Para controlar el costo de la IA cuando hay muchos usuarios, cada usuario
tiene una cuota diaria de mensajes analizados con IA (AI_DAILY_LIMIT); al
superarla, el bot sigue funcionando con un analisis por palabras clave.

Modelo freemium: cada usuario tiene FREE_TX_LIMIT registros gratis (gastos,
ingresos y aportes a metas cuentan igual). Al llegar al limite, puede seguir
viendo resumenes/presupuestos/meta pero no anotar mas hasta suscribirse por
SUBSCRIPTION_STARS Stars al mes (pago nativo de Telegram, moneda "XTR"), que
se renueva solo cada 30 dias.

Sorteo mensual: el primer dia de cada mes se sortea SORTEO_PRIZE_USD dolares
(puestos por quien administra el bot, no por dinero de otros usuarios) entre
todos los usuarios -- gratis o suscritos -- que hayan acumulado al menos
SORTEO_MIN_REGISTROS movimientos EN TOTAL (de por vida, no se reinicia cada
mes: una vez que un usuario llega al minimo, sigue participando en todos los
sorteos siguientes). Quien gana queda excluido de volver a ganar durante
SORTEO_EXCLUSION_MONTHS meses, y ademas su conteo se reinicia desde esa
victoria: tiene que volver a llegar a SORTEO_MIN_REGISTROS registros NUEVOS
(hechos despues de ganar) para calificar de nuevo, no le alcanza con el
total historico que ya tenia antes. Ninguna de las dos condiciones se puede
saltar pagando nada -- eso reintroduce "consideration" y lo volveria un
juego de azar de pago. No hace falta pagar nada para participar (nunca se
cobra por un ticket ni existe un pozo comun), asi que es una promocion
normal y no un juego de azar con dinero de terceros. El resultado solo se le
avisa en privado a ADMIN_TELEGRAM_ID; el pago del premio se coordina fuera
del bot.
"""

import asyncio
import calendar
import datetime as dt
import html
import io
import logging
import os
import random

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)
from dotenv import load_dotenv

# Debe cargarse ANTES de importar parser: ese modulo lee ANTHROPIC_API_KEY
# apenas se importa, asi que si el .env no esta cargado todavia, no la ve.
load_dotenv()

import database as db
from parser import parse_message

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID")
AI_DAILY_LIMIT = int(os.getenv("AI_DAILY_LIMIT", "50"))
PERU_UTC_OFFSET = -5  # para el resumen semanal automatico

# Modelo freemium: 50 registros gratis (gastos/ingresos/aportes), despues
# hace falta la suscripcion mensual para seguir anotando. Se cobra con
# Telegram Stars (moneda "XTR"), que Telegram renueva sola cada 30 dias.
FREE_TX_LIMIT = 50
SUBSCRIPTION_STARS = 99
SUBSCRIPTION_PERIOD_SECONDS = 2592000  # 30 dias, el unico valor que Telegram acepta hoy
SUBSCRIPTION_PAYLOAD = "meow_premium_mensual"

# Sorteo mensual: promocion pagada por quien administra el bot (no un juego
# de azar con dinero de los usuarios). Participa gratis cualquier usuario
# -- suscrito o no -- que llegue a este minimo de registros en total (de
# por vida). Quien gana no puede volver a ganar durante los siguientes
# SORTEO_EXCLUSION_MONTHS meses (sigue participando gratis, esa exclusion
# nunca se puede saltar pagando -- eso lo volveria un juego de azar de pago).
SORTEO_MIN_REGISTROS = 45
SORTEO_PRIZE_USD = 50
SORTEO_EXCLUSION_MONTHS = 2

# Hora (Peru, UTC-5) a la que se revisan y aplican los gastos/ingresos
# recurrentes que tocan ese dia.
RECURRING_CHECK_HOUR = 8

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("finzo")

dp = Dispatcher()

WELCOME = (
    "🐱 Hola, soy Meow 💰 Te ayudo a llevar el control de tus gastos e ingresos "
    "sin salir de Telegram.\n\n"
    "Solo escribeme lo que gastaste o recibiste, en tus propias palabras ✍️:\n"
    "  - \"gaste 50 en el mercado\"\n"
    "  - \"me pagaron 300\"\n"
    "  - \"spent $20 on transport\"\n\n"
    "📋 Comandos utiles:\n"
    "/resumen - 📊 elige el periodo (hoy, semana, mes, un dia, un rango o "
    "todo) y te doy un resumen completo: ingresos/gastos, presupuestos y meta\n"
    "/moneda USD - 💱 define tu moneda (ej. PEN, USD, MXN, EUR)\n"
    "/categorias - 🏷️ ve las categorias que se formaron segun tus registros\n"
    "/presupuesto - 🎯 ve tus limites y desde ahi crea, actualiza o borra "
    "uno (categoria libre, ej. \"curso de gastronomia\")\n"
    "/meta - 🐷 menu para crear tu meta de ahorro o aportar a ella\n"
    "/exportar - 📥 descarga todo tu historial en un archivo Excel\n"
    "/borrar - 🗑️ elige que borrar: tu ultimo registro, presupuestos, tu "
    "meta o todo tu historial (siempre te pido confirmar antes)\n"
    "/logros - 🏅 ve las medallas que has ganado\n"
    "/mascota - 🐱 revisa el animo de Meow (sube si ahorras, baja si te pasas)\n"
    "/suscripcion - ⭐ revisa tus registros gratis restantes o tu suscripcion\n"
    "/sorteo - 🎟️ mira tu progreso hacia el sorteo mensual de $50\n"
    "/recurrente - 🔁 crea un gasto o ingreso que se registre solo cada mes "
    "(ej. alquiler, sueldo)\n"
    "/deuda - 🤝 anota \"me deben\" o \"yo debo\", ve tus deudas pendientes y "
    "marcalas como pagadas\n"
    "/feedback - 💬 mandame un comentario o reporte un problema\n"
    "/idioma en - 🌐 cambia el idioma (es/en)\n"
    "/ayuda - ❓ vuelve a mostrar este mensaje\n\n"
    "🤖 La categoria de cada registro la decide una IA. Por eso, despues de "
    "cada uno te voy a preguntar si esta bien; si marcas que no, te dejo "
    "elegir la categoria correcta o cambiar el tipo (gasto/ingreso) con "
    "botones 👇.\n\n"
    f"🆓 Tienes {FREE_TX_LIMIT} registros gratis. Cuando se acaben, puedes "
    f"suscribirte por {SUBSCRIPTION_STARS} Stars al mes con /suscripcion "
    "para seguir sin limite."
)

WELCOME_EN = (
    "🐱 Hi, I'm Meow 💰 I help you keep track of your expenses and income "
    "right inside Telegram.\n\n"
    "Just tell me what you spent or received, in your own words ✍️:\n"
    "  - \"spent 50 on groceries\"\n"
    "  - \"got paid 300\"\n"
    "  - \"gaste 20 en el almuerzo\"\n\n"
    "📋 Useful commands:\n"
    "/resumen - 📊 pick a period (today, week, month, a day, a range or "
    "all-time) and get a full report: income/expenses, budgets and your goal\n"
    "/moneda USD - 💱 set your currency (e.g. PEN, USD, MXN, EUR)\n"
    "/categorias - 🏷️ see the categories that formed from your own habits\n"
    "/presupuesto - 🎯 view your limits and from there create, update or "
    "delete one (free category label, e.g. \"cooking course\")\n"
    "/meta - 🐷 menu to create your savings goal or contribute to it\n"
    "/exportar - 📥 download your full history as an Excel file\n"
    "/borrar - 🗑️ pick what to delete: your last entry, budgets, your "
    "goal, or all your data (always asks to confirm first)\n"
    "/logros - 🏅 see the achievements you've earned\n"
    "/mascota - 🐱 check Meow's mood (goes up when you save, down when you overspend)\n"
    "/suscripcion - ⭐ check your free entries left or your subscription\n"
    "/sorteo - 🎟️ check your progress toward the monthly $50 giveaway\n"
    "/recurrente - 🔁 set up an expense or income that gets logged "
    "automatically every month (e.g. rent, salary)\n"
    "/deuda - 🤝 track money owed to you or that you owe, see what's "
    "pending and mark it as settled\n"
    "/feedback - 💬 send a comment or report a problem\n"
    "/idioma es - 🌐 switch language (es/en)\n"
    "/ayuda - ❓ show this message again\n\n"
    "🤖 The category for each entry is chosen by AI. That's why, after each "
    "one, I'll ask if it looks right; if not, I'll let you pick the correct "
    "category or flip the type (expense/income) with buttons 👇."
)

BOT_COMMANDS = [
    BotCommand(command="start", description="Registrarte y ver la intro"),
    BotCommand(command="resumen", description="Ver tu resumen (elige el periodo)"),
    BotCommand(command="moneda", description="Definir tu moneda"),
    BotCommand(command="categorias", description="Ver tus categorias segun tus habitos"),
    BotCommand(command="presupuesto", description="Ver, crear, actualizar o borrar presupuestos"),
    BotCommand(command="meta", description="Crear tu meta de ahorro o aportar a ella"),
    BotCommand(command="exportar", description="Descargar tu historial en Excel"),
    BotCommand(command="borrar", description="Elegir que borrar (registro, presupuestos, meta o todo)"),
    BotCommand(command="logros", description="Ver tus medallas"),
    BotCommand(command="mascota", description="Ver el animo de Meow"),
    BotCommand(command="suscripcion", description="Ver tus registros gratis o suscribirte"),
    BotCommand(command="sorteo", description="Ver tu progreso hacia el sorteo mensual de $50"),
    BotCommand(command="recurrente", description="Gastos/ingresos que se registran solos cada mes"),
    BotCommand(command="deuda", description="Anotar y ver deudas: me deben / yo debo"),
    BotCommand(command="feedback", description="Enviar un comentario o reportar un problema"),
    BotCommand(command="idioma", description="Cambiar idioma (es/en)"),
    BotCommand(command="ayuda", description="Ver los comandos disponibles"),
]

VALID_CATEGORIES = [
    "comida", "transporte", "servicios", "salud",
    "entretenimiento", "trabajo/negocio", "ahorro", "otros",
]

CATEGORY_LABELS = {
    "comida": "Comida",
    "transporte": "Transporte",
    "servicios": "Servicios",
    "salud": "Salud",
    "entretenimiento": "Entretenimiento",
    "trabajo/negocio": "Trabajo/Negocio",
    "ahorro": "Ahorro",
    "otros": "Otros",
}

# Paleta categorica validada (dataviz skill) para el grafico de /resumen.
CATEGORY_COLORS = {
    "comida": "#2a78d6",
    "transporte": "#eb6834",
    "servicios": "#1baf7a",
    "salud": "#eda100",
    "entretenimiento": "#e87ba4",
    "trabajo/negocio": "#008300",
    "ahorro": "#0891b2",
    "otros": "#4a3aa7",
}

CURRENCY_OPTIONS = ["PEN", "USD", "MXN", "EUR", "COP", "ARS"]

# user_id -> tx_id: cuando el usuario eligio "Otra categoria" y le toca
# escribir el nombre en su proximo mensaje (en vez de que se interprete
# como un nuevo registro de gasto/ingreso).
PENDING_CUSTOM_CATEGORY: dict[int, int] = {}

# user_id -> "date" o "range": cuando el usuario eligio ver el resumen de un
# dia en particular o de un rango de fechas y le toca escribirlo en su
# proximo mensaje (en vez de que se interprete como un nuevo registro).
PENDING_SUMMARY_INPUT: dict[int, str] = {}

# user_id -> "aportar" o "crear": cuando el usuario eligio una opcion del
# menu de /meta y le toca escribir el monto (y, si es "crear", la
# descripcion) en su proximo mensaje.
PENDING_GOAL_INPUT: dict[int, str] = {}

# user_id -> True: cuando el usuario eligio "Crear/actualizar presupuesto"
# y despues "Otra categoria" (o uso el atajo /presupuesto), y le toca
# escribir "categoria monto" en su proximo mensaje.
PENDING_BUDGET_INPUT: dict[int, bool] = {}

# user_id -> categoria: cuando el usuario ya eligio la categoria del
# presupuesto desde la lista (predeterminadas + las suyas) y solo le falta
# escribir el monto en su proximo mensaje.
PENDING_BUDGET_AMOUNT: dict[int, str] = {}

# user_id -> "gasto" o "ingreso": cuando el usuario eligio crear un gasto o
# ingreso recurrente y le toca escribir "monto categoria descripcion" en su
# proximo mensaje.
PENDING_RECURRING_INPUT: dict[int, str] = {}

# user_id -> "me_deben" o "yo_debo": cuando el usuario eligio anotar una
# deuda nueva y le toca escribir "monto persona descripcion" en su proximo
# mensaje.
PENDING_DEBT_INPUT: dict[int, str] = {}


def _t(lang: str, es: str, en: str) -> str:
    """Devuelve el texto en el idioma del usuario (solo "es" o "en")."""
    return en if lang == "en" else es

# codigo -> (emoji, titulo, descripcion)
ACHIEVEMENTS = {
    "primer_registro": ("🥇", "Primer paso", "Registraste tu primer movimiento."),
    "diez_registros": ("🔟", "Constancia", "Ya llevas 10 movimientos registrados."),
    "cincuenta_registros": ("💯", "Veterano/a", "Llevas 50 movimientos registrados."),
    "primer_aporte": ("🌱", "Primer aporte", "Hiciste tu primer aporte hacia tu meta de ahorro."),
    "meta_cumplida": ("🏆", "¡Meta cumplida!", "Llegaste al 100% de tu meta de ahorro."),
    "presupuesto_bajo_control": ("🛡️", "Bajo control", "Ninguno de tus presupuestos esta pasado de su limite."),
}

@dp.message(Command("start", ignore_case=True))
async def cmd_start(message: Message):
    is_new = not db.user_exists(message.from_user.id)
    db.ensure_user(message.from_user.id, message.from_user.username)

    if is_new:
        buttons = [
            InlineKeyboardButton(text=c, callback_data=f"setcur:{c}")
            for c in CURRENCY_OPTIONS
        ]
        rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
        keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
        await message.answer(
            "🐱 ¡Bienvenido/a a Meow! Antes de empezar, ¿en que moneda "
            "quieres registrar tus finanzas?",
            reply_markup=keyboard,
        )
        return

    lang = db.get_language(message.from_user.id)
    await message.answer(WELCOME_EN if lang == "en" else WELCOME)


@dp.callback_query(F.data.startswith("setcur:"))
async def cb_set_currency(callback: CallbackQuery):
    currency = callback.data.split(":", 1)[1]
    db.set_currency(callback.from_user.id, currency)
    lang = db.get_language(callback.from_user.id)
    if callback.message:
        await callback.message.edit_text(f"Listo, tu moneda es {currency}. 🎉")
        await callback.message.answer(WELCOME_EN if lang == "en" else WELCOME)
    await callback.answer()


@dp.message(Command("ayuda", ignore_case=True))
async def cmd_help(message: Message):
    db.ensure_user(message.from_user.id, message.from_user.username)
    lang = db.get_language(message.from_user.id)
    await message.answer(WELCOME_EN if lang == "en" else WELCOME)


@dp.message(Command("idioma", ignore_case=True))
async def cmd_language(message: Message, command: CommandObject):
    db.ensure_user(message.from_user.id, message.from_user.username)
    choice = (command.args or "").strip().lower()
    if choice not in ("es", "en"):
        await message.answer(
            "Usa /idioma es o /idioma en para elegir el idioma.\n"
            "Use /idioma en or /idioma es to choose the language."
        )
        return
    db.set_language(message.from_user.id, choice)
    if choice == "en":
        await message.answer("Got it, I'll show your intro in English from now on.")
    else:
        await message.answer("Listo, te muestro la intro en español de ahora en adelante.")


@dp.message(Command("moneda", ignore_case=True))
async def cmd_currency(message: Message, command: CommandObject):
    db.ensure_user(message.from_user.id, message.from_user.username)
    if not command.args:
        current = db.get_currency(message.from_user.id)
        await message.answer(
            f"Tu moneda actual es {current}. Para cambiarla: /moneda PEN (o USD, MXN, EUR, etc.)"
        )
        return
    currency = command.args.strip().split()[0]
    db.set_currency(message.from_user.id, currency)
    await message.answer(f"Listo, tu moneda ahora es {currency.upper()}.")


def _build_category_chart(rows, currency: str):
    """Grafico de barras horizontales de gastos por categoria. Devuelve un
    BytesIO con un PNG, o None si no hay datos."""
    if not rows:
        return None

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ordered = sorted(rows, key=lambda r: r["total"], reverse=True)
    categories = [r["category"] for r in ordered]
    totals = [r["total"] for r in ordered]
    colors = [CATEGORY_COLORS.get(c, "#898781") for c in categories]

    fig, ax = plt.subplots(figsize=(6, 0.6 * len(categories) + 1), dpi=150)
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    bars = ax.barh(categories, totals, color=colors, height=0.6)
    ax.invert_yaxis()
    ax.set_xlabel(f"Gasto ({currency})", color="#52514e", fontsize=9)
    ax.tick_params(colors="#52514e", labelsize=9)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.grid(axis="x", color="#e1e0d9", linewidth=0.8)
    ax.set_axisbelow(True)

    max_total = max(totals) if totals else 0
    for bar, total in zip(bars, totals):
        ax.text(
            bar.get_width() + max_total * 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"{total:.0f}",
            va="center", ha="left", fontsize=8, color="#0b0b0b",
        )

    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buffer.seek(0)
    return buffer


def _parse_report_date(text: str) -> dt.date | None:
    """Intenta leer una fecha en formatos comunes: AAAA-MM-DD, DD/MM/AAAA,
    DD-MM-AAAA. Devuelve None si no se pudo interpretar."""
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_report_range(text: str):
    """Intenta leer dos fechas de un texto libre, ej. "2026-09-01 al
    2026-09-24" o "2026-09-01 2026-09-24". Devuelve (fecha_inicio, fecha_fin)
    ya ordenadas, o None si no se pudieron leer ambas."""
    text = text.strip().lower()
    for sep in (" al ", " a ", " hasta ", " to ", " - "):
        if sep in text:
            left, right = text.split(sep, 1)
            d1, d2 = _parse_report_date(left), _parse_report_date(right)
            if d1 and d2:
                return (d1, d2) if d1 <= d2 else (d2, d1)

    dates = [d for d in (_parse_report_date(tok) for tok in text.split()) if d]
    if len(dates) >= 2:
        d1, d2 = dates[0], dates[-1]
        return (d1, d2) if d1 <= d2 else (d2, d1)
    return None


async def _send_full_report(message: Message, user_id: int, start: dt.datetime | None, end: dt.datetime | None, label: str):
    """Arma y manda el resumen tipo articulo: ingresos/gastos/balance del
    periodo elegido, mas el estado actual de presupuestos y meta de ahorro
    (esos dos son "estado actual", no dependen del periodo elegido). `label`
    ya viene en el idioma del usuario (lo arma quien llama a esta funcion)."""
    db.ensure_user(user_id, None)
    lang = db.get_language(user_id)
    currency = db.get_currency(user_id)
    # OJO: se compara contra created_at, que SQLite llena con CURRENT_TIMESTAMP
    # en formato "AAAA-MM-DD HH:MM:SS" (separador espacio). Si aca usaramos
    # .isoformat() (separador "T"), la comparacion de strings fallaria: " " <
    # "T", asi que un created_at de HOY quedaria (mal) por debajo del limite
    # de inicio. Por eso siempre .strftime con espacio para estos limites.
    start_iso = start.strftime("%Y-%m-%d %H:%M:%S") if start else None
    end_iso = end.strftime("%Y-%m-%d %H:%M:%S") if end else None
    summary = db.get_summary_range(user_id, start_iso, end_iso)

    ingresos = summary["total_ingresos"]
    gastos = summary["total_gastos"]
    balance = summary["balance"]

    paragraphs = [f"📊 <b>{_t(lang, 'Tu resumen', 'Your summary')} — {html.escape(label)}</b>"]

    if ingresos == 0 and gastos == 0:
        paragraphs.append(_t(
            lang,
            f"No registraste nada en {label}. Escribeme algo como \"gaste 20 en el mercado\" para empezar.",
            f"You didn't log anything for {label}. Try telling me something like \"spent 20 on groceries\" to get started.",
        ))
    else:
        if lang == "en":
            saldo_txt = "a positive balance" if balance >= 0 else "a negative balance"
            p = (
                f"During {label}, your income added up to <b>{ingresos:.2f} {currency}</b> and "
                f"your expenses <b>{gastos:.2f} {currency}</b>, leaving you with {saldo_txt} "
                f"of <b>{balance:.2f} {currency}</b>."
            )
        else:
            saldo_txt = "un balance positivo" if balance >= 0 else "un balance negativo"
            p = (
                f"Durante {label}, tus ingresos sumaron <b>{ingresos:.2f} {currency}</b> y "
                f"tus gastos <b>{gastos:.2f} {currency}</b>, asi que te queda {saldo_txt} "
                f"de <b>{balance:.2f} {currency}</b>."
            )
        gastos_cat = summary["gastos_por_categoria"]
        if gastos_cat:
            top = sorted(gastos_cat, key=lambda r: r["total"], reverse=True)[:3]
            frases = [f"<b>{html.escape(r['category'])}</b> ({r['total']:.2f} {currency})" for r in top]
            if len(frases) == 1:
                detalle = frases[0]
            elif len(frases) == 2:
                detalle = f"{frases[0]} {_t(lang, 'y', 'and')} {frases[1]}"
            else:
                detalle = f"{', '.join(frases[:-1])} {_t(lang, 'y', 'and')} {frases[-1]}"
            p += _t(
                lang,
                f" La mayor parte de tus gastos fue en {detalle}.",
                f" Most of your spending was on {detalle}.",
            )
            if len(gastos_cat) > 3:
                p += _t(lang, " y otras categorias.", " and other categories.")
        paragraphs.append(p)

    # --- Presupuestos: estado actual (siempre del mes en curso) ---
    budgets = db.get_budgets(user_id)
    if not budgets:
        paragraphs.append(_t(
            lang,
            "<b>Presupuestos:</b> no tienes ninguno definido. Usa \"/presupuesto "
            "comida 200\" para poner un limite mensual.",
            "<b>Budgets:</b> you don't have any set up yet. Use \"/presupuesto "
            "comida 200\" to set a monthly limit.",
        ))
    else:
        budget_lines = [_t(lang, "<b>Presupuestos de este mes:</b>", "<b>This month's budgets:</b>")]
        for row in budgets:
            spent = db.get_month_spent(user_id, row["category"])
            estado = _t(lang, "⚠️ superado", "⚠️ over") if spent > row["limit_amount"] else _t(lang, "✅ bajo control", "✅ under control")
            budget_lines.append(
                f"- {html.escape(row['category'])}: {spent:.2f} / {row['limit_amount']:.2f} "
                f"{currency} ({estado})"
            )
        paragraphs.append("\n".join(budget_lines))

    # --- Meta de ahorro: estado actual ---
    goal = db.get_goal(user_id)
    if not goal:
        paragraphs.append(_t(
            lang,
            "<b>Meta de ahorro:</b> no tienes ninguna activa. Usa \"/meta 500 viaje "
            "a Cusco\" para definir una.",
            "<b>Savings goal:</b> you don't have one active. Use \"/meta 500 trip "
            "to Cusco\" to set one up.",
        ))
    else:
        aportado = db.get_goal_contributions_sum(user_id, goal["created_at"])
        target = goal["target_amount"]
        pct = max(0, min(100, (aportado / target * 100) if target else 0))
        if lang == "en":
            para = f" for \"{html.escape(goal['label'])}\"" if goal["label"] else ""
            paragraphs.append(
                f"<b>Savings goal{para}:</b> you're at {pct:.0f}%, you've put in "
                f"{aportado:.2f} of {target:.2f} {currency} (use /meta to add more)."
            )
        else:
            para = f" para \"{html.escape(goal['label'])}\"" if goal["label"] else ""
            paragraphs.append(
                f"<b>Meta de ahorro{para}:</b> vas en el {pct:.0f}%, llevas aportado "
                f"{aportado:.2f} de {target:.2f} {currency} (usa /meta para sumar)."
            )

    paragraphs.append(_t(
        lang,
        "🐱 Usa /presupuesto o /meta para actualizar cualquiera de estos.",
        "🐱 Use /presupuesto or /meta to update either of these.",
    ))

    await message.answer("\n\n".join(paragraphs), parse_mode="HTML")

    try:
        chart_buffer = _build_category_chart(summary["gastos_por_categoria"], currency)
        if chart_buffer:
            photo = BufferedInputFile(chart_buffer.read(), filename="resumen.png")
            await message.answer_photo(photo, caption=_t(lang, "📊 Gastos por categoria", "📊 Spending by category"))
    except Exception as exc:
        logger.warning("No se pudo generar el grafico de resumen: %s", exc)


@dp.message(Command("resumen", ignore_case=True))
async def cmd_summary(message: Message):
    db.ensure_user(message.from_user.id, message.from_user.username)
    lang = db.get_language(message.from_user.id)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_t(lang, "Hoy", "Today"), callback_data="resumen:hoy"),
                InlineKeyboardButton(text=_t(lang, "Esta semana", "This week"), callback_data="resumen:semana"),
            ],
            [
                InlineKeyboardButton(text=_t(lang, "Este mes", "This month"), callback_data="resumen:mes"),
                InlineKeyboardButton(text=_t(lang, "Todo el historial", "All-time"), callback_data="resumen:todo"),
            ],
            [
                InlineKeyboardButton(text=_t(lang, "📅 Un dia en particular", "📅 A specific day"), callback_data="resumen:dia"),
                InlineKeyboardButton(text=_t(lang, "📆 Un rango de fechas", "📆 A date range"), callback_data="resumen:rango"),
            ],
            [InlineKeyboardButton(text=_t(lang, "Cancelar", "Cancel"), callback_data="delcancel")],
        ]
    )
    await message.answer(_t(lang, "¿De que periodo quieres tu resumen?", "Which period do you want your summary for?"), reply_markup=keyboard)


@dp.callback_query(F.data.startswith("resumen:"))
async def cb_resumen_period(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = db.get_language(user_id)
    choice = callback.data.split(":", 1)[1]

    if choice == "dia":
        PENDING_SUMMARY_INPUT[user_id] = "date"
        if callback.message:
            await callback.message.edit_text(_t(
                lang,
                "Escribeme la fecha que quieres ver, en formato AAAA-MM-DD (ej. 2026-09-20).",
                "Tell me the date you want to see, in YYYY-MM-DD format (e.g. 2026-09-20).",
            ))
        await callback.answer()
        return

    if choice == "rango":
        PENDING_SUMMARY_INPUT[user_id] = "range"
        if callback.message:
            await callback.message.edit_text(_t(
                lang,
                "Escribeme el rango de fechas, ej. \"2026-09-01 al 2026-09-24\".",
                "Tell me the date range, e.g. \"2026-09-01 to 2026-09-24\".",
            ))
        await callback.answer()
        return

    now = dt.datetime.utcnow()
    if choice == "hoy":
        start = dt.datetime(now.year, now.month, now.day)
        end = start + dt.timedelta(days=1)
        label = _t(lang, f"hoy ({start.date().isoformat()})", f"today ({start.date().isoformat()})")
    elif choice == "semana":
        start = now - dt.timedelta(days=7)
        end = None
        label = _t(lang, "los ultimos 7 dias", "the last 7 days")
    elif choice == "mes":
        start = dt.datetime(now.year, now.month, 1)
        end = None
        label = _t(lang, "este mes", "this month")
    elif choice == "todo":
        start = None
        end = None
        label = _t(lang, "todo tu historial", "your entire history")
    else:
        await callback.answer()
        return

    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await _send_full_report(callback.message, user_id, start, end, label)
    await callback.answer()


@dp.message(Command("categorias", ignore_case=True))
async def cmd_categories(message: Message):
    db.ensure_user(message.from_user.id, message.from_user.username)
    rows = db.get_categories_summary(message.from_user.id)
    currency = db.get_currency(message.from_user.id)
    lang = db.get_language(message.from_user.id)

    if not rows:
        await message.answer(_t(
            lang,
            "Todavia no tienes categorias propias: se van formando segun lo "
            "que registres. Prueba escribiendo algo como \"gaste 20 en almuerzo\".",
            "You don't have any categories of your own yet: they form as you "
            "log things. Try something like \"spent 20 on lunch\".",
        ))
        return

    gastos = [r for r in rows if r["kind"] == "gasto"]
    ingresos = [r for r in rows if r["kind"] == "ingreso"]

    lines = [_t(lang, "Estas son tus categorias, segun como has usado el bot:", "Here are your categories, based on how you've used the bot:")]
    if gastos:
        lines.append(_t(lang, "\nGastos:", "\nExpenses:"))
        for r in gastos:
            lines.append(f"  - {r['category']}: {r['total']:.2f} {currency} ({r['n']} {_t(lang, 'registros', 'entries')})")
    if ingresos:
        lines.append(_t(lang, "\nIngresos:", "\nIncome:"))
        for r in ingresos:
            lines.append(f"  - {r['category']}: {r['total']:.2f} {currency} ({r['n']} {_t(lang, 'registros', 'entries')})")

    lines.append(_t(
        lang,
        "\nSi alguna vez te pregunto y marcas que una categoria no esta bien, "
        "la corrijo y asi esta lista refleja mejor tus habitos reales.",
        "\nIf I ever ask and you mark a category as wrong, I'll fix it so this "
        "list better reflects your real habits.",
    ))
    await message.answer("\n".join(lines))


def _user_categories(user_id: int) -> list[str]:
    """Categorias predeterminadas + las que el usuario fue agregando a mano
    (con "Otra categoria" o al crear un presupuesto), sin duplicados."""
    custom = [c for c in db.get_custom_categories(user_id) if c not in VALID_CATEGORIES]
    return VALID_CATEGORIES + custom


def _category_list_rows(user_id: int, callback_data_for) -> list[list[InlineKeyboardButton]]:
    """Una fila por categoria (lista vertical, no una grilla), para que se
    lea como una lista de opciones en vez de botones sueltos."""
    return [
        [InlineKeyboardButton(
            text=CATEGORY_LABELS.get(c, c.capitalize()),
            callback_data=callback_data_for(c),
        )]
        for c in _user_categories(user_id)
    ]


async def _save_budget(message: Message, user_id: int, category: str, limit_amount: float):
    lang = db.get_language(user_id)
    currency = db.get_currency(user_id)
    db.set_budget(user_id, category, limit_amount)
    if category not in VALID_CATEGORIES:
        db.add_custom_category(user_id, category)

    note = ""
    if category not in VALID_CATEGORIES:
        note = _t(
            lang,
            "\n\nComo \"{}\" no es una de las categorias que uso para clasificar tus "
            "gastos automaticamente, este limite solo va a sumar los gastos que tu "
            "asignes manualmente a esa categoria. La agregue a tu lista de "
            "categorias para que la veas junto a las demas la proxima vez.",
            "\n\nSince \"{}\" isn't one of the categories I use to classify your "
            "expenses automatically, this limit will only add up expenses you "
            "assign to it manually. I added it to your category list so you "
            "see it alongside the rest next time.",
        ).format(category)
    label = CATEGORY_LABELS.get(category, category)
    text = _t(
        lang,
        f"Listo, tu limite mensual para \"{label}\" es {limit_amount:.2f} {currency}.{note}",
        f"Done, your monthly limit for \"{label}\" is {limit_amount:.2f} {currency}.{note}",
    )
    await message.answer(text)


async def _process_budget_creation(message: Message, user_id: int, args_text: str) -> bool:
    """Parsea "<categoria> <monto>" y crea/actualiza ese presupuesto.
    Devuelve True si se guardo, False si hubo un error de formato (y ya se
    le aviso)."""
    lang = db.get_language(user_id)
    parts = args_text.strip().rsplit(" ", 1)
    if len(parts) != 2:
        await message.answer(_t(
            lang,
            "Formato: categoria monto (ej. \"comida 200\" o \"curso de gastronomia 8000\").",
            "Format: category amount (e.g. \"food 200\" or \"cooking course 8000\").",
        ))
        return False

    category, raw_amount = parts[0].strip().lower(), parts[1].strip()
    if not category:
        await message.answer(_t(lang, "Falta el nombre de la categoria. Ejemplo: \"comida 200\".", "Missing the category name. Example: \"food 200\"."))
        return False
    try:
        limit_amount = float(raw_amount.replace(",", "."))
    except ValueError:
        await message.answer(_t(lang, "El monto no es valido. Ejemplo: \"comida 200\".", "That amount isn't valid. Example: \"food 200\"."))
        return False

    await _save_budget(message, user_id, category, limit_amount)
    return True


async def _process_budget_amount(message: Message, user_id: int, category: str, amount_text: str) -> bool:
    """Como _process_budget_creation, pero la categoria ya se eligio de la
    lista y solo falta parsear el monto que el usuario acaba de escribir."""
    lang = db.get_language(user_id)
    try:
        limit_amount = float(amount_text.strip().split()[0].replace(",", "."))
    except (ValueError, IndexError):
        await message.answer(_t(lang, "Monto invalido. Ejemplo: 200", "Invalid amount. Example: 200"))
        return False
    if limit_amount <= 0:
        await message.answer(_t(lang, "El monto debe ser mayor que cero.", "The amount must be greater than zero."))
        return False

    await _save_budget(message, user_id, category, limit_amount)
    return True


@dp.message(Command("presupuesto", ignore_case=True))
async def cmd_budget(message: Message, command: CommandObject):
    user_id = message.from_user.id
    db.ensure_user(user_id, message.from_user.username)
    lang = db.get_language(user_id)
    currency = db.get_currency(user_id)

    if command.args:
        # Atajo directo para quien ya se sabe el formato: /presupuesto comida 200.
        await _process_budget_creation(message, user_id, command.args)
        return

    budgets = db.get_budgets(user_id)
    if not budgets:
        status_text = _t(lang, "No tienes presupuestos definidos todavia.", "You don't have any budgets set up yet.")
    else:
        lines = [_t(lang, f"Tus presupuestos mensuales ({currency}):", f"Your monthly budgets ({currency}):")]
        all_under_control = True
        for row in budgets:
            spent = db.get_month_spent(user_id, row["category"])
            if spent > row["limit_amount"]:
                all_under_control = False
            lines.append(f"  - {row['category']}: {spent:.2f} / {row['limit_amount']:.2f}")
        status_text = "\n".join(lines)
        if all_under_control:
            await _award(message, user_id, "presupuesto_bajo_control")

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=_t(lang, "🎯 Crear/actualizar presupuesto", "🎯 Create/update a budget"), callback_data="presupuestomenu:crear"),
            InlineKeyboardButton(text=_t(lang, "🗑️ Borrar un presupuesto", "🗑️ Delete a budget"), callback_data="presupuestomenu:borrar"),
        ]]
    )
    await message.answer(status_text, reply_markup=keyboard)


@dp.callback_query(F.data.startswith("presupuestomenu:"))
async def cb_presupuestomenu(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = db.get_language(user_id)
    choice = callback.data.split(":", 1)[1]

    if choice == "crear":
        rows = _category_list_rows(user_id, lambda c: f"presupuestocat:{c}")
        rows.append([InlineKeyboardButton(text=_t(lang, "✏️ Otra categoria", "✏️ Another category"), callback_data="presupuestocat:otra")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
        if callback.message:
            await callback.message.edit_text(
                _t(lang, "¿Para cual categoria quieres poner o actualizar un limite?", "Which category do you want to set or update a limit for?"),
                reply_markup=keyboard,
            )
        await callback.answer()
        return

    if choice == "borrar":
        await cb_delmenu_budgets(callback)
        return

    await callback.answer()


@dp.callback_query(F.data.startswith("presupuestocat:"))
async def cb_presupuestocat(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = db.get_language(user_id)
    category = callback.data.split(":", 1)[1]

    if category == "otra":
        PENDING_BUDGET_INPUT[user_id] = True
        if callback.message:
            await callback.message.edit_text(_t(
                lang,
                "Escribe la categoria y el monto, ej. \"curso de gastronomia 8000\".",
                "Write the category and the amount, e.g. \"cooking course 8000\".",
            ))
        await callback.answer()
        return

    PENDING_BUDGET_AMOUNT[user_id] = category
    if callback.message:
        label = CATEGORY_LABELS.get(category, category.capitalize())
        await callback.message.edit_text(_t(
            lang,
            f"¿Cual es el limite mensual para \"{label}\"? Escribe el monto, ej. 200.",
            f"What's the monthly limit for \"{label}\"? Write the amount, e.g. 200.",
        ))
    await callback.answer()


async def _process_goal_creation(message: Message, user_id: int, args_text: str) -> bool:
    """Parsea "<monto> [descripcion]" y crea/actualiza la meta. Devuelve True
    si se guardo, False si hubo un error de formato (y ya se le aviso)."""
    currency = db.get_currency(user_id)
    parts = args_text.strip().split(maxsplit=1)
    try:
        target_amount = float(parts[0].replace(",", "."))
    except (ValueError, IndexError):
        await message.answer(
            "Formato: 500 viaje a Cusco (la descripcion despues del monto es "
            "opcional)."
        )
        return False

    if target_amount <= 0:
        await message.answer("El monto debe ser mayor que cero.")
        return False

    label = parts[1].strip() if len(parts) > 1 else None
    db.set_goal(user_id, target_amount, label)
    para = f" para \"{label}\"" if label else ""
    await message.answer(
        f"🐷 Meta guardada: ahorrar {target_amount:.2f} {currency}{para}. Usa "
        f"/meta cuando quieras aportar o ver tu avance."
    )
    return True


async def _process_contribution(message: Message, user_id: int, amount_text: str) -> bool:
    """Parsea un monto y lo suma a la meta actual. Devuelve True si se
    registro, False si hubo un error de formato (y ya se le aviso). Asume que
    ya se verifico que existe una meta."""
    currency = db.get_currency(user_id)
    goal = db.get_goal(user_id)
    try:
        amount = float(amount_text.strip().split()[0].replace(",", "."))
    except (ValueError, IndexError):
        await message.answer("Monto invalido. Ejemplo: 50")
        return False

    if amount <= 0:
        await message.answer("El monto debe ser mayor que cero.")
        return False

    if not await _check_and_block_limit(message, user_id):
        return False

    db.add_goal_contribution(user_id, amount)
    target = goal["target_amount"]
    label = goal["label"]

    # El aporte tambien se registra como un gasto en "ahorro": asi el
    # dinero que apartas para tu meta se resta de tu balance (ingresos -
    # gastos), en vez de seguir apareciendo como disponible.
    label_quoted = f' "{label}"' if label else ""
    desc = f"aporte a la meta{label_quoted}"
    db.add_transaction(user_id, "gasto", amount, "ahorro", desc)
    db.adjust_pet_mood(user_id, 3)

    aportado = db.get_goal_contributions_sum(user_id, goal["created_at"])
    pct = max(0, min(100, (aportado / target * 100) if target else 0))
    para = f" para \"{label}\"" if label else ""
    await message.answer(
        f"💰 Aporte registrado: {amount:.2f} {currency} (tambien se anoto "
        f"como gasto en \"ahorro\" para que se refleje en tu balance).\n"
        f"Llevas {aportado:.2f} / {target:.2f} {currency} ({pct:.0f}%){para}."
    )
    await _check_goal_achievements(message, user_id)
    await _check_registro_achievements(message, user_id)
    await _check_budget_alert(message, user_id, "ahorro")
    await _maybe_warn_limit(message, user_id)
    return True


@dp.message(Command("meta", ignore_case=True))
async def cmd_goal(message: Message, command: CommandObject):
    user_id = message.from_user.id
    db.ensure_user(user_id, message.from_user.username)
    currency = db.get_currency(user_id)

    if command.args:
        # Atajo directo para quien ya se sabe el formato: /meta 500 viaje.
        await _process_goal_creation(message, user_id, command.args)
        return

    goal = db.get_goal(user_id)
    if not goal:
        status_text = (
            "No tienes una meta de ahorro todavia. Usa \"🎯 Crear meta\" para "
            "definir cuanto quieres ahorrar y para que (la descripcion es "
            "opcional)."
        )
    else:
        aportado = db.get_goal_contributions_sum(user_id, goal["created_at"])
        target = goal["target_amount"]
        label = goal["label"]
        pct = max(0, min(100, (aportado / target * 100) if target else 0))
        para = f" para \"{label}\"" if label else ""
        status_text = (
            f"🐷 Tu meta{para} es ahorrar {target:.2f} {currency}.\n"
            f"Llevas aportado {aportado:.2f} {currency} ({pct:.0f}%)."
        )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="💰 Aportar", callback_data="metamenu:aportar"),
            InlineKeyboardButton(text="🎯 Crear/actualizar meta", callback_data="metamenu:crear"),
        ]]
    )
    await message.answer(status_text, reply_markup=keyboard)


@dp.callback_query(F.data.startswith("metamenu:"))
async def cb_metamenu(callback: CallbackQuery):
    user_id = callback.from_user.id
    choice = callback.data.split(":", 1)[1]

    if choice == "aportar":
        goal = db.get_goal(user_id)
        if not goal:
            if callback.message:
                await callback.message.edit_text(
                    "Todavia no tienes una meta de ahorro. Escribe /meta de "
                    "nuevo y usa \"🎯 Crear/actualizar meta\" primero."
                )
            await callback.answer()
            return
        PENDING_GOAL_INPUT[user_id] = "aportar"
        if callback.message:
            await callback.message.edit_text("¿Cuanto quieres aportar? Escribe el monto, ej. 50.")
        await callback.answer()
        return

    if choice == "crear":
        PENDING_GOAL_INPUT[user_id] = "crear"
        if callback.message:
            await callback.message.edit_text(
                "Escribe el monto de tu meta y, si quieres, para que es. "
                "Ej: \"500 viaje a Cusco\"."
            )
        await callback.answer()
        return

    await callback.answer()


@dp.message(Command("aportar", ignore_case=True))
async def cmd_contribute(message: Message, command: CommandObject):
    # Se mantiene funcionando (sin publicitarse en /ayuda ni en el menu de
    # comandos) por si alguien lo escribe por costumbre: ahora la forma
    # principal de aportar es /meta > "Aportar".
    user_id = message.from_user.id
    db.ensure_user(user_id, message.from_user.username)
    goal = db.get_goal(user_id)

    if not goal:
        await message.answer(
            "Todavia no tienes una meta de ahorro. Usa \"/meta 500 viaje a "
            "Cusco\" para crear una primero."
        )
        return

    if not command.args:
        await message.answer("¿Cuanto quieres aportar? Ejemplo: /aportar 50")
        return

    await _process_contribution(message, user_id, command.args)


@dp.message(Command("exportar", ignore_case=True))
async def cmd_export(message: Message):
    db.ensure_user(message.from_user.id, message.from_user.username)
    rows = db.get_all_transactions(message.from_user.id)

    if not rows:
        await message.answer("Todavia no tienes movimientos registrados para exportar.")
        return

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Finzo"
    ws.append(["Fecha", "Tipo", "Monto", "Categoria", "Detalle"])
    for row in rows:
        ws.append([row["created_at"], row["kind"], row["amount"], row["category"], row["raw_text"]])

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    file = BufferedInputFile(buffer.read(), filename="finzo_historial.xlsx")
    await message.answer_document(file, caption="Aqui tienes todo tu historial en Excel.")


# user_id -> lista de categorias de presupuesto mostradas en el ultimo
# menu de "Borrar presupuestos" (asi los botones no dependen de meter la
# categoria completa, que puede ser texto libre largo, en el callback_data).
PENDING_DELETE_BUDGETS: dict[int, list[str]] = {}


@dp.message(Command("deshacer", ignore_case=True))
async def cmd_undo(message: Message):
    # Se mantiene funcionando (sin publicitarse en /ayuda ni en el menu de
    # comandos) por si alguien lo escribe por costumbre: ahora la forma
    # principal de deshacer un registro es /borrar.
    db.ensure_user(message.from_user.id, message.from_user.username)
    row = db.delete_last_transaction(message.from_user.id)
    if not row:
        await message.answer("No tienes registros para deshacer.")
        return
    currency = db.get_currency(message.from_user.id)
    await message.answer(
        f"↩️ Listo, elimine tu ultimo registro: {row['kind']} de "
        f"{row['amount']:.2f} {currency} en \"{row['category']}\"."
    )


@dp.message(Command("borrartodo", ignore_case=True))
async def cmd_delete_all(message: Message):
    # Igual que /deshacer: se mantiene por costumbre, pero /borrar > "Borrar
    # todo" es la forma que se muestra ahora.
    db.ensure_user(message.from_user.id, message.from_user.username)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="⚠️ Si, borrar todo", callback_data="delall:confirm"),
            InlineKeyboardButton(text="Cancelar", callback_data="delcancel"),
        ]]
    )
    await message.answer(
        "⚠️ Esto va a borrar TODOS tus registros, presupuestos y tu meta de "
        "ahorro. No se puede deshacer. Tu moneda e idioma se mantienen.\n\n"
        "¿Seguro que quieres continuar?",
        reply_markup=keyboard,
    )


@dp.callback_query(F.data == "delall:confirm")
async def cb_delete_all_confirm(callback: CallbackQuery):
    db.delete_all_user_data(callback.from_user.id)
    if callback.message:
        await callback.message.edit_text(
            "🗑️ Listo, borre todos tus registros, presupuestos y tu meta de ahorro."
        )
    await callback.answer("Datos borrados")


@dp.callback_query(F.data == "delcancel")
async def cb_delete_cancel(callback: CallbackQuery):
    PENDING_DELETE_BUDGETS.pop(callback.from_user.id, None)
    if callback.message:
        await callback.message.edit_text("Cancelado, no borre nada.")
    await callback.answer()


@dp.message(Command("borrar", ignore_case=True))
async def cmd_delete_menu(message: Message):
    db.ensure_user(message.from_user.id, message.from_user.username)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Borrar el ultimo registro", callback_data="delmenu:last")],
            [InlineKeyboardButton(text="🎯 Borrar presupuestos", callback_data="delmenu:budgets")],
            [InlineKeyboardButton(text="🐷 Borrar mi meta de ahorro", callback_data="delmenu:goal")],
            [InlineKeyboardButton(text="🗑️ Borrar TODO mi historial", callback_data="delmenu:all")],
            [InlineKeyboardButton(text="Cancelar", callback_data="delcancel")],
        ]
    )
    await message.answer("¿Que quieres borrar?", reply_markup=keyboard)


@dp.callback_query(F.data == "delmenu:last")
async def cb_delmenu_last(callback: CallbackQuery):
    user_id = callback.from_user.id
    tx = db.get_last_transaction(user_id)
    if not tx:
        if callback.message:
            await callback.message.edit_text("No tienes registros para borrar.")
        await callback.answer()
        return
    currency = db.get_currency(user_id)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="⚠️ Si, borrarlo", callback_data="dellast:confirm"),
            InlineKeyboardButton(text="Cancelar", callback_data="delcancel"),
        ]]
    )
    if callback.message:
        await callback.message.edit_text(
            f"¿Seguro que quieres borrar tu ultimo registro: {tx['kind']} de "
            f"{tx['amount']:.2f} {currency} en \"{tx['category']}\"?",
            reply_markup=keyboard,
        )
    await callback.answer()


@dp.callback_query(F.data == "dellast:confirm")
async def cb_dellast_confirm(callback: CallbackQuery):
    row = db.delete_last_transaction(callback.from_user.id)
    if callback.message:
        if row:
            currency = db.get_currency(callback.from_user.id)
            await callback.message.edit_text(
                f"↩️ Listo, borre tu ultimo registro: {row['kind']} de "
                f"{row['amount']:.2f} {currency} en \"{row['category']}\"."
            )
        else:
            await callback.message.edit_text("No tenias registros para borrar.")
    await callback.answer("Listo")


@dp.callback_query(F.data == "delmenu:budgets")
async def cb_delmenu_budgets(callback: CallbackQuery):
    user_id = callback.from_user.id
    budgets = db.get_budgets(user_id)
    if not budgets:
        if callback.message:
            await callback.message.edit_text("No tienes presupuestos definidos.")
        await callback.answer()
        return

    categories = [b["category"] for b in budgets]
    PENDING_DELETE_BUDGETS[user_id] = categories
    rows = [
        [InlineKeyboardButton(text=cat, callback_data=f"delbud:{i}")]
        for i, cat in enumerate(categories)
    ]
    rows.append([InlineKeyboardButton(text="🗑️ Todos los presupuestos", callback_data="delbud:all")])
    rows.append([InlineKeyboardButton(text="Cancelar", callback_data="delcancel")])
    if callback.message:
        await callback.message.edit_text(
            "¿Cual presupuesto quieres borrar?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("delbud:"))
async def cb_delbud_pick(callback: CallbackQuery):
    user_id = callback.from_user.id
    choice = callback.data.split(":", 1)[1]

    if choice == "all":
        categories = PENDING_DELETE_BUDGETS.get(user_id) or [b["category"] for b in db.get_budgets(user_id)]
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="⚠️ Si, borrar todos", callback_data="delbudconfirm:all"),
                InlineKeyboardButton(text="Cancelar", callback_data="delcancel"),
            ]]
        )
        if callback.message:
            await callback.message.edit_text(
                f"¿Seguro que quieres borrar tus {len(categories)} presupuestos?",
                reply_markup=keyboard,
            )
        await callback.answer()
        return

    categories = PENDING_DELETE_BUDGETS.get(user_id)
    try:
        category = categories[int(choice)]
    except (TypeError, ValueError, IndexError):
        if callback.message:
            await callback.message.edit_text("Esa opcion ya no es valida, usa /borrar de nuevo.")
        await callback.answer()
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="⚠️ Si, borrarlo", callback_data=f"delbudconfirm:{choice}"),
            InlineKeyboardButton(text="Cancelar", callback_data="delcancel"),
        ]]
    )
    if callback.message:
        await callback.message.edit_text(
            f"¿Seguro que quieres borrar tu presupuesto de \"{category}\"?",
            reply_markup=keyboard,
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("delbudconfirm:"))
async def cb_delbud_confirm(callback: CallbackQuery):
    user_id = callback.from_user.id
    choice = callback.data.split(":", 1)[1]

    if choice == "all":
        db.delete_all_budgets(user_id)
        PENDING_DELETE_BUDGETS.pop(user_id, None)
        if callback.message:
            await callback.message.edit_text("🗑️ Listo, borre todos tus presupuestos.")
        await callback.answer("Presupuestos borrados")
        return

    categories = PENDING_DELETE_BUDGETS.pop(user_id, None)
    try:
        category = categories[int(choice)]
    except (TypeError, ValueError, IndexError):
        if callback.message:
            await callback.message.edit_text("Esa opcion ya no es valida, usa /borrar de nuevo.")
        await callback.answer()
        return

    db.delete_budget(user_id, category)
    if callback.message:
        await callback.message.edit_text(f"🗑️ Listo, borre tu presupuesto de \"{category}\".")
    await callback.answer("Presupuesto borrado")


@dp.callback_query(F.data == "delmenu:goal")
async def cb_delmenu_goal(callback: CallbackQuery):
    user_id = callback.from_user.id
    goal = db.get_goal(user_id)
    if not goal:
        if callback.message:
            await callback.message.edit_text("No tienes una meta de ahorro definida.")
        await callback.answer()
        return

    currency = db.get_currency(user_id)
    aportado = db.get_goal_contributions_sum(user_id, goal["created_at"])
    para = f" para \"{goal['label']}\"" if goal["label"] else ""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="⚠️ Si, borrarla", callback_data="delgoal:confirm"),
            InlineKeyboardButton(text="Cancelar", callback_data="delcancel"),
        ]]
    )
    if callback.message:
        await callback.message.edit_text(
            f"¿Seguro que quieres borrar tu meta{para} de {goal['target_amount']:.2f} "
            f"{currency} (llevas aportado {aportado:.2f} {currency})? Tambien se borra "
            f"el historial de aportes.",
            reply_markup=keyboard,
        )
    await callback.answer()


@dp.callback_query(F.data == "delgoal:confirm")
async def cb_delgoal_confirm(callback: CallbackQuery):
    db.delete_goal_and_contributions(callback.from_user.id)
    if callback.message:
        await callback.message.edit_text("🗑️ Listo, borre tu meta de ahorro y tus aportes.")
    await callback.answer("Meta borrada")


@dp.callback_query(F.data == "delmenu:all")
async def cb_delmenu_all(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="⚠️ Si, borrar todo", callback_data="delall:confirm"),
            InlineKeyboardButton(text="Cancelar", callback_data="delcancel"),
        ]]
    )
    if callback.message:
        await callback.message.edit_text(
            "⚠️ Esto va a borrar TODOS tus registros, presupuestos y tu meta de "
            "ahorro (y sus aportes). No se puede deshacer. Tu moneda e idioma "
            "se mantienen.\n\n¿Seguro que quieres continuar?",
            reply_markup=keyboard,
        )
    await callback.answer()


@dp.message(Command("feedback", ignore_case=True))
async def cmd_feedback(message: Message, command: CommandObject):
    db.ensure_user(message.from_user.id, message.from_user.username)
    if not command.args:
        await message.answer(
            "Cuentame que esta pasando o que te gustaria que mejore. Ejemplo:\n"
            "/feedback la categoria de \"internet\" deberia ser servicios, no otros"
        )
        return

    text = command.args.strip()
    if ADMIN_TELEGRAM_ID:
        who = f"@{message.from_user.username}" if message.from_user.username else f"id {message.from_user.id}"
        try:
            await message.bot.send_message(
                ADMIN_TELEGRAM_ID,
                f"💬 Feedback de {who}:\n{text}",
            )
        except Exception as exc:
            logger.warning("No se pudo reenviar el feedback al admin: %s", exc)

    await message.answer("Gracias, se lo hice llegar a quien mantiene el bot. 🙌")


@dp.message(Command("admin", ignore_case=True))
async def cmd_admin(message: Message):
    if not ADMIN_TELEGRAM_ID or str(message.from_user.id) != str(ADMIN_TELEGRAM_ID):
        return  # comando oculto: no revela nada a quien no sea el admin
    today = dt.datetime.utcnow().date().isoformat()
    total_users = db.get_user_count()
    ai_today = db.get_total_ai_usage(today)

    active_subs = db.get_active_subscribers_count()
    total_payments = db.get_total_star_payments_count()
    total_stars = db.get_total_stars_revenue()
    # Formato con espacio, no .isoformat(): ver el comentario en _send_full_report.
    since_30d = (dt.datetime.utcnow() - dt.timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    stars_30d = db.get_stars_revenue_since(since_30d)

    lines = [
        "📊 Estado de Meow:",
        f"Usuarios registrados: {total_users}",
        f"Mensajes procesados con IA hoy: {ai_today}",
        f"Limite diario de IA por usuario: {AI_DAILY_LIMIT}",
        "",
        "⭐ Suscripciones:",
        f"Suscriptores activos ahora mismo: {active_subs}",
        f"Pagos con Stars recibidos en total: {total_payments}",
        f"Stars cobradas en total: {total_stars}",
        f"Stars cobradas en los ultimos 30 dias: {stars_30d}",
    ]

    recent = db.get_recent_star_payments(5)
    if recent:
        lines.append("\nUltimos pagos:")
        for row in recent:
            fecha = row["created_at"][:10]
            lines.append(f"  - {row['amount']} Stars el {fecha} (usuario {row['user_id']})")

    await message.answer("\n".join(lines))


async def _award(message: Message, user_id: int, code: str):
    """Otorga un logro si todavia no lo tenia, avisa y sube el animo de la mascota."""
    if not db.award_achievement(user_id, code):
        return
    db.adjust_pet_mood(user_id, 8)
    emoji, title, desc = ACHIEVEMENTS[code]
    await message.answer(f"🏅 ¡Nueva medalla! {emoji} {title}\n{desc}")


async def _check_registro_achievements(message: Message, user_id: int):
    n = db.get_transaction_count(user_id)
    if n == 1:
        await _award(message, user_id, "primer_registro")
    elif n == 10:
        await _award(message, user_id, "diez_registros")
    elif n == 50:
        await _award(message, user_id, "cincuenta_registros")


async def _check_goal_achievements(message: Message, user_id: int):
    goal = db.get_goal(user_id)
    if not goal:
        return
    aportado = db.get_goal_contributions_sum(user_id, goal["created_at"])
    if aportado > 0:
        await _award(message, user_id, "primer_aporte")
    if goal["target_amount"] and aportado >= goal["target_amount"]:
        await _award(message, user_id, "meta_cumplida")


@dp.message(Command("logros", ignore_case=True))
async def cmd_achievements(message: Message):
    db.ensure_user(message.from_user.id, message.from_user.username)
    earned_codes = {row["code"] for row in db.get_achievements(message.from_user.id)}

    lines = ["🏅 Tus medallas:\n"]
    for code, (emoji, title, desc) in ACHIEVEMENTS.items():
        if code in earned_codes:
            lines.append(f"{emoji} {title} — {desc}")
        else:
            lines.append(f"🔒 ??? — sigue usando el bot para desbloquearla")
    lines.append(f"\nLlevas {len(earned_codes)}/{len(ACHIEVEMENTS)} medallas.")
    await message.answer("\n".join(lines))


@dp.message(Command("mascota", ignore_case=True))
async def cmd_pet(message: Message):
    db.ensure_user(message.from_user.id, message.from_user.username)
    mood = db.get_pet_mood(message.from_user.id)

    if mood >= 85:
        emoji, texto = "😻", "¡Meow esta feliz y consentido! Sigue asi."
    elif mood >= 60:
        emoji, texto = "😺", "Meow esta bien y tranquilo."
    elif mood >= 40:
        emoji, texto = "😐", "Meow esta regular, ojo con los gastos de mas."
    elif mood >= 20:
        emoji, texto = "😿", "Meow esta un poco triste, se paso de presupuesto seguido."
    else:
        emoji, texto = "🤒", "Meow esta enfermito... hay que controlar los gastos urgente."

    barra_llena = "🟩" * (mood // 10)
    barra_vacia = "⬜" * (10 - mood // 10)
    await message.answer(
        f"{emoji} {texto}\n\nAnimo: {mood}/100\n{barra_llena}{barra_vacia}\n\n"
        "Sube cuando ahorras, cumples metas o te mantienes dentro de tu "
        "presupuesto; baja cuando te pasas de tus limites."
    )


# --- Suscripcion mensual (Telegram Stars) --------------------------------
#
# Cada gasto/ingreso/aporte cuenta como un registro. Los primeros
# FREE_TX_LIMIT son gratis; despues, el usuario puede seguir viendo todo
# (resumenes, presupuestos, meta) pero no anotar nada nuevo hasta pagar la
# suscripcion mensual con Telegram Stars, que Telegram renueva sola.

def _subscribe_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text=f"⭐ Suscribirme ({SUBSCRIPTION_STARS} Stars/mes)",
                callback_data="premium:subscribe",
            )
        ]]
    )


async def _check_and_block_limit(message: Message, user_id: int) -> bool:
    """Devuelve True si el usuario puede seguir registrando (sigue dentro de
    sus registros gratis o ya tiene la suscripcion activa). Si no puede, le
    avisa con el boton para suscribirse y devuelve False."""
    if db.is_premium(user_id):
        return True
    if db.get_transaction_count(user_id) < FREE_TX_LIMIT:
        return True
    await message.answer(
        f"Llegaste a tus {FREE_TX_LIMIT} registros gratis 🐾. Puedes seguir "
        "viendo tus resumenes, presupuestos y meta sin problema, pero para "
        "anotar nuevos gastos, ingresos o aportes necesitas la suscripcion "
        "mensual.",
        reply_markup=_subscribe_keyboard(),
    )
    return False


async def _maybe_warn_limit(message: Message, user_id: int):
    """Avisa una sola vez, a los FREE_TX_LIMIT - 10 registros, que se estan
    por acabar los registros gratis."""
    if db.is_premium(user_id):
        return
    count = db.get_transaction_count(user_id)
    if count == FREE_TX_LIMIT - 10:
        await message.answer(
            f"ℹ️ Te quedan 10 registros gratis (llevas {count}/{FREE_TX_LIMIT}). "
            "Usa /suscripcion para ver tus opciones y seguir sin limite cuando "
            "se acaben."
        )


@dp.message(Command("suscripcion", ignore_case=True))
async def cmd_subscription(message: Message):
    user_id = message.from_user.id
    db.ensure_user(user_id, message.from_user.username)

    if db.is_premium(user_id):
        expires_at = db.get_subscription_expiry(user_id)
        exp_dt = dt.datetime.fromisoformat(expires_at)
        await message.answer(
            f"⭐ Tu suscripcion esta activa hasta el {exp_dt.strftime('%d/%m/%Y')}.\n"
            "Telegram la renueva sola cada mes con tus Stars, no necesitas "
            "hacer nada."
        )
        return

    count = db.get_transaction_count(user_id)
    restantes = max(0, FREE_TX_LIMIT - count)
    if restantes > 0:
        estado = f"Llevas {count}/{FREE_TX_LIMIT} registros gratis (te quedan {restantes})."
    else:
        estado = f"Ya usaste tus {FREE_TX_LIMIT} registros gratis."

    await message.answer(
        f"{estado}\n\nCon la suscripcion mensual ({SUBSCRIPTION_STARS} Stars) "
        "tienes registros ilimitados, pagando directo con Telegram Stars "
        "(se renueva sola cada mes).",
        reply_markup=_subscribe_keyboard(),
    )


@dp.message(Command("sorteo", ignore_case=True))
async def cmd_sorteo(message: Message):
    user_id = message.from_user.id
    db.ensure_user(user_id, message.from_user.username)

    lifetime_count = db.get_registro_count_total(user_id)
    last_wins = db.get_last_win_timestamps()
    count = _eligible_registro_count(user_id, lifetime_count, last_wins)
    restantes = max(0, SORTEO_MIN_REGISTROS - count)
    has_won_before = user_id in last_wins

    now_utc = dt.datetime.utcnow()
    peru_now = now_utc + dt.timedelta(hours=PERU_UTC_OFFSET)
    if peru_now.month == 12:
        next_year, next_month = peru_now.year + 1, 1
    else:
        next_year, next_month = peru_now.year, peru_now.month + 1
    excluded_ids = db.get_recent_winner_ids(_recent_exclusion_month_keys(next_year, next_month))

    if user_id in excluded_ids:
        last_win = db.get_last_win_month(user_id)
        progreso = (
            f"🏆 Ganaste el sorteo de {last_win}, asi que quedas fuera de los "
            f"proximos sorteos por {SORTEO_EXCLUSION_MONTHS} meses. Ademas, para "
            "volver a participar vas a necesitar hacer de nuevo "
            f"{SORTEO_MIN_REGISTROS} registros NUEVOS desde esa fecha (el total "
            "que ya tenias antes de ganar ya no cuenta). Sigues usando el bot "
            "gratis igual que siempre, nada de esto se puede saltar pagando."
        )
    elif count >= SORTEO_MIN_REGISTROS:
        progreso = f"✅ Ya llevas {count} registros que califican: estas participando en el sorteo."
    elif has_won_before:
        progreso = (
            f"Ya paso tu exclusion, pero llevas {count}/{SORTEO_MIN_REGISTROS} "
            f"registros nuevos desde que ganaste (te faltan {restantes} para "
            "volver a entrar al sorteo)."
        )
    else:
        progreso = (
            f"Llevas {count}/{SORTEO_MIN_REGISTROS} registros en total "
            f"(te faltan {restantes} para entrar al sorteo)."
        )

    await message.answer(
        f"🎟️ Sorteo mensual de Meow\n\n"
        f"Cada mes sorteamos ${SORTEO_PRIZE_USD:.0f} entre quienes acumulen al menos "
        f"{SORTEO_MIN_REGISTROS} movimientos (gastos o ingresos) -- no hace falta "
        "lograrlo cada mes, es de por vida: una vez que llegas al minimo, sigues "
        "participando en todos los sorteos siguientes. Quien gana no puede volver "
        f"a ganar durante {SORTEO_EXCLUSION_MONTHS} meses, y ademas tiene que "
        f"volver a llegar a {SORTEO_MIN_REGISTROS} registros nuevos desde esa "
        "fecha para calificar otra vez. No hace falta pagar nada ni estar "
        "suscrito para nada de esto, solo usar el bot con regularidad.\n\n"
        f"{progreso}\n\n"
        "El sorteo se hace automaticamente el primer dia de cada mes. Si ganas, "
        "te contactamos para coordinar el premio."
    )


# --- Gastos/ingresos recurrentes ---

def _recurring_list_text(user_id: int, lang: str) -> str:
    rows = db.get_recurring(user_id)
    currency = db.get_currency(user_id)
    if not rows:
        return _t(
            lang,
            "No tienes gastos ni ingresos recurrentes configurados todavia.",
            "You don't have any recurring expenses or income set up yet.",
        )
    lines = [_t(lang, "Tus recurrentes (se registran solos cada mes):", "Your recurring items (logged automatically every month):")]
    for r in rows:
        etiqueta = r["label"] or r["category"]
        tipo = _t(lang, "gasto", "expense") if r["kind"] == "gasto" else _t(lang, "ingreso", "income")
        lines.append(
            f"  - #{r['id']} {etiqueta}: {r['amount']:.2f} {currency} ({tipo}, "
            f"{r['category']}, {_t(lang, 'dia', 'day')} {r['day_of_month']})"
        )
    return "\n".join(lines)


@dp.message(Command("recurrente", ignore_case=True))
async def cmd_recurring(message: Message, command: CommandObject):
    user_id = message.from_user.id
    db.ensure_user(user_id, message.from_user.username)
    lang = db.get_language(user_id)

    if command.args:
        # Atajo directo: /recurrente 800 servicios alquiler (gasto, dia de hoy).
        await _process_recurring_creation(message, user_id, "gasto", command.args)
        return

    text = _recurring_list_text(user_id, lang)
    rows = []
    for r in db.get_recurring(user_id):
        etiqueta = r["label"] or r["category"]
        rows.append([InlineKeyboardButton(
            text=_t(lang, f"🗑️ Borrar \"{etiqueta}\"", f"🗑️ Delete \"{etiqueta}\""),
            callback_data=f"recurdel:{r['id']}",
        )])
    rows.append([
        InlineKeyboardButton(text=_t(lang, "➕ Gasto recurrente", "➕ Recurring expense"), callback_data="recurmenu:add_gasto"),
        InlineKeyboardButton(text=_t(lang, "➕ Ingreso recurrente", "➕ Recurring income"), callback_data="recurmenu:add_ingreso"),
    ])
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    await message.answer(text, reply_markup=keyboard)


@dp.callback_query(F.data.startswith("recurmenu:"))
async def cb_recurmenu(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = db.get_language(user_id)
    choice = callback.data.split(":", 1)[1]

    if choice in ("add_gasto", "add_ingreso"):
        kind = "gasto" if choice == "add_gasto" else "ingreso"
        PENDING_RECURRING_INPUT[user_id] = kind
        today = (dt.datetime.utcnow() + dt.timedelta(hours=PERU_UTC_OFFSET)).day
        if callback.message:
            await callback.message.edit_text(_t(
                lang,
                f"Escribe: monto categoria descripcion (ej. \"800 servicios alquiler\"). "
                f"Se va a registrar solo, cada mes, el dia {today} (hoy).",
                f"Write: amount category description (e.g. \"800 utilities rent\"). "
                f"It will be logged automatically every month on day {today} (today).",
            ))
        await callback.answer()
        return

    await callback.answer()


@dp.callback_query(F.data.startswith("recurdel:"))
async def cb_recurdel(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = db.get_language(user_id)
    recurring_id = int(callback.data.split(":", 1)[1])
    deleted = db.deactivate_recurring(recurring_id, user_id)
    if callback.message:
        if deleted:
            await callback.message.edit_text(_t(lang, "Listo, lo borre. Ya no se va a registrar solo.", "Done, deleted. It won't be logged automatically anymore."))
        else:
            await callback.message.edit_text(_t(lang, "Ese recurrente ya no existe.", "That recurring item no longer exists."))
    await callback.answer()


async def _process_recurring_creation(message: Message, user_id: int, kind: str, args_text: str) -> bool:
    """Parsea "<monto> <categoria> [descripcion]" y crea el recurrente, con
    el dia de hoy (hora de Peru) como el dia del mes en que se va a repetir.
    Devuelve True si se guardo, False si hubo un error de formato (y ya se
    le aviso)."""
    lang = db.get_language(user_id)
    parts = args_text.strip().split(maxsplit=2)
    if len(parts) < 2:
        await message.answer(_t(
            lang,
            "Formato: monto categoria descripcion (ej. \"800 servicios alquiler\").",
            "Format: amount category description (e.g. \"800 utilities rent\").",
        ))
        return False

    raw_amount, category = parts[0], parts[1].strip().lower()
    label = parts[2].strip() if len(parts) > 2 else category
    try:
        amount = float(raw_amount.replace(",", "."))
    except ValueError:
        await message.answer(_t(
            lang,
            "El monto no es valido. Ejemplo: \"800 servicios alquiler\".",
            "That amount isn't valid. Example: \"800 utilities rent\".",
        ))
        return False
    if amount <= 0:
        await message.answer(_t(lang, "El monto debe ser mayor que cero.", "The amount must be greater than zero."))
        return False

    if category not in VALID_CATEGORIES:
        db.add_custom_category(user_id, category)

    today = (dt.datetime.utcnow() + dt.timedelta(hours=PERU_UTC_OFFSET)).day
    db.add_recurring(user_id, kind, amount, category, label, today)
    currency = db.get_currency(user_id)
    tipo = _t(lang, "gasto", "expense") if kind == "gasto" else _t(lang, "ingreso", "income")
    await message.answer(_t(
        lang,
        f"Listo, cree tu {tipo} recurrente \"{label}\" de {amount:.2f} {currency}. "
        f"Se va a registrar solo cada mes, el dia {today}. Usa /recurrente para verlo o borrarlo.",
        f"Done, I created your recurring {tipo} \"{label}\" of {amount:.2f} {currency}. "
        f"It'll be logged automatically every month on day {today}. Use /recurrente to view or delete it.",
    ))
    return True


# --- Registro de deudas (me deben / yo debo) ---

def _debts_summary_text(user_id: int, lang: str) -> str:
    totals = db.get_debts_totals(user_id)
    currency = db.get_currency(user_id)
    pending = db.get_pending_debts(user_id)

    lines = [_t(
        lang,
        f"Te deben en total: {totals['me_deben']:.2f} {currency}\nDebes en total: {totals['yo_debo']:.2f} {currency}",
        f"Owed to you: {totals['me_deben']:.2f} {currency}\nYou owe: {totals['yo_debo']:.2f} {currency}",
    )]

    if pending:
        lines.append("")
        lines.append(_t(lang, "Deudas pendientes:", "Pending debts:"))
        for d in pending:
            direccion = _t(lang, "me debe", "owes me") if d["direction"] == "me_deben" else _t(lang, "le debo", "I owe")
            desc = f" ({d['description']})" if d["description"] else ""
            lines.append(f"  - #{d['id']} {d['person']} {direccion} {d['amount']:.2f} {currency}{desc}")
    else:
        lines.append("")
        lines.append(_t(lang, "No tienes deudas pendientes.", "You don't have any pending debts."))

    return "\n".join(lines)


@dp.message(Command("deuda", ignore_case=True))
async def cmd_debt(message: Message):
    user_id = message.from_user.id
    db.ensure_user(user_id, message.from_user.username)
    lang = db.get_language(user_id)

    text = _debts_summary_text(user_id, lang)
    rows = []
    for d in db.get_pending_debts(user_id):
        rows.append([InlineKeyboardButton(
            text=_t(lang, f"✅ Marcar pagada #{d['id']} ({d['person']})", f"✅ Mark #{d['id']} settled ({d['person']})"),
            callback_data=f"deudapagar:{d['id']}",
        )])
    rows.append([
        InlineKeyboardButton(text=_t(lang, "➕ Me deben", "➕ Owed to me"), callback_data="deudatipo:me_deben"),
        InlineKeyboardButton(text=_t(lang, "➕ Yo debo", "➕ I owe"), callback_data="deudatipo:yo_debo"),
    ])
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    await message.answer(text, reply_markup=keyboard)


@dp.callback_query(F.data.startswith("deudatipo:"))
async def cb_deudatipo(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = db.get_language(user_id)
    direction = callback.data.split(":", 1)[1]
    PENDING_DEBT_INPUT[user_id] = direction
    if callback.message:
        await callback.message.edit_text(_t(
            lang,
            "Escribe: monto persona descripcion (ej. \"50 Juan almuerzo\"). "
            "La descripcion es opcional.",
            "Write: amount person description (e.g. \"50 John lunch\"). "
            "The description is optional.",
        ))
    await callback.answer()


@dp.callback_query(F.data.startswith("deudapagar:"))
async def cb_deudapagar(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = db.get_language(user_id)
    debt_id = int(callback.data.split(":", 1)[1])
    updated = db.mark_debt_paid(debt_id, user_id)
    if callback.message:
        if updated:
            await callback.message.edit_text(_t(lang, "Listo, la marque como pagada.", "Done, marked as settled."))
        else:
            await callback.message.edit_text(_t(lang, "Esa deuda ya no esta pendiente.", "That debt is no longer pending."))
    await callback.answer()


async def _process_debt_creation(message: Message, user_id: int, direction: str, args_text: str) -> bool:
    """Parsea "<monto> <persona> [descripcion]" y anota la deuda. Devuelve
    True si se guardo, False si hubo un error de formato (y ya se le aviso)."""
    lang = db.get_language(user_id)
    parts = args_text.strip().split(maxsplit=2)
    if len(parts) < 2:
        await message.answer(_t(
            lang,
            "Formato: monto persona descripcion (ej. \"50 Juan almuerzo\").",
            "Format: amount person description (e.g. \"50 John lunch\").",
        ))
        return False

    raw_amount, person = parts[0], parts[1].strip()
    description = parts[2].strip() if len(parts) > 2 else ""
    try:
        amount = float(raw_amount.replace(",", "."))
    except ValueError:
        await message.answer(_t(lang, "El monto no es valido. Ejemplo: \"50 Juan almuerzo\".", "That amount isn't valid. Example: \"50 John lunch\"."))
        return False
    if amount <= 0:
        await message.answer(_t(lang, "El monto debe ser mayor que cero.", "The amount must be greater than zero."))
        return False

    db.add_debt(user_id, direction, person, amount, description)
    currency = db.get_currency(user_id)
    if direction == "me_deben":
        await message.answer(_t(
            lang,
            f"Listo, anote que {person} te debe {amount:.2f} {currency}. Usa /deuda para verlo o marcarlo pagado.",
            f"Done, noted that {person} owes you {amount:.2f} {currency}. Use /deuda to view or mark it settled.",
        ))
    else:
        await message.answer(_t(
            lang,
            f"Listo, anote que le debes {amount:.2f} {currency} a {person}. Usa /deuda para verlo o marcarlo pagado.",
            f"Done, noted that you owe {person} {amount:.2f} {currency}. Use /deuda to view or mark it settled.",
        ))
    return True


@dp.callback_query(F.data == "premium:subscribe")
async def cb_premium_subscribe(callback: CallbackQuery):
    link = await callback.bot.create_invoice_link(
        title="Suscripcion mensual Meow",
        description=(
            "Registros ilimitados en Meow durante 30 dias. Se renueva "
            "automaticamente cada mes con tus Telegram Stars."
        ),
        payload=SUBSCRIPTION_PAYLOAD,
        currency="XTR",
        prices=[LabeledPrice(label="Suscripcion mensual", amount=SUBSCRIPTION_STARS)],
        subscription_period=SUBSCRIPTION_PERIOD_SECONDS,
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=f"⭐ Pagar {SUBSCRIPTION_STARS} Stars", url=link)
        ]]
    )
    if callback.message:
        await callback.message.answer(
            "Toca el boton para completar el pago con Telegram Stars:",
            reply_markup=keyboard,
        )
    await callback.answer()


@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@dp.message(F.successful_payment)
async def process_successful_payment(message: Message):
    sp = message.successful_payment
    user_id = message.from_user.id
    db.ensure_user(user_id, message.from_user.username)

    exp_ts = getattr(sp, "subscription_expiration_date", None)
    if exp_ts:
        expires_at = dt.datetime.utcfromtimestamp(exp_ts).isoformat()
    else:
        expires_at = (dt.datetime.utcnow() + dt.timedelta(days=30)).isoformat()

    db.set_subscription(user_id, expires_at, sp.telegram_payment_charge_id)
    db.log_star_payment(user_id, sp.total_amount, sp.telegram_payment_charge_id)
    exp_dt = dt.datetime.fromisoformat(expires_at)
    await message.answer(
        f"⭐ ¡Gracias por suscribirte! Tu suscripcion esta activa hasta el "
        f"{exp_dt.strftime('%d/%m/%Y')} y se renueva sola cada mes con tus "
        "Stars. Ya puedes seguir registrando sin limite."
    )


async def _check_budget_alert(message: Message, user_id: int, category: str):
    budgets = {b["category"]: b["limit_amount"] for b in db.get_budgets(user_id)}
    limit_amount = budgets.get(category)
    if limit_amount is None:
        return

    spent = db.get_month_spent(user_id, category)
    currency = db.get_currency(user_id)
    ratio = spent / limit_amount if limit_amount > 0 else 0

    if spent > limit_amount:
        db.adjust_pet_mood(user_id, -10)
        await message.answer(
            f"Ojo: superaste tu presupuesto mensual de \"{category}\" "
            f"({spent:.2f} / {limit_amount:.2f} {currency})."
        )
        return

    if ratio >= 0.8:
        db.adjust_pet_mood(user_id, -5)
        await message.answer(
            f"Aviso: ya usaste el {ratio * 100:.0f}% de tu presupuesto mensual de "
            f"\"{category}\" ({spent:.2f} / {limit_amount:.2f} {currency})."
        )
        return

    # Alerta predictiva: si sigues gastando a este ritmo, ¿cuando se acaba el
    # presupuesto? Solo tiene sentido avisar antes de llegar al 80%.
    now = dt.datetime.utcnow()
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    days_elapsed = max(now.day, 1)
    daily_rate = spent / days_elapsed
    if daily_rate <= 0:
        return
    projected_total = daily_rate * days_in_month
    if projected_total <= limit_amount:
        return

    day_it_runs_out = int(limit_amount / daily_rate) + 1
    if day_it_runs_out > days_in_month:
        return
    db.adjust_pet_mood(user_id, -3)
    await message.answer(
        f"📉 Segun tu ritmo de gasto en \"{category}\" ({spent:.2f} {currency} "
        f"en {days_elapsed} dias), si sigues asi te vas a quedar sin presupuesto "
        f"el dia {day_it_runs_out} de este mes."
    )


def _confirm_keyboard(tx_id: int, kind: str) -> InlineKeyboardMarkup:
    flip_label = "↔️ Era un ingreso" if kind == "gasto" else "↔️ Era un gasto"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Si, esta bien", callback_data=f"catok:{tx_id}"),
                InlineKeyboardButton(text="🔄 Cambiar categoria", callback_data=f"catno:{tx_id}"),
            ],
            [InlineKeyboardButton(text=flip_label, callback_data=f"flipkind:{tx_id}")],
        ]
    )


@dp.message(F.text)
async def handle_text(message: Message):
    db.ensure_user(message.from_user.id, message.from_user.username)
    user_id = message.from_user.id

    lang = db.get_language(user_id)

    pending_summary = PENDING_SUMMARY_INPUT.pop(user_id, None)
    if pending_summary == "date":
        parsed = _parse_report_date(message.text)
        if not parsed:
            await message.answer(_t(
                lang,
                "No pude leer esa fecha. Escribela como AAAA-MM-DD, ej. 2026-09-20.",
                "I couldn't read that date. Write it as YYYY-MM-DD, e.g. 2026-09-20.",
            ))
            PENDING_SUMMARY_INPUT[user_id] = "date"
            return
        start = dt.datetime(parsed.year, parsed.month, parsed.day)
        end = start + dt.timedelta(days=1)
        label = _t(lang, f"el {parsed.isoformat()}", f"{parsed.isoformat()}")
        await _send_full_report(message, user_id, start, end, label)
        return

    if pending_summary == "range":
        parsed = _parse_report_range(message.text)
        if not parsed:
            await message.answer(_t(
                lang,
                "No pude leer ese rango. Escribelo como \"2026-09-01 al 2026-09-24\".",
                "I couldn't read that range. Write it as \"2026-09-01 to 2026-09-24\".",
            ))
            PENDING_SUMMARY_INPUT[user_id] = "range"
            return
        d1, d2 = parsed
        start = dt.datetime(d1.year, d1.month, d1.day)
        end = dt.datetime(d2.year, d2.month, d2.day) + dt.timedelta(days=1)
        label = _t(lang, f"del {d1.isoformat()} al {d2.isoformat()}", f"{d1.isoformat()} to {d2.isoformat()}")
        await _send_full_report(message, user_id, start, end, label)
        return

    pending_budget = PENDING_BUDGET_INPUT.pop(user_id, None)
    if pending_budget:
        ok = await _process_budget_creation(message, user_id, message.text)
        if not ok:
            PENDING_BUDGET_INPUT[user_id] = True
        return

    pending_budget_category = PENDING_BUDGET_AMOUNT.pop(user_id, None)
    if pending_budget_category is not None:
        ok = await _process_budget_amount(message, user_id, pending_budget_category, message.text)
        if not ok:
            PENDING_BUDGET_AMOUNT[user_id] = pending_budget_category
        return

    pending_goal = PENDING_GOAL_INPUT.pop(user_id, None)
    if pending_goal == "aportar":
        if db.get_goal(user_id) is None:
            await message.answer("Ya no tienes una meta de ahorro activa. Usa /meta para crear una.")
            return
        ok = await _process_contribution(message, user_id, message.text)
        if not ok:
            PENDING_GOAL_INPUT[user_id] = "aportar"
        return

    if pending_goal == "crear":
        ok = await _process_goal_creation(message, user_id, message.text)
        if not ok:
            PENDING_GOAL_INPUT[user_id] = "crear"
        return

    pending_tx_id = PENDING_CUSTOM_CATEGORY.pop(user_id, None)
    if pending_tx_id is not None:
        category = message.text.strip().lower()
        if not category:
            await message.answer("Ese nombre no es valido, intenta de nuevo.")
            PENDING_CUSTOM_CATEGORY[user_id] = pending_tx_id
            return
        db.update_transaction_category(pending_tx_id, category)
        note = ""
        if category not in VALID_CATEGORIES:
            db.add_custom_category(user_id, category)
            note = " La agregue a tu lista de categorias para la proxima vez."
        await message.answer(f"Listo, lo cambie a la categoria \"{category}\".{note}")
        budgets = {b["category"]: b["limit_amount"] for b in db.get_budgets(user_id)}
        if category in budgets:
            await _check_budget_alert(message, user_id, category)
        return

    pending_recurring = PENDING_RECURRING_INPUT.pop(user_id, None)
    if pending_recurring is not None:
        ok = await _process_recurring_creation(message, user_id, pending_recurring, message.text)
        if not ok:
            PENDING_RECURRING_INPUT[user_id] = pending_recurring
        return

    pending_debt = PENDING_DEBT_INPUT.pop(user_id, None)
    if pending_debt is not None:
        ok = await _process_debt_creation(message, user_id, pending_debt, message.text)
        if not ok:
            PENDING_DEBT_INPUT[user_id] = pending_debt
        return

    today = dt.datetime.utcnow().date().isoformat()

    usage_before = db.get_ai_usage_count(user_id, today)
    allow_ai = usage_before < AI_DAILY_LIMIT
    result, used_ai = parse_message(message.text, allow_ai=allow_ai)
    if used_ai:
        db.increment_ai_usage(user_id, today)

    if result is None:
        await message.answer(
            "No encontre un monto en tu mensaje. Intenta algo como "
            "\"gaste 50 en el mercado\" o \"ingreso 300\"."
        )
        return

    kind, amount, category = result
    if not await _check_and_block_limit(message, user_id):
        return
    tx_id = db.add_transaction(user_id, kind, amount, category, message.text)
    currency = db.get_currency(user_id)

    verbo = "Registre un ingreso" if kind == "ingreso" else "Registre un gasto"
    await message.answer(
        f"{verbo} de {amount:.2f} {currency} en la categoria \"{category}\". "
        f"¿Esta bien? (usa /resumen para ver tus totales)",
        reply_markup=_confirm_keyboard(tx_id, kind),
    )

    if not allow_ai and usage_before == AI_DAILY_LIMIT:
        await message.answer(
            f"ℹ️ Hoy ya usaste tus {AI_DAILY_LIMIT} registros analizados con IA, "
            "asi que por ahora sigo funcionando con un analisis mas simple "
            "por palabras clave (un poco menos preciso). Manana vuelve a "
            "tener el cupo completo."
        )

    if kind == "gasto":
        await _check_budget_alert(message, user_id, category)
    else:
        db.adjust_pet_mood(user_id, 3)

    await _check_registro_achievements(message, user_id)
    await _maybe_warn_limit(message, user_id)


@dp.callback_query(F.data.startswith("catok:"))
async def cb_category_ok(callback: CallbackQuery):
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Gracias, anotado.")


@dp.callback_query(F.data.startswith("catno:"))
async def cb_category_no(callback: CallbackQuery):
    tx_id = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    rows = _category_list_rows(user_id, lambda c: f"setcat:{tx_id}:{c}")
    rows.append([InlineKeyboardButton(text="✏️ Otra categoria", callback_data=f"catother:{tx_id}")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    if callback.message:
        await callback.message.edit_text("¿En cual categoria deberia ir?", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data.startswith("catother:"))
async def cb_category_other(callback: CallbackQuery):
    tx_id = int(callback.data.split(":", 1)[1])
    PENDING_CUSTOM_CATEGORY[callback.from_user.id] = tx_id
    if callback.message:
        await callback.message.edit_text(
            "Escribeme el nombre de la categoria que quieres usar (ej. "
            "\"curso de gastronomia\")."
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("setcat:"))
async def cb_category_set(callback: CallbackQuery):
    _, tx_id, category = callback.data.split(":", 2)
    db.update_transaction_category(int(tx_id), category)

    if callback.message:
        await callback.message.edit_text(f"Listo, lo cambie a la categoria \"{category}\".")
    await callback.answer("Categoria actualizada")

    if callback.message:
        user_id = callback.from_user.id
        budgets = {b["category"]: b["limit_amount"] for b in db.get_budgets(user_id)}
        if category in budgets:
            await _check_budget_alert(callback.message, user_id, category)


@dp.callback_query(F.data.startswith("flipkind:"))
async def cb_flip_kind(callback: CallbackQuery):
    tx_id = int(callback.data.split(":", 1)[1])
    tx = db.get_transaction(tx_id)
    if tx is None:
        await callback.answer("Ese registro ya no existe.")
        return

    new_kind = "ingreso" if tx["kind"] == "gasto" else "gasto"
    db.update_transaction_kind(tx_id, new_kind)

    if callback.message:
        etiqueta = "ingreso" if new_kind == "ingreso" else "gasto"
        await callback.message.edit_text(
            f"Listo, lo cambie a {etiqueta} de {tx['amount']:.2f} en \"{tx['category']}\"."
        )
    await callback.answer("Tipo actualizado")

    if callback.message and new_kind == "gasto":
        await _check_budget_alert(callback.message, callback.from_user.id, tx["category"])


def _seconds_until_next_weekly_report() -> float:
    """Domingos 8pm hora de Peru (UTC-5), para el resumen semanal automatico."""
    now_utc = dt.datetime.utcnow()
    peru_now = now_utc + dt.timedelta(hours=PERU_UTC_OFFSET)
    days_ahead = (6 - peru_now.weekday()) % 7  # lunes=0 ... domingo=6
    target_peru = peru_now.replace(hour=20, minute=0, second=0, microsecond=0) + dt.timedelta(days=days_ahead)
    if target_peru <= peru_now:
        target_peru += dt.timedelta(days=7)
    target_utc = target_peru - dt.timedelta(hours=PERU_UTC_OFFSET)
    return max((target_utc - now_utc).total_seconds(), 60)


async def weekly_summary_task(bot: Bot):
    """Manda, sin que lo pidan, un resumen semanal a cada usuario activo."""
    while True:
        try:
            await asyncio.sleep(_seconds_until_next_weekly_report())
            for user_id in db.get_all_user_ids():
                try:
                    summary = db.get_summary(user_id, "semana")
                    if summary["total_ingresos"] == 0 and summary["total_gastos"] == 0:
                        continue
                    currency = db.get_currency(user_id)
                    lines = [
                        "📅 Tu resumen semanal:",
                        f"Ingresos: {summary['total_ingresos']:.2f} {currency}",
                        f"Gastos: {summary['total_gastos']:.2f} {currency}",
                        f"Balance: {summary['balance']:.2f} {currency}",
                        "\nEscribe /resumen para ver el detalle completo (categorias, presupuestos y tu meta).",
                    ]
                    await bot.send_message(user_id, "\n".join(lines))
                except Exception as exc:
                    logger.warning("No se pudo enviar resumen semanal a %s: %s", user_id, exc)
        except Exception as exc:
            logger.warning("Fallo el ciclo de resumen semanal, reintento en 1 hora: %s", exc)
            await asyncio.sleep(3600)


def _seconds_until_next_month_start() -> float:
    """Dia 1 de cada mes a las 00:05 hora de Peru, para correr el sorteo."""
    now_utc = dt.datetime.utcnow()
    peru_now = now_utc + dt.timedelta(hours=PERU_UTC_OFFSET)
    if peru_now.month == 12:
        next_month_start = dt.datetime(peru_now.year + 1, 1, 1, 0, 5)
    else:
        next_month_start = dt.datetime(peru_now.year, peru_now.month + 1, 1, 0, 5)
    target_utc = next_month_start - dt.timedelta(hours=PERU_UTC_OFFSET)
    return max((target_utc - now_utc).total_seconds(), 60)


def _month_key_offset(year: int, month: int, offset: int) -> str:
    """month_key de `offset` meses antes de (year, month). offset=1 es el
    mes inmediatamente anterior, offset=2 el anterior a ese, etc."""
    total = year * 12 + (month - 1) - offset
    y, m = divmod(total, 12)
    return f"{y:04d}-{m + 1:02d}"


def _recent_exclusion_month_keys(year: int, month: int) -> list[str]:
    """Los month_key de los ultimos SORTEO_EXCLUSION_MONTHS meses antes de
    (year, month) -- quien gano en cualquiera de esos meses queda excluido
    del sorteo de (year, month)."""
    return [_month_key_offset(year, month, i) for i in range(1, SORTEO_EXCLUSION_MONTHS + 1)]


def _eligible_registro_count(user_id: int, lifetime_n: int, last_wins: dict[int, str]) -> int:
    """Cuantos registros cuentan para calificar al sorteo: el total de
    siempre, salvo que el usuario ya haya ganado antes -- en ese caso solo
    cuentan los registros hechos DESPUES de esa victoria, asi que tiene que
    volver a llegar a SORTEO_MIN_REGISTROS desde cero para participar de
    nuevo (no le alcanza con el total que ya tenia acumulado antes de
    ganar)."""
    last_win = last_wins.get(user_id)
    if last_win is None:
        return lifetime_n
    return db.get_registro_count_since_win(user_id, last_win)


async def _run_monthly_sorteo(bot: Bot):
    """Sortea SORTEO_PRIZE_USD entre quienes acumularon SORTEO_MIN_REGISTROS
    registros (de por vida, no se reinicia cada mes -- salvo que ya hayan
    ganado antes, en cuyo caso el conteo se reinicia desde su ultima
    victoria y tienen que volver a llegar al minimo con registros nuevos),
    excluyendo ademas a quien haya ganado en los ultimos
    SORTEO_EXCLUSION_MONTHS meses. Es dinero de quien administra el bot, no
    un pozo de otros usuarios, y no hace falta pagar nada para participar ni
    para saltarse ninguna de las dos condiciones. Solo le avisa al admin, en
    privado; el pago se coordina fuera del bot."""
    now_utc = dt.datetime.utcnow()
    peru_now = now_utc + dt.timedelta(hours=PERU_UTC_OFFSET)
    month_key = f"{peru_now.year:04d}-{peru_now.month:02d}"

    if db.has_sorteo_run(month_key):
        return

    excluded_ids = db.get_recent_winner_ids(_recent_exclusion_month_keys(peru_now.year, peru_now.month))
    last_wins = db.get_last_win_timestamps()
    counts = db.get_registro_counts_total()
    eligible = []
    for c in counts:
        if c["user_id"] in excluded_ids:
            continue
        n = _eligible_registro_count(c["user_id"], c["n"], last_wins)
        if n >= SORTEO_MIN_REGISTROS:
            eligible.append({"user_id": c["user_id"], "n": n})

    if not eligible:
        db.record_sorteo_run(month_key, None, None, None)
        if ADMIN_TELEGRAM_ID:
            try:
                await bot.send_message(
                    int(ADMIN_TELEGRAM_ID),
                    f"🎟️ Sorteo de {month_key}: no hubo ganador (nadie llego a los "
                    f"{SORTEO_MIN_REGISTROS} registros minimos, o los unicos que "
                    "calificaban estan excluidos por haber ganado hace poco).",
                )
            except Exception as exc:
                logger.warning("No se pudo avisar al admin del sorteo (%s): %s", month_key, exc)
        return

    winner = random.choice(eligible)
    winner_id = winner["user_id"]
    username = db.get_username(winner_id)
    db.record_sorteo_run(month_key, winner_id, username, winner["n"])

    if ADMIN_TELEGRAM_ID:
        handle = f"@{username}" if username else f"id {winner_id}"
        try:
            await bot.send_message(
                int(ADMIN_TELEGRAM_ID),
                f"🎉 Sorteo de {month_key}: gano {handle} con {winner['n']} registros "
                f"que califican. Coordina con esa persona el pago de ${SORTEO_PRIZE_USD:.0f}.",
            )
        except Exception as exc:
            logger.warning("No se pudo avisar al admin del sorteo (%s): %s", month_key, exc)


async def monthly_sorteo_task(bot: Bot):
    """Cada 1 de mes, sortea $50 entre quienes acumularon SORTEO_MIN_REGISTROS
    registros (gratis o suscritos, no hace falta pagar para participar). El
    conteo no se reinicia cada mes -- salvo para quien ya gano antes, a
    quien se le reinicia desde su ultima victoria. Solo le avisa al admin en
    privado; el pago se coordina fuera del bot."""
    while True:
        try:
            await asyncio.sleep(_seconds_until_next_month_start())
            await _run_monthly_sorteo(bot)
        except Exception as exc:
            logger.warning("Fallo el ciclo del sorteo mensual, reintento en 1 hora: %s", exc)
            await asyncio.sleep(3600)


def _seconds_until_next_daily_check() -> float:
    """Todos los dias a las RECURRING_CHECK_HOUR (hora de Peru), para aplicar
    los gastos/ingresos recurrentes que le tocan a cada usuario ese dia."""
    now_utc = dt.datetime.utcnow()
    peru_now = now_utc + dt.timedelta(hours=PERU_UTC_OFFSET)
    target_peru = peru_now.replace(hour=RECURRING_CHECK_HOUR, minute=0, second=0, microsecond=0)
    if target_peru <= peru_now:
        target_peru += dt.timedelta(days=1)
    target_utc = target_peru - dt.timedelta(hours=PERU_UTC_OFFSET)
    return max((target_utc - now_utc).total_seconds(), 60)


async def _apply_due_recurring(bot: Bot):
    """Registra automaticamente cada gasto/ingreso recurrente que le toca al
    dia de hoy (hora de Peru) y todavia no se aplico este mes."""
    now_utc = dt.datetime.utcnow()
    peru_now = now_utc + dt.timedelta(hours=PERU_UTC_OFFSET)
    month_key = f"{peru_now.year:04d}-{peru_now.month:02d}"
    last_day = calendar.monthrange(peru_now.year, peru_now.month)[1]

    for rule in db.get_due_recurring(peru_now.day, last_day, month_key):
        db.add_transaction(
            rule["user_id"], rule["kind"], rule["amount"], rule["category"],
            f"[recurrente] {rule['label'] or rule['category']}",
        )
        db.set_recurring_last_run(rule["id"], month_key)
        try:
            lang = db.get_language(rule["user_id"])
            currency = db.get_currency(rule["user_id"])
            etiqueta = rule["label"] or rule["category"]
            tipo = _t(lang, "gasto", "expense") if rule["kind"] == "gasto" else _t(lang, "ingreso", "income")
            await bot.send_message(rule["user_id"], _t(
                lang,
                f"🔁 Registre tu {tipo} recurrente \"{etiqueta}\" de {rule['amount']:.2f} {currency}.",
                f"🔁 Logged your recurring {tipo} \"{etiqueta}\" of {rule['amount']:.2f} {currency}.",
            ))
        except Exception as exc:
            logger.warning("No se pudo avisar el recurrente %s al usuario %s: %s", rule["id"], rule["user_id"], exc)


async def recurring_task(bot: Bot):
    """Cada dia, a la hora fijada, aplica los gastos/ingresos recurrentes que
    correspondan (ver _apply_due_recurring)."""
    while True:
        try:
            await asyncio.sleep(_seconds_until_next_daily_check())
            await _apply_due_recurring(bot)
        except Exception as exc:
            logger.warning("Fallo el ciclo de recurrentes, reintento en 1 hora: %s", exc)
            await asyncio.sleep(3600)


BOT_DESCRIPTION = (
    "🐾 ¡Hola! Soy Meow 💰✨ Te ayudo a controlar tus finanzas personales sin "
    "hojas de calculo ni apps complicadas. Solo cuentame que gastaste o "
    "recibiste, como si le hablaras a un amigo 💬🐱.\n\n"
    "Tambien te ayudo a poner presupuestos por categoria, definir una meta "
    "de ahorro con aportes reales, ver resumenes completos por periodo, y "
    "te doy medallas 🏅 por tus buenos habitos."
)
BOT_SHORT_DESCRIPTION = "Tu asistente de finanzas: gastos, presupuestos, metas de ahorro y mas 💰🐱"


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Falta BOT_TOKEN en el archivo .env")

    db.init_db()
    bot = Bot(token=BOT_TOKEN)
    await bot.set_my_commands(BOT_COMMANDS)
    try:
        await bot.set_my_description(BOT_DESCRIPTION)
        await bot.set_my_short_description(BOT_SHORT_DESCRIPTION)
    except Exception as exc:
        logger.warning("No se pudo actualizar la descripcion del bot: %s", exc)
    asyncio.create_task(weekly_summary_task(bot))
    asyncio.create_task(monthly_sorteo_task(bot))
    asyncio.create_task(recurring_task(bot))
    logger.info("Finzo esta corriendo...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
