import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

URL_GASOLINERAS = "https://geoportalgasolineras.es/rest/geoportalgasolineras/ListaPrecioGasolinerasSinGalp"

# Función para obtener y filtrar gasolineras por localidad
def obtener_top_3(ciudad: str, tipo: str = "Gasoleo A"):
    response = requests.get(URL_GASOLINERAS)
    data = response.json()["ListaEESSPrecio"]

    ciudad = ciudad.lower()
    tipo = tipo.lower()

    gasolineras_filtradas = [
        g for g in data
        if ciudad in g["Municipio"].lower()
        and g[f"Precio {tipo.title()}"] not in ["", " "]
    ]

    # Convertir precios a float y ordenar
    for g in gasolineras_filtradas:
        g["precio"] = float(g[f"Precio {tipo.title()}"].replace(",", "."))
    
    top = sorted(gasolineras_filtradas, key=lambda x: x["precio"])[:3]

    return top

# Comando /precio
async def precio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Por favor, indica una ciudad o pueblo. Ej: /precio Cáceres")
        return

    ciudad = " ".join(context.args)

    try:
        top_gasolineras = obtener_top_3(ciudad)
        if not top_gasolineras:
            await update.message.reply_text(f"No encontré gasolineras en '{ciudad}'.")
            return

        mensaje = f"⛽ Top 3 gasolineras más baratas en {ciudad.title()} (Gasóleo A):\n\n"
        for g in top_gasolineras:
            mensaje += (
                f"🏷️ {g['Rótulo']} - {g['Dirección']}\n"
                f"💶 Precio: {g['precio']} €/L\n"
                f"🕒 Horario: {g['Horario']}\n\n"
            )
        await update.message.reply_text(mensaje.strip())
    except Exception as e:
        await update.message.reply_text("Error al obtener precios. Inténtalo más tarde.")

# Inicializar bot
if __name__ == "__main__":
    import os

    TOKEN = os.getenv("TELEGRAM_TOKEN")  # o pon directamente tu token aquí (no recomendado)

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("precio", precio_command))

    print("Bot corriendo...")
    app.run_polling()
