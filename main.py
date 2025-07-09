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

PEDIR_CIUDAD = 1
URL = "https://geoportalgasolineras.es/rest/geoportalgasolineras/ListaPrecioGasolinerasSinGalp"

def obtener_top_3(ciudad: str, tipo="Gasoleo A"):
    res = requests.get(URL).json()
    data = res["ListaEESSPrecio"]
    ciudad = ciudad.lower()

    filtradas = [
        g for g in data
        if ciudad in g["Municipio"].lower()
        and g[f"Precio {tipo}"].strip() != ""
    ]

    for g in filtradas:
        g["precio"] = float(g[f"Precio {tipo}"].replace(",", "."))

    top = sorted(filtradas, key=lambda x: x["precio"])[:3]
    return top

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hola 👋 ¿De qué ciudad o pueblo quieres ver las gasolineras más baratas?")
    return PEDIR_CIUDAD

async def recibir_ciudad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ciudad = update.message.text
    top = obtener_top_3(ciudad)

    if not top:
        await update.message.reply_text(f"No encontré gasolineras en '{ciudad}'.")
    else:
        mensaje = f"⛽ Top 3 en {ciudad.title()} (Gasóleo A):\n\n"
        for g in top:
            mensaje += f"🏷️ {g['Rótulo']} - {g['Dirección']}\n💶 {g['precio']} €/L\n🕒 {g['Horario']}\n\n"
        await update.message.reply_text(mensaje.strip())

    return ConversationHandler.END

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelado 👌")
    return ConversationHandler.END

if __name__ == "__main__":
    TOKEN = os.getenv("TELEGRAM_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("precio", start)],
        states={PEDIR_CIUDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_ciudad)]},
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )

    app.add_handler(conv_handler)

    print("Bot activo...")
    app.run_polling()
