from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes
)
import requests
import os

# Estados para la conversación
PEDIR_CIUDAD = 1

# URL del Ministerio
URL = "https://geoportalgasolineras.es/rest/geoportalgasolineras/ListaPrecioGasolinerasSinGalp"

# Función que obtiene el top 3 de gasolineras por ciudad
def obtener_top_3(ciudad: str):
    try:
        res = requests.get(URL, timeout=10)
        data = res.json()

        if "ListaEESSPrecio" not in data:
            return None, "Error en la respuesta del servidor."

        gasolineras = data["ListaEESSPrecio"]
        ciudad = ciudad.lower()

        filtradas = [
            g for g in gasolineras
            if ciudad in g["Municipio"].lower()
            and g["Precio Gasoleo A"].strip() != ""
            and g["Precio Gasolina 95 E5"].strip() != ""
        ]

        for g in filtradas:
            g["precio_diesel"] = float(g["Precio Gasoleo A"].replace(",", "."))
            g["precio_gasolina"] = float(g["Precio Gasolina 95 E5"].replace(",", "."))

        top = sorted(filtradas, key=lambda x: (x["precio_diesel"] + x["precio_gasolina"]) / 2)[:3]
        return top, None
    except Exception as e:
        return None, str(e)

# /start: inicia la conversación preguntando ciudad
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 ¡Hola! ¿De qué ciudad o pueblo quieres saber el precio del combustible?")
    return PEDIR_CIUDAD

# Usuario responde con ciudad
async def recibir_ciudad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ciudad = update.message.text
    top, error = obtener_top_3(ciudad)

    if error:
        await update.message.reply_text(f"⚠️ Error al consultar precios: {error}")
    elif not top:
        await update.message.reply_text(f"❌ No se encontraron resultados para '{ciudad}'. Prueba con otra localidad.")
    else:
        mensaje = f"⛽ Top 3 en {ciudad.title()}:\n\n"
        for g in top:
            mensaje += (
                f"🏷️ {g['Rótulo']} - {g['Dirección']}\n"
                f"🟡 Gasolina 95: {g['precio_gasolina']} €/L\n"
                f"🔵 Diésel: {g['precio_diesel']} €/L\n"
                f"🕒 Horario: {g['Horario']}\n\n"
            )
        await update.message.reply_text(mensaje.strip())

    return ConversationHandler.END

# Permite cancelar con /cancelar
async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Operación cancelada.")
    return ConversationHandler.END

# Código principal del bot
if __name__ == "__main__":
    TOKEN = os.getenv("TELEGRAM_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={PEDIR_CIUDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_ciudad)]},
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )

    app.add_handler(conv_handler)

    print("✅ Bot activo...")
    app.run_polling()
