"""Meow (ex-Finzo): bot de Telegram para finanzas personales.

Comandos:
  /start               - registra al usuario (pide moneda si es nuevo)
  /moneda USD          - define la moneda principal del usuario
  /resumen semana      - resumen de los ultimos 7 dias (con grafico)
  /resumen mes         - resumen de los ultimos 30 dias (con grafico)
  /categorias          - ve las categorias que se formaron segun tus registros
  /presupuesto         - ver tus limites de gasto por categoria
  /presupuesto X 200   - definir un limite mensual de 200 para la categoria X
  /meta 500            - definir o ver tu meta de ahorro
  /aportar 50          - sumar un aporte hacia tu meta de ahorro
  /exportar            - descargar todo tu historial en un archivo Excel
  /borrar              - menu para borrar: ultimo registro, presupuestos,
                         meta de ahorro o todo el historial (con confirmacion)
  /logros              - ve tus medallas ganadas
  /mascota             - revisa el animo de Meow (tamagotchi financiero)
  /reto                - recibe/revisa un reto de ahorro personalizado
  /feedback            - mandale un comentario o reporte a quien mantiene el bot
  /idioma es|en        - elegir idioma (afecta el mensaje de bienvenida)
  /ayuda               - vuelve a mostrar las instrucciones

Cualquier otro mensaje de texto se interpreta como un registro de gasto o
ingreso, ej: "gaste 50 en el mercado" o "spent $20 on groceries". Como la
categoria la decide una IA, despues de cada registro el bot pregunta si
esta bien; si no, deja elegir la correcta o cambiar el tipo con botones.

Para controlar el costo de la IA cuando hay muchos usuarios, cada usuario
tiene una cuota diaria de mensajes analizados con IA (AI_DAILY_LIMIT); al
superarla, el bot sigue funcionando con un analisis por palabras clave.
"""

import asyncio
import calendar
import datetime as dt
import io
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
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
    "/resumen semana - 📅 tus totales de los ultimos 7 dias (con grafico)\n"
    "/resumen mes - 🗓️ tus totales de los ultimos 30 dias\n"
    "/moneda USD - 💱 define tu moneda (ej. PEN, USD, MXN, EUR)\n"
    "/categorias - 🏷️ ve las categorias que se formaron segun tus registros\n"
    "/presupuesto comida 200 - 🎯 define un limite mensual para una categoria "
    "(puede ser libre, ej. \"curso de gastronomia\")\n"
    "/presupuesto - 📊 ver tus limites actuales\n"
    "/meta 500 viaje a Cusco - 🐷 define tu meta de ahorro y para que es\n"
    "/aportar 50 - 💰 suma un aporte a tu meta de ahorro\n"
    "/exportar - 📥 descarga todo tu historial en un archivo Excel\n"
    "/borrar - 🗑️ elige que borrar: tu ultimo registro, presupuestos, tu "
    "meta o todo tu historial (siempre te pido confirmar antes)\n"
    "/logros - 🏅 ve las medallas que has ganado\n"
    "/mascota - 🐱 revisa el animo de Meow (sube si ahorras, baja si te pasas)\n"
    "/reto - 🔥 recibe un reto de ahorro personalizado de 5 dias\n"
    "/feedback - 💬 mandame un comentario o reporte un problema\n"
    "/idioma en - 🌐 cambia el idioma (es/en)\n"
    "/ayuda - ❓ vuelve a mostrar este mensaje\n\n"
    "🤖 La categoria de cada registro la decide una IA. Por eso, despues de "
    "cada uno te voy a preguntar si esta bien; si marcas que no, te dejo "
    "elegir la categoria correcta o cambiar el tipo (gasto/ingreso) con "
    "botones 👇."
)

