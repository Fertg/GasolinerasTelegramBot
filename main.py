import os
import time
import json
import requests
import logging
import unicodedata
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup # Añadido
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes
)

# Configuración básica
TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Ej: https://tubot.up.railway.app/
CACHE_FILE = "gasolineras.json"
CACHE_TIEMPO = 6 * 60 * 60  # 6 horas
URL_API = "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ESPERANDO_CIUDAD = range(1)

def normalizar(texto):
    # Elimina tildes y pone en minúsculas
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    ).lower()

def descargar_si_es_necesario():
    if not os.path.exists(CACHE_FILE) or (time.time() - os.path.getmtime(CACHE_FILE)) > CACHE_TIEMPO:
        try:
            logger.info("⛽ Descargando datos actualizados de gasolineras...")
            r = requests.get(URL_API, timeout=10)
            r.raise_for_status()
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(r.json(), f, ensure_ascii=False, indent=2)
            logger.info("✅ Datos guardados.")
        except Exception as e:
            logger.error(f"❌ Error al descargar los datos: {e}")

def obtener_top_3(ciudad):
    descargar_si_es_necesario()
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            datos = json.load(f)["ListaEESSPrecio"]
    except Exception as e:
        return None, f"❌ Error al leer los datos: {e}"

    ciudad = normalizar(ciudad.strip())
    filtradas = []

    for g in datos:
        try:
            # Algunas gasolineras pueden tener la ciudad en un formato diferente,
            # o pueden faltar datos de precio o coordenadas.
            # Se normaliza el municipio de la gasolinera para una mejor coincidencia.
            if ciudad in normalizar(g["Municipio"]):
                # Reemplazar ',' por '.' para que float pueda parsear los precios correctamente
                diesel = float(g["Precio Gasoleo A"].replace(",", "."))
                gasolina = float(g["Precio Gasolina 95 E5"].replace(",", "."))
                
                g["diesel"] = diesel
                g["gasolina"] = gasolina
                filtradas.append(g)
        except (ValueError, KeyError):
            # Ignorar gasolineras con datos incompletos o malformados
            continue

    if not filtradas:
        return None, "⚠️ No se encontraron gasolineras en esa ciudad."

    # Ordenar y obtener el top 3
    top_diesel = sorted(filtradas, key=lambda x: x["diesel"])[:3]
    top_gasolina = sorted(filtradas, key=lambda x: x["gasolina"])[:3]

    return (top_diesel, top_gasolina), None

# Comandos del bot

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 ¡Bienvenido al bot de precios de gasolina ⛽!\n\n"
        "Usa /precio para consultar el precio más barato en tu ciudad.\n"
        "Escribe /cancelar para salir de la búsqueda."
    )

async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📍 ¿Qué ciudad quieres consultar?")
    return ESPERANDO_CIUDAD

async def recibir_ciudad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ciudad = update.message.text
    resultado, error = obtener_top_3(ciudad)

    if error:
        await update.message.reply_text(error)
        return ConversationHandler.END

    top_diesel, top_gasolina = resultado
    full_keyboard = [] # Lista para almacenar todos los botones

    msg = f"⛽ *Top 3 Diésel en {ciudad.title()}*\n"
    for i, g in enumerate(top_diesel):
        try:
            # Asegúrate de que las coordenadas sean strings y reemplaza la coma por punto para float
            lat = float(g["Latitud"].replace(",", "."))
            lon = float(g["Longitud (WGS84)"].replace(",", "."))
            # Construye la URL de Google Maps
            Maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
            
            msg += f"• {g['Rótulo']} - {g['diesel']} €\n  📍 {g['Dirección']}\n"
            # Añade el botón a la lista de botones. Cada lista interna representa una fila de botones.
            full_keyboard.append([InlineKeyboardButton(f"📍 {g['Rótulo']} (Diésel)", url=Maps_url)])
        except (ValueError, KeyError):
            # En caso de que las coordenadas falten o estén mal, no añadir botón
            msg += f"• {g['Rótulo']} - {g['diesel']} €\n  📍 {g['Dirección']} (Coordenadas no disponibles)\n"

    msg += f"\n⛽ *Top 3 Gasolina 95 en {ciudad.title()}*\n"
    for i, g in enumerate(top_gasolina):
        try:
            lat = float(g["Latitud"].replace(",", "."))
            lon = float(g["Longitud (WGS84)"].replace(",", "."))
            Maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
            
            msg += f"• {g['Rótulo']} - {g['gasolina']} €\n  📍 {g['Dirección']}\n"
            full_keyboard.append([InlineKeyboardButton(f"📍 {g['Rótulo']} (Gasolina)", url=Maps_url)])
        except (ValueError, KeyError):
            msg += f"• {g['Rótulo']} - {g['gasolina']} €\n  📍 {g['Dirección']} (Coordenadas no disponibles)\n"

    # Crea el objeto InlineKeyboardMarkup con todos los botones
    reply_markup = InlineKeyboardMarkup(full_keyboard)

    # Envía el mensaje con los precios y los botones
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
    return ConversationHandler.END

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Consulta cancelada.")
    return ConversationHandler.END

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("precio", precio)],
        states={ESPERANDO_CIUDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_ciudad)]},
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    # Configuración para Webhook (ideal para despliegue en plataformas como Railway)
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        url_path=TOKEN,
        webhook_url=f"{WEBHOOK_URL}{TOKEN}"
    )