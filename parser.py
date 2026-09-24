"""Interpreta mensajes en lenguaje natural (ES/EN) y los convierte en una transaccion.

Usa Claude (Anthropic) para entender el mensaje con contexto real, y cae de
vuelta a un analisis por palabras clave si no hay API key configurada o si la
llamada a la IA falla por cualquier motivo (sin internet, clave invalida, etc.)
para que el bot nunca se quede sin responder.
"""

import json
import logging
import os
import re

logger = logging.getLogger("finzo.parser")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-latest")

_client = None
if ANTHROPIC_API_KEY:
    try:
        from anthropic import Anthropic

        _client = Anthropic(api_key=ANTHROPIC_API_KEY)
    except Exception:
        _client = None

VALID_CATEGORIES = [
    "comida", "transporte", "servicios", "salud",
    "entretenimiento", "trabajo/negocio", "otros",
]

SYSTEM_PROMPT = (
    "Interpretas mensajes de un usuario sobre sus finanzas personales, en "
    "espanol o ingles. Responde UNICAMENTE con un JSON valido, sin texto "
    "adicional, con esta forma exacta:\n"
    '{"kind": "gasto" o "ingreso", "amount": numero, "category": una de '
    + json.dumps(VALID_CATEGORIES) + "}\n"
    "Si el mensaje no describe un gasto o ingreso con un monto, responde "
    '{"kind": null, "amount": null, "category": null}.'
)

INCOME_KEYWORDS = [
    "ingreso", "ingrese", "me pagaron", "cobre", "recibi", "gane",
    "income", "received", "earned", "got paid", "paid me",
]

CATEGORY_KEYWORDS = {
    "comida": ["mercado", "comida", "restaurante", "almuerzo", "cena", "delivery",
               "food", "lunch", "dinner", "groceries", "supermarket"],
    "transporte": ["taxi", "uber", "pasaje", "gasolina", "combustible", "bus",
                   "transport", "gas", "fuel"],
    "servicios": ["luz", "agua", "internet", "telefono", "celular", "netflix",
                  "utilities", "phone", "wifi", "subscription"],
    "salud": ["farmacia", "medico", "doctor", "medicina", "pharmacy", "health",
              "medicine"],
    "entretenimiento": ["cine", "juego", "salida", "bar", "fiesta", "movie",
                         "entertainment", "game", "party"],
    "trabajo/negocio": ["proveedor", "insumo", "mercaderia", "sueldo", "planilla",
                         "supplier", "inventory", "payroll"],
}

# Acepta 50, 50.5, 50,50, $50, S/50, 50 soles, 20 dollars, etc.
AMOUNT_RE = re.compile(r"(?:[a-zA-Z$/]*\s*)?(\d+(?:[.,]\d{1,2})?)")


def _has_word(text: str, keyword: str) -> bool:
    """True si `keyword` aparece como palabra completa (no como sub-palabra:
    'gas' no debe encender con 'gaste')."""
    return re.search(r"\b" + re.escape(keyword) + r"\b", text) is not None


def _detect_kind(text: str) -> str:
    lowered = text.lower()
    for kw in INCOME_KEYWORDS:
        if _has_word(lowered, kw):
            return "ingreso"
    return "gasto"


def _detect_category(text: str) -> str:
    lowered = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if _has_word(lowered, kw):
                return category
    return "otros"


def parse_message_rules(text: str):
    """Analisis por palabras clave (sin IA). Devuelve (kind, amount, category) o None."""
    match = AMOUNT_RE.search(text)
    if not match:
        return None

    raw_amount = match.group(1).replace(",", ".")
    try:
        amount = float(raw_amount)
    except ValueError:
        return None

    if amount <= 0:
        return None

    kind = _detect_kind(text)
    category = _detect_category(text)
    return kind, amount, category


def parse_message_ai(text: str):
    """Analisis con Claude. Devuelve (kind, amount, category), o None si el
    mensaje no describe una transaccion, o lanza una excepcion si la llamada
    a la API falla (para que quien la use decida caer al modo por reglas)."""
    response = _client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    raw = response.content[0].text.strip()

    # Por si el modelo agrega algo de texto alrededor del JSON.
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Respuesta sin JSON: {raw}")
    data = json.loads(raw[start:end + 1])

    if not data.get("kind") or data.get("amount") is None:
        return None

    kind = data["kind"]
    amount = float(data["amount"])
    category = data.get("category") or "otros"
    if category not in VALID_CATEGORIES:
        category = "otros"
    if amount <= 0:
        return None

    return kind, amount, category


def parse_message(text: str):
    """Punto de entrada que usa el bot: IA si esta disponible, si no, reglas."""
    if _client is not None:
        try:
            return parse_message_ai(text)
        except Exception as exc:
            # Sin internet, clave invalida, limite de uso, etc.: no se cae el bot,
            # pero se avisa en la terminal para poder diagnosticar la causa.
            logger.warning("Fallo la IA, usando reglas de respaldo: %s", exc)
            return parse_message_rules(text)
    else:
        logger.warning("ANTHROPIC_API_KEY no configurada o cliente no inicializado; usando reglas.")
    return parse_message_rules(text)
