import logging
import os
import time
import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, filters
)

# 🔐 Configuración
TOKEN = os.getenv("TELEGRAM_TOKEN")
URL = "https://geoportalgasolineras.es/rest/geoportalgasolineras/ListaPrecioGasolinerasSinGalp"

# 🧠 Cache de datos
gasolineras_cache = None
ultimo_update = 0
CACHE_TIEMPO = 6 * 60 * 60  # 6 horas

# 🤖 Configurar logs
logging.basicConfig(level=logging.INFO)

# 🟦 Estados de la conversación
ESPERANDO_CIUDAD = range(1)

# 📦 Descargar y cachear datos
def actualizar_cache():
    global gasolineras_cache, ultimo_update
    headers = {"User-Agent": "Mozilla/5.0 (TelegramGasBot/1.0)"}
    try:
        r = requests.get(URL, headers=headers, timeout=10)
        if r.status_code == 200:
            gasolineras_cache = r.json().get("ListaEESSPrecio", [])
            ultimo_update = time.time()
            print("✅ Datos actualizados")
        else:
            print(f"⚠️ Error HTTP: {r.status_code}")
    except Exception as e:
        print("❌ Excepción al obtener datos:", e)

# 🔍 Obtener top 3
def obtener_top_3(ciudad):
    global gasolineras_cache, ultimo_update
    if gasolineras_cache is None or time.time() - ultimo_update > CACHE_TIEMPO:
        actualizar_cache()
    if gasolineras_cache is None:
        return None, "Error al obtener datos."

    ciudad = ciudad.strip().lower()
    filtradas = []

    for g in gasolineras_cache:
        try:
            if ciudad in g["Municipio"].lower():
                diesel = float(g["Precio Gasoleo A"].replace(",", "."))
                gasolina = float(g["Precio Gasolina 95 E5"].replace(",", "."))
                g["diesel"] = diesel
                g["gasolina"] = gasolina
                filtradas.append(g)
        except:
            continue

    if not filtradas:
        return None, "No se encontraron gasolineras en esa ciudad."

    top_diesel = sorted(filtradas, key=lambda x: x["diesel"])[:3]
    top_gasolina = sorted(filtradas, key=lambda x: x["gasolina"])[:3]

    return (top_diesel, top_gasolina), None

# 🟩 /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 ¡Bienvenido al Bot de Gasolineras!\n\n"
        "Puedes usar estos comandos:\n"
        "• /precio – Ver el top 3 de gasolineras más baratas\n"
        "• /cancelar – Cancelar la consulta actual"
    )

# ⛽ /precio
async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📍 Escribe el nombre de la ciudad o pueblo:")
    return ESPERANDO_CIUDAD

# 📍 Recibir ciudad
async def recibir_ciudad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ciudad = update.message.text
    resultado, error = obtener_top_3(ciudad)

    if error:
        await update.message.reply_text(f"⚠️ {error}")
        return ConversationHandler.END

    top_diesel, top_gasolina = resultado
    msg = f"⛽ *Top 3 Diésel en {ciudad.title()}*\n"
    for g in top_diesel:
        msg += f"• {g['Rótulo']} - {g['diesel']} €\n  📍 {g['Dirección']}\n"

    msg += f"\n⛽ *Top 3 Gasolina 95 en {ciudad.title()}*\n"
    for g in top_gasolina:
        msg += f"• {g['Rótulo']} - {g['gasolina']} €\n  📍 {g['Dirección']}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")
    return ConversationHandler.END

# 🚫 /cancelar
async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Consulta cancelada.")
    return ConversationHandler.END

# 🚀 Main
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("precio", precio)],
        states={ESPERANDO_CIUDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_ciudad)]},
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    # 🟢 Ejecutar por webhook (Railway)
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # ej. https://tuapp.up.railway.app/
    print("🧷 Webhook:", f"{WEBHOOK_URL}{TOKEN}")
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        url_path=TOKEN,
        webhook_url=f"{WEBHOOK_URL}{TOKEN}",
    )
