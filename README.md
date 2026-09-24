# Finzo — bot de Telegram para finanzas personales (MVP)

## Que hace ahora mismo

- Recibe mensajes en lenguaje natural (español o inglés) como "gaste 50 en el mercado" o "spent $20 on transport" y los guarda como gasto o ingreso.
- Categoriza automáticamente por palabras clave (comida, transporte, servicios, salud, entretenimiento, trabajo/negocio, otros).
- `/resumen semana` o `/resumen mes` — totales de ingresos, gastos, balance y desglose por categoría.
- `/moneda PEN` (o USD, MXN, EUR, etc.) — cada usuario define su propia moneda.
- Todo se guarda en un archivo SQLite local (`finzo.db`), sin depender de servicios externos de pago.

## Cómo correrlo en tu computadora

1. Asegúrate de tener Python 3.10 o superior instalado.
2. Abre una terminal en esta carpeta y crea un entorno virtual (recomendado):
   ```
   python -m venv venv
   venv\Scripts\activate        (Windows)
   source venv/bin/activate     (Mac/Linux)
   ```
3. Instala las dependencias:
   ```
   pip install -r requirements.txt
   ```
4. El archivo `.env` ya tiene tu token de Finzo cargado. No lo compartas ni lo subas a GitHub — si alguna vez sospechas que se filtró, ve a @BotFather y usa `/revoke` para generar uno nuevo.
5. Corre el bot:
   ```
   python bot.py
   ```
6. Abre Telegram, busca `@myfinzo_bot` y envíale `/start`.

Mientras esta terminal esté abierta y corriendo, el bot responde. Para dejarlo funcionando todo el tiempo sin tener tu compu prendida, el siguiente paso es subirlo a un servidor pequeño (Railway o Render tienen planes gratuitos para empezar).

## Qué falta para el plan completo (ver el documento de planificación)

- Reemplazar el parser por reglas con una llamada a un modelo de IA, para entender frases más variadas.
- Alertas de presupuesto por categoría.
- Exportar historial a Excel/Google Sheets.
- Cobro de la versión premium (Telegram Stars / Stripe).
- Reconocimiento de recibos por foto (OCR).

Cada uno de estos se puede agregar sin rehacer lo que ya está — el `parser.py` y `database.py` están separados justamente para poder mejorarlos por partes.
