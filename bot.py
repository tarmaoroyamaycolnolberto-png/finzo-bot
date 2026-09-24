"""Finzo: bot de Telegram para finanzas personales (MVP).

Comandos:
  /start            - registra al usuario y explica como usarlo
  /moneda USD       - define la moneda principal del usuario
  /resumen semana   - resumen de los ultimos 7 dias
  /resumen mes      - resumen de los ultimos 30 dias
  /ayuda            - vuelve a mostrar las instrucciones

Cualquier otro mensaje de texto se interpreta como un registro de gasto o
ingreso, ej: "gaste 50 en el mercado" o "spent $20 on groceries".
"""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from dotenv import load_dotenv

import database as db
from parser import parse_message

load_dotenv()
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
    "/ayuda - vuelve a mostrar este mensaje"
)


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


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Falta BOT_TOKEN en el archivo .env")

    db.init_db()
    bot = Bot(token=BOT_TOKEN)
    logger.info("Finzo esta corriendo...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
