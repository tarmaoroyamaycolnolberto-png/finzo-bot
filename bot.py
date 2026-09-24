"""Finzo: bot de Telegram para finanzas personales (MVP).

Comandos:
  /start               - registra al usuario y explica como usarlo
  /moneda USD          - define la moneda principal del usuario
  /resumen semana      - resumen de los ultimos 7 dias
  /resumen mes         - resumen de los ultimos 30 dias
  /presupuesto         - ver tus limites de gasto por categoria
  /presupuesto X 200   - definir un limite mensual de 200 para la categoria X
  /exportar            - descargar todo tu historial en un archivo Excel
  /ayuda               - vuelve a mostrar las instrucciones

Cualquier otro mensaje de texto se interpreta como un registro de gasto o
ingreso, ej: "gaste 50 en el mercado" o "spent $20 on groceries".
"""

import asyncio
import io
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message
from dotenv import load_dotenv

# Debe cargarse ANTES de importar parser: ese modulo lee ANTHROPIC_API_KEY
# apenas se importa, asi que si el .env no esta cargado todavia, no la ve.
load_dotenv()

import database as db
from parser import parse_message

BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("finzo")

dp = Dispatcher()

WELCOME = (
    "Hola, soy Finzo. Te ayudo a llevar el control de tus gastos e ingresos "
    "sin salir de Telegram.\n\n"
    "Solo escribeme lo que gastaste o recibiste, en tus propias palabras:\n"
    "  - \"gaste 50 en el mercado\"\n"
    "  - \"me pagaron 300\"\n"
    "  - \"spent $20 on transport\"\n\n"
    "Comandos utiles:\n"
    "/resumen semana - tus totales de los ultimos 7 dias\n"
    "/resumen mes - tus totales de los ultimos 30 dias\n"
    "/moneda USD - define tu moneda (ej. PEN, USD, MXN, EUR)\n"
    "/presupuesto comida 200 - define un limite mensual para una categoria\n"
    "/presupuesto - ver tus limites actuales\n"
    "/exportar - descarga todo tu historial en un archivo Excel\n"
    "/ayuda - vuelve a mostrar este mensaje"
)

VALID_CATEGORIES = [
    "comida", "transporte", "servicios", "salud",
    "entretenimiento", "trabajo/negocio", "otros",
]


@dp.message(Command("start"))
async def cmd_start(message: Message):
    db.ensure_user(message.from_user.id, message.from_user.username)
    await message.answer(WELCOME)


@dp.message(Command("ayuda"))
async def cmd_help(message: Message):
    await message.answer(WELCOME)


@dp.message(Command("moneda"))
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


@dp.message(Command("resumen"))
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


@dp.message(Command("presupuesto"))
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
        for row in budgets:
            spent = db.get_month_spent(message.from_user.id, row["category"])
            lines.append(f"  - {row['category']}: {spent:.2f} / {row['limit_amount']:.2f}")
        await message.answer("\n".join(lines))
        return

    parts = command.args.strip().rsplit(" ", 1)
    if len(parts) != 2:
        await message.answer(
            "Formato: /presupuesto categoria monto (ej. \"/presupuesto comida 200\")."
        )
        return

    category, raw_amount = parts[0].strip().lower(), parts[1].strip()
    if category not in VALID_CATEGORIES:
        await message.answer(
            "Categoria no reconocida. Usa una de: " + ", ".join(VALID_CATEGORIES)
        )
        return
    try:
        limit_amount = float(raw_amount.replace(",", "."))
    except ValueError:
        await message.answer("El monto no es valido. Ejemplo: \"/presupuesto comida 200\".")
        return

    db.set_budget(message.from_user.id, category, limit_amount)
    await message.answer(
        f"Listo, tu limite mensual para \"{category}\" es {limit_amount:.2f} {currency}."
    )


@dp.message(Command("exportar"))
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


async def _check_budget_alert(message: Message, user_id: int, category: str):
    budgets = {b["category"]: b["limit_amount"] for b in db.get_budgets(user_id)}
    limit_amount = budgets.get(category)
    if limit_amount is None:
        return

    spent = db.get_month_spent(user_id, category)
    currency = db.get_currency(user_id)
    ratio = spent / limit_amount if limit_amount > 0 else 0

    if spent > limit_amount:
        await message.answer(
            f"Ojo: superaste tu presupuesto mensual de \"{category}\" "
            f"({spent:.2f} / {limit_amount:.2f} {currency})."
        )
    elif ratio >= 0.8:
        await message.answer(
            f"Aviso: ya usaste el {ratio * 100:.0f}% de tu presupuesto mensual de "
            f"\"{category}\" ({spent:.2f} / {limit_amount:.2f} {currency})."
        )


@dp.message(F.text)
async def handle_text(message: Message):
    db.ensure_user(message.from_user.id, message.from_user.username)
    result = parse_message(message.text)

    if result is None:
        await message.answer(
            "No encontre un monto en tu mensaje. Intenta algo como "
            "\"gaste 50 en el mercado\" o \"ingreso 300\"."
        )
        return

    kind, amount, category = result
    db.add_transaction(message.from_user.id, kind, amount, category, message.text)
    currency = db.get_currency(message.from_user.id)

    verbo = "Registre un ingreso" if kind == "ingreso" else "Registre un gasto"
    await message.answer(
        f"{verbo} de {amount:.2f} {currency} en la categoria \"{category}\". "
        f"Usa /resumen semana para ver tus totales."
    )

    if kind == "gasto":
        await _check_budget_alert(message, message.from_user.id, category)


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Falta BOT_TOKEN en el archivo .env")

    db.init_db()
    bot = Bot(token=BOT_TOKEN)
    logger.info("Finzo esta corriendo...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