WELCOME_EN = (
    "🐱 Hi, I'm Meow 💰 I help you keep track of your expenses and income "
    "right inside Telegram.\n\n"
    "Just tell me what you spent or received, in your own words ✍️:\n"
    "  - \"spent 50 on groceries\"\n"
    "  - \"got paid 300\"\n"
    "  - \"gaste 20 en el almuerzo\"\n\n"
    "📋 Useful commands:\n"
    "/resumen semana - 📅 your totals for the last 7 days (with a chart)\n"
    "/resumen mes - 🗓️ your totals for the last 30 days\n"
    "/moneda USD - 💱 set your currency (e.g. PEN, USD, MXN, EUR)\n"
    "/categorias - 🏷️ see the categories that formed from your own habits\n"
    "/presupuesto comida 200 - 🎯 set a monthly limit for a category (can be "
    "a free label, e.g. \"cooking course\")\n"
    "/presupuesto - 📊 view your current limits\n"
    "/meta 500 trip to Cusco - 🐷 set your savings goal and what it's for\n"
    "/aportar 50 - 💰 log a contribution toward your savings goal\n"
    "/exportar - 📥 download your full history as an Excel file\n"
    "/borrar - 🗑️ pick what to delete: your last entry, budgets, your "
    "goal, or all your data (always asks to confirm first)\n"
    "/logros - 🏅 see the achievements you've earned\n"
    "/mascota - 🐱 check Meow's mood (goes up when you save, down when you overspend)\n"
    "/reto - 🔥 get a personalized 5-day savings challenge\n"
    "/feedback - 💬 send a comment or report a problem\n"
    "/idioma es - 🌐 switch language (es/en)\n"
    "/ayuda - ❓ show this message again\n\n"
    "🤖 The category for each entry is chosen by AI. That's why, after each "
    "one, I'll ask if it looks right; if not, I'll let you pick the correct "
    "category or flip the type (expense/income) with buttons 👇.\n\n"
    "(Note: some replies, like /resumen or /presupuesto, are still in "
    "Spanish for now — full English support is on the way.)"
)

BOT_COMMANDS = [
    BotCommand(command="start", description="Registrarte y ver la intro"),
    BotCommand(command="resumen", description="Resumen semana o mes"),
    BotCommand(command="moneda", description="Definir tu moneda"),
    BotCommand(command="categorias", description="Ver tus categorias segun tus habitos"),
    BotCommand(command="presupuesto", description="Ver o definir limites mensuales"),
    BotCommand(command="meta", description="Definir o ver tu meta de ahorro"),
    BotCommand(command="aportar", description="Sumar un aporte a tu meta de ahorro"),
    BotCommand(command="exportar", description="Descargar tu historial en Excel"),
    BotCommand(command="borrar", description="Elegir que borrar (registro, presupuestos, meta o todo)"),
    BotCommand(command="logros", description="Ver tus medallas"),
    BotCommand(command="mascota", description="Ver el animo de Meow"),
    BotCommand(command="reto", description="Recibir o revisar un reto de ahorro"),
    BotCommand(command="feedback", description="Enviar un comentario o reportar un problema"),
    BotCommand(command="idioma", description="Cambiar idioma (es/en)"),
    BotCommand(command="ayuda", description="Ver los comandos disponibles"),
]

VALID_CATEGORIES = [
    "comida", "transporte", "servicios", "salud",
    "entretenimiento", "trabajo/negocio", "otros",
]

CATEGORY_LABELS = {
    "comida": "Comida",
    "transporte": "Transporte",
    "servicios": "Servicios",
    "salud": "Salud",
    "entretenimiento": "Entretenimiento",
    "trabajo/negocio": "Trabajo/Negocio",
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
    "otros": "#4a3aa7",
}

CURRENCY_OPTIONS = ["PEN", "USD", "MXN", "EUR", "COP", "ARS"]

# user_id -> tx_id: cuando el usuario eligio "Otra categoria" y le toca
# escribir el nombre en su proximo mensaje (en vez de que se interprete
# como un nuevo registro de gasto/ingreso).
PENDING_CUSTOM_CATEGORY: dict[int, int] = {}

# codigo -> (emoji, titulo, descripcion)
ACHIEVEMENTS = {
    "primer_registro": ("🥇", "Primer paso", "Registraste tu primer movimiento."),
    "diez_registros": ("🔟", "Constancia", "Ya llevas 10 movimientos registrados."),
    "cincuenta_registros": ("💯", "Veterano/a", "Llevas 50 movimientos registrados."),
    "primer_aporte": ("🌱", "Primer aporte", "Hiciste tu primer aporte hacia tu meta de ahorro."),
    "meta_cumplida": ("🏆", "¡Meta cumplida!", "Llegaste al 100% de tu meta de ahorro."),
    "presupuesto_bajo_control": ("🛡️", "Bajo control", "Ninguno de tus presupuestos esta pasado de su limite."),
    "reto_superado": ("🔥", "Reto superado", "Cumpliste un reto de ahorro de principio a fin."),
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


@dp.message(Command("resumen", ignore_case=True))
async def cmd_summary(message: Message, command: CommandObject):
    db.ensure_user(message.from_user.id, message.from_user.username)
    period = "semana"
    if command.args and "mes" in command.args.lower():
        period = "mes"

    summary = db.get_summary(message.from_user.id, period)
    currency = db.get_currency(message.from_user.id)
    etiqueta = "ultimos 7 dias" if period == "semana" else "ultimos 30 dias"

    lines = [f"Resumen ({etiqueta}) en {currency}:"]
    lines.append(f"Ingresos: {summary['total_ingresos']:.2f}")
    lines.append(f"Gastos: {summary['total_gastos']:.2f}")
    lines.append(f"Balance: {summary['balance']:.2f}")

    if summary["gastos_por_categoria"]:
        lines.append("\nGastos por categoria:")
        for row in summary["gastos_por_categoria"]:
            lines.append(f"  - {row['category']}: {row['total']:.2f} ({row['n']} registros)")

    if not summary["gastos_por_categoria"] and not summary["ingresos_por_categoria"]:
        lines.append("\nTodavia no registras nada en este periodo. Escribeme algo como \"gaste 20 en almuerzo\".")

    await message.answer("\n".join(lines))

    try:
        chart_buffer = _build_category_chart(summary["gastos_por_categoria"], currency)
        if chart_buffer:
            photo = BufferedInputFile(chart_buffer.read(), filename="resumen.png")
            await message.answer_photo(photo, caption="📊 Gastos por categoria")
    except Exception as exc:
        logger.warning("No se pudo generar el grafico de resumen: %s", exc)


@dp.message(Command("categorias", ignore_case=True))
async def cmd_categories(message: Message):
    db.ensure_user(message.from_user.id, message.from_user.username)
    rows = db.get_categories_summary(message.from_user.id)
    currency = db.get_currency(message.from_user.id)

    if not rows:
        await message.answer(
            "Todavia no tienes categorias propias: se van formando segun lo "
            "que registres. Prueba escribiendo algo como \"gaste 20 en almuerzo\"."
        )
        return

    gastos = [r for r in rows if r["kind"] == "gasto"]
    ingresos = [r for r in rows if r["kind"] == "ingreso"]

    lines = ["Estas son tus categorias, segun como has usado el bot:"]
    if gastos:
        lines.append("\nGastos:")
        for r in gastos:
            lines.append(f"  - {r['category']}: {r['total']:.2f} {currency} ({r['n']} registros)")
    if ingresos:
        lines.append("\nIngresos:")
        for r in ingresos:
            lines.append(f"  - {r['category']}: {r['total']:.2f} {currency} ({r['n']} registros)")

    lines.append(
        "\nSi alguna vez te pregunto y marcas que una categoria no esta bien, "
        "la corrijo y asi esta lista refleja mejor tus habitos reales."
    )
    await message.answer("\n".join(lines))


@dp.message(Command("presupuesto", ignore_case=True))
async def cmd_budget(message: Message, command: CommandObject):
    db.ensure_user(message.from_user.id, message.from_user.username)
    currency = db.get_currency(message.from_user.id)

    if not command.args:
        budgets = db.get_budgets(message.from_user.id)
        if not budgets:
            await message.answer(
                "No tienes presupuestos definidos todavia. Usa algo como "
                "\"/presupuesto comida 200\" para poner un limite mensual."
            )
            return
        lines = [f"Tus presupuestos mensuales ({currency}):"]
        all_under_control = True
        for row in budgets:
            spent = db.get_month_spent(message.from_user.id, row["category"])
            if spent > row["limit_amount"]:
                all_under_control = False
            lines.append(f"  - {row['category']}: {spent:.2f} / {row['limit_amount']:.2f}")
        await message.answer("\n".join(lines))
        if all_under_control:
            await _award(message, message.from_user.id, "presupuesto_bajo_control")
        return

    parts = command.args.strip().rsplit(" ", 1)
    if len(parts) != 2:
        await message.answer(
            "Formato: /presupuesto categoria monto (ej. \"/presupuesto comida 200\" o "
            "\"/presupuesto curso de gastronomia 8000\")."
        )
        return

    category, raw_amount = parts[0].strip().lower(), parts[1].strip()
    if not category:
        await message.answer("Falta el nombre de la categoria. Ejemplo: \"/presupuesto comida 200\".")
        return
    try:
        limit_amount = float(raw_amount.replace(",", "."))
    except ValueError:
        await message.answer("El monto no es valido. Ejemplo: \"/presupuesto comida 200\".")
        return

    db.set_budget(message.from_user.id, category, limit_amount)
    note = ""
    if category not in VALID_CATEGORIES:
        note = (
            "\n\nComo \"{}\" no es una de las categorias que uso para clasificar tus "
            "gastos automaticamente, este limite solo va a sumar los gastos que tu "
            "asignes manualmente a esa categoria (con el boton \"Otra categoria\" "
            "cuando registres uno)."
        ).format(category)
    await message.answer(
        f"Listo, tu limite mensual para \"{category}\" es {limit_amount:.2f} {currency}.{note}"
    )


@dp.message(Command("meta", ignore_case=True))
async def cmd_goal(message: Message, command: CommandObject):
    db.ensure_user(message.from_user.id, message.from_user.username)
    currency = db.get_currency(message.from_user.id)

    if not command.args:
        goal = db.get_goal(message.from_user.id)
        if not goal:
            await message.answer(
                "No tienes una meta de ahorro todavia. Usa \"/meta 500 viaje a "
                "Cusco\" para definir cuanto quieres ahorrar y para que "
                "(la descripcion es opcional)."
            )
            return
        aportado = db.get_goal_contributions_sum(message.from_user.id, goal["created_at"])
        target = goal["target_amount"]
        label = goal["label"]
        pct = (aportado / target * 100) if target else 0
        pct = max(0, min(100, pct))
        para = f" para \"{label}\"" if label else ""
        await message.answer(
            f"🐷 Tu meta{para} es ahorrar {target:.2f} {currency}.\n"
            f"Llevas aportado {aportado:.2f} {currency} ({pct:.0f}%). Usa "
            f"\"/aportar 50\" para sumar a tu meta cuando apartes algo.\n"
            f"Usa \"/meta {target:.0f}{' ' + label if label else ''}\" de nuevo "
            f"para reiniciarla."
        )
        return

    parts = command.args.strip().split(maxsplit=1)
    try:
        target_amount = float(parts[0].replace(",", "."))
    except ValueError:
        await message.answer(
            "Formato: /meta 500 viaje a Cusco (la descripcion despues del "
            "monto es opcional)."
        )
        return

    if target_amount <= 0:
        await message.answer("El monto debe ser mayor que cero.")
        return

    label = parts[1].strip() if len(parts) > 1 else None
    db.set_goal(message.from_user.id, target_amount, label)
    para = f" para \"{label}\"" if label else ""
    await message.answer(
        f"🐷 Meta guardada: ahorrar {target_amount:.2f} {currency}{para}. Usa "
        f"\"/aportar 50\" cada vez que apartes algo, y te ire mostrando tu "
        f"avance con /meta."
    )


@dp.message(Command("aportar", ignore_case=True))
async def cmd_contribute(message: Message, command: CommandObject):
    db.ensure_user(message.from_user.id, message.from_user.username)
    currency = db.get_currency(message.from_user.id)
    goal = db.get_goal(message.from_user.id)

    if not goal:
        await message.answer(
            "Todavia no tienes una meta de ahorro. Usa \"/meta 500 viaje a "
            "Cusco\" para crear una primero."
        )
        return

    if not command.args:
        await message.answer("¿Cuanto quieres aportar? Ejemplo: /aportar 50")
        return

    try:
        amount = float(command.args.strip().split()[0].replace(",", "."))
    except ValueError:
        await message.answer("Monto invalido. Ejemplo: /aportar 50")
        return

    if amount <= 0:
        await message.answer("El monto debe ser mayor que cero.")
        return

    db.add_goal_contribution(message.from_user.id, amount)
    aportado = db.get_goal_contributions_sum(message.from_user.id, goal["created_at"])
    target = goal["target_amount"]
    label = goal["label"]
    pct = max(0, min(100, (aportado / target * 100) if target else 0))
    para = f" para \"{label}\"" if label else ""
    await message.answer(
        f"💰 Aporte registrado: {amount:.2f} {currency}.\n"
        f"Llevas {aportado:.2f} / {target:.2f} {currency} ({pct:.0f}%){para}."
    )
    await _check_goal_achievements(message, message.from_user.id)


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
    await message.answer(
        "📊 Estado de Meow:\n"
        f"Usuarios registrados: {total_users}\n"
        f"Mensajes procesados con IA hoy: {ai_today}\n"
        f"Limite diario de IA por usuario: {AI_DAILY_LIMIT}"
    )


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


@dp.message(Command("reto", ignore_case=True))
async def cmd_challenge(message: Message):
    db.ensure_user(message.from_user.id, message.from_user.username)
    user_id = message.from_user.id
    currency = db.get_currency(user_id)
    challenge = db.get_challenge(user_id)

    if challenge and not challenge["resolved"]:
        if not challenge["accepted"]:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Acepto el reto", callback_data="reto:si"),
                    InlineKeyboardButton(text="❌ Ahora no", callback_data="reto:no"),
                ]]
            )
            await message.answer(
                f"Ya te habia propuesto un reto de $0 en \"{challenge['category']}\". "
                "¿Lo aceptas?",
                reply_markup=keyboard,
            )
            return

        now_iso = dt.datetime.utcnow().isoformat()
        if now_iso < challenge["ends_at"]:
            spent = db.get_category_spent_since(user_id, challenge["category"], challenge["started_at"])
            if spent > 0:
                await message.answer(
                    f"😿 Vas a mitad de tu reto de \"{challenge['category']}\" y ya "
                    f"gastaste {spent:.2f} {currency} ahi. ¡Todavia puedes recuperarte!"
                )
            else:
                await message.answer(
                    f"🔥 Vas perfecto en tu reto de $0 en \"{challenge['category']}\": "
                    f"0.00 {currency} gastados hasta ahora. ¡Sigue asi!"
                )
            return

        spent = db.get_category_spent_since(user_id, challenge["category"], challenge["started_at"])
        db.resolve_challenge(user_id)
        if spent <= 0:
            db.adjust_pet_mood(user_id, 10)
            await message.answer(
                f"🎉 ¡Reto superado! No gastaste nada en \"{challenge['category']}\" "
                "durante 5 dias."
            )
            await _award(message, user_id, "reto_superado")
        else:
            await message.answer(
                f"El reto en \"{challenge['category']}\" ya termino: gastaste "
                f"{spent:.2f} {currency} ahi. ¡La proxima lo logras! Usa /reto "
                "para un nuevo desafio."
            )
        return

    top = db.get_top_expense_category(user_id, days=30)
    if not top:
        await message.answer(
            "Todavia no tengo suficientes gastos tuyos para proponerte un reto. "
            "Registra algunos movimientos y vuelve a intentar con /reto."
        )
        return

    category = top["category"]
    ends_at = (dt.datetime.utcnow() + dt.timedelta(days=5)).isoformat()
    db.propose_challenge(user_id, category, ends_at)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Acepto el reto", callback_data="reto:si"),
            InlineKeyboardButton(text="❌ Ahora no", callback_data="reto:no"),
        ]]
    )
    await message.answer(
        f"He notado que gastas bastante en \"{category}\" 👀. ¿Aceptas el reto de "
        f"gastar $0 en \"{category}\" los proximos 5 dias?",
        reply_markup=keyboard,
    )


@dp.callback_query(F.data == "reto:si")
async def cb_challenge_accept(callback: CallbackQuery):
    db.accept_challenge(callback.from_user.id)
    if callback.message:
        await callback.message.edit_text(
            "💪 ¡Reto aceptado! Te voy a estar avisando cuando uses /reto de "
            "nuevo. En 5 dias vemos como te fue."
        )
    await callback.answer("Reto aceptado")


@dp.callback_query(F.data == "reto:no")
async def cb_challenge_decline(callback: CallbackQuery):
    db.resolve_challenge(callback.from_user.id)
    if callback.message:
        await callback.message.edit_text("Sin problema, no acepte el reto. Puedes pedir otro con /reto cuando quieras.")
    await callback.answer()


@dp.message(F.text)
async def handle_text(message: Message):
    db.ensure_user(message.from_user.id, message.from_user.username)
    user_id = message.from_user.id

    pending_tx_id = PENDING_CUSTOM_CATEGORY.pop(user_id, None)
    if pending_tx_id is not None:
        category = message.text.strip().lower()
        if not category:
            await message.answer("Ese nombre no es valido, intenta de nuevo.")
            PENDING_CUSTOM_CATEGORY[user_id] = pending_tx_id
            return
        db.update_transaction_category(pending_tx_id, category)
        await message.answer(f"Listo, lo cambie a la categoria \"{category}\".")
        budgets = {b["category"]: b["limit_amount"] for b in db.get_budgets(user_id)}
        if category in budgets:
            await _check_budget_alert(message, user_id, category)
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
    tx_id = db.add_transaction(user_id, kind, amount, category, message.text)
    currency = db.get_currency(user_id)

    verbo = "Registre un ingreso" if kind == "ingreso" else "Registre un gasto"
    await message.answer(
        f"{verbo} de {amount:.2f} {currency} en la categoria \"{category}\". "
        f"¿Esta bien? (usa /resumen semana para ver tus totales)",
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


@dp.callback_query(F.data.startswith("catok:"))
async def cb_category_ok(callback: CallbackQuery):
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Gracias, anotado.")


@dp.callback_query(F.data.startswith("catno:"))
async def cb_category_no(callback: CallbackQuery):
    tx_id = callback.data.split(":", 1)[1]
    buttons = [
        InlineKeyboardButton(text=CATEGORY_LABELS[c], callback_data=f"setcat:{tx_id}:{c}")
        for c in VALID_CATEGORIES
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
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
                        "\nEscribe /resumen semana para ver el detalle por categoria.",
                    ]
                    await bot.send_message(user_id, "\n".join(lines))
                except Exception as exc:
                    logger.warning("No se pudo enviar resumen semanal a %s: %s", user_id, exc)
        except Exception as exc:
            logger.warning("Fallo el ciclo de resumen semanal, reintento en 1 hora: %s", exc)
            await asyncio.sleep(3600)


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Falta BOT_TOKEN en el archivo .env")

    db.init_db()
    bot = Bot(token=BOT_TOKEN)
    await bot.set_my_commands(BOT_COMMANDS)
    asyncio.create_task(weekly_summary_task(bot))
    logger.info("Finzo esta corriendo...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
