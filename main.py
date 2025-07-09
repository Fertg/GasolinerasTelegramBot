import os
import time
import json
import requests
import logging
import unicodedata
import math # Para el cálculo de distancia
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Location

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
            if ciudad in normalizar(g["Municipio"]):
                diesel = float(g["Precio Gasoleo A"].replace(",", "."))
                gasolina = float(g["Precio Gasolina 95 E5"].replace(",", "."))
                
                g["diesel"] = diesel
                g["gasolina"] = gasolina
                filtradas.append(g)
        except (ValueError, KeyError):
            continue

    if not filtradas:
        return None, "⚠️ No se encontraron gasolineras en esa ciudad."

    top_diesel = sorted(filtradas, key=lambda x: x["diesel"])[:3]
    top_gasolina = sorted(filtradas, key=lambda x: x["gasolina"])[:3]

    return (top_diesel, top_gasolina), None

# Función para calcular la distancia Haversine entre dos puntos (lat, lon)
def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Radio de la Tierra en kilómetros

    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad

    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    distance = R * c
    return distance

# Comandos del bot

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 ¡Bienvenido al bot de precios de gasolina ⛽!\n\n"
        "Usa /precio para consultar el precio más barato en tu ciudad.\n"
        "Escribe /cancelar para salir de la búsqueda."
    )

async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ¡Aquí está el cambio!
    await update.message.reply_text("📍 ¿Qué ciudad quieres consultar? O si lo prefieres, ¡envíame tu ubicación actual!")
    return ESPERANDO_CIUDAD

async def recibir_ciudad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ciudad = update.message.text
    resultado, error = obtener_top_3(ciudad)

    if error:
        await update.message.reply_text(error)
        return ConversationHandler.END

    top_diesel, top_gasolina = resultado
    full_keyboard = []

    msg = f"⛽ *Top 3 Diésel en {ciudad.title()}*\n"
    for i, g in enumerate(top_diesel):
        try:
            lat = float(g["Latitud"].replace(",", "."))
            lon = float(g["Longitud (WGS84)"].replace(",", "."))
            Maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
            
            msg += f"• {g['Rótulo']} - {g['diesel']} €\n  📍 {g['Dirección']}\n"
            full_keyboard.append([InlineKeyboardButton(f"📍 {g['Rótulo']} (Diésel)", url=Maps_url)])
        except (ValueError, KeyError):
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

    reply_markup = InlineKeyboardMarkup(full_keyboard)

    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
    return ConversationHandler.END

async def recibir_ubicacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_location = update.message.location
    user_lat = user_location.latitude
    user_lon = user_location.longitude

    await update.message.reply_text("🔎 Buscando gasolineras cercanas a tu ubicación...")

    descargar_si_es_necesario()

    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            datos = json.load(f)["ListaEESSPrecio"]
    except Exception as e:
        await update.message.reply_text(f"❌ Error al leer los datos de gasolineras: {e}")
        return ConversationHandler.END

    gasolineras_cercanas = []

    for g in datos:
        try:
            gas_lat = float(g["Latitud"].replace(",", "."))
            gas_lon = float(g["Longitud (WGS84)"].replace(",", "."))

            dist = haversine(user_lat, user_lon, gas_lat, gas_lon)

            if dist <= 20: # Filtrar gasolineras en un radio de 20 km
                diesel = float(g["Precio Gasoleo A"].replace(",", "."))
                gasolina = float(g["Precio Gasolina 95 E5"].replace(",", "."))
                g["diesel"] = diesel
                g["gasolina"] = gasolina
                g["distancia"] = dist
                gasolineras_cercanas.append(g)
        except (ValueError, KeyError):
            continue

    if not gasolineras_cercanas:
        await update.message.reply_text("⚠️ No se encontraron gasolineras en un radio de 20 km. Prueba a especificar una ciudad con /precio.")
        return ConversationHandler.END

    top_diesel = sorted(gasolineras_cercanas, key=lambda x: (x["diesel"], x["distancia"]))[:3]
    top_gasolina = sorted(gasolineras_cercanas, key=lambda x: (x["gasolina"], x["distancia"]))[:3]

    full_keyboard = []
    msg = f"⛽ *Top 3 Diésel cerca de ti*\n"
    for g in top_diesel:
        try:
            lat = float(g["Latitud"].replace(",", "."))
            lon = float(g["Longitud (WGS84)"].replace(",", "."))
            Maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
            msg += f"• {g['Rótulo']} - {g['diesel']} € ({g['distancia']:.2f} km)\n  📍 {g['Dirección']}\n"
            full_keyboard.append([InlineKeyboardButton(f"📍 {g['Rótulo']} (Diésel)", url=Maps_url)])
        except (ValueError, KeyError):
            msg += f"• {g['Rótulo']} - {g['diesel']} € ({g['distancia']:.2f} km)\n  📍 {g['Dirección']} (Coordenadas no disponibles)\n"


    msg += f"\n⛽ *Top 3 Gasolina 95 cerca de ti*\n"
    for g in top_gasolina:
        try:
            lat = float(g["Latitud"].replace(",", "."))
            lon = float(g["Longitud (WGS84)"].replace(",", "."))
            Maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
            msg += f"• {g['Rótulo']} - {g['gasolina']} € ({g['distancia']:.2f} km)\n  📍 {g['Dirección']}\n"
            full_keyboard.append([InlineKeyboardButton(f"📍 {g['Rótulo']} (Gasolina)", url=Maps_url)])
        except (ValueError, KeyError):
            msg += f"• {g['Rótulo']} - {g['gasolina']} € ({g['distancia']:.2f} km)\n  📍 {g['Dirección']} (Coordenadas no disponibles)\n"

    reply_markup = InlineKeyboardMarkup(full_keyboard)
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
    return ConversationHandler.END


async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Consulta cancelada.")
    return ConversationHandler.END

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("precio", precio)],
        states={
            ESPERANDO_CIUDAD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_ciudad),
                MessageHandler(filters.LOCATION, recibir_ubicacion)
            ]
        },
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        url_path=TOKEN,
        webhook_url=f"{WEBHOOK_URL}{TOKEN}"
    )