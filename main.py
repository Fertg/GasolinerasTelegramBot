import os
import time
import json
import requests
import logging
import unicodedata
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Location
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes
)

# --- Configuración básica ---
# Reemplaza "TU_TELEGRAM_TOKEN" con tu token real de bot
TOKEN = os.getenv("TELEGRAM_TOKEN", "TU_TELEGRAM_TOKEN")
# Si usas Railway, esta URL debe ser la de tu app. Ej: https://tubot.up.railway.app/
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://example.com/your-bot-webhook/")
CACHE_FILE = "gasolineras.json"
CACHE_TIEMPO = 6 * 60 * 60  # 6 horas
URL_API = "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/"

# --- Configuración de Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO # Cambia a logging.DEBUG para ver más trazas detalladas
)
logger = logging.getLogger(__name__)

# --- Estados para ConversationHandler ---
ESPERANDO_CIUDAD = range(1)

# --- Funciones de Utilidad ---
def normalizar(texto):
    """
    Normaliza el texto: elimina tildes y convierte a minúsculas.
    Útil para comparar nombres de municipios sin importar acentos.
    """
    logger.debug(f"Normalizando texto: '{texto}'")
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    ).lower()

def descargar_si_es_necesario():
    """
    Descarga los datos de las gasolineras si el archivo de caché no existe
    o si ha caducado (más de CACHE_TIEMPO segundos).
    """
    descargar = False
    if not os.path.exists(CACHE_FILE):
        logger.info("Cache: El archivo 'gasolineras.json' no existe. Se requiere descarga.")
        descargar = True
    elif (time.time() - os.path.getmtime(CACHE_FILE)) > CACHE_TIEMPO:
        logger.info(f"Cache: El archivo 'gasolineras.json' ha caducado (más de {CACHE_TIEMPO / 3600} horas). Se requiere descarga.")
        descargar = True
    else:
        logger.info("Cache: El archivo 'gasolineras.json' está actualizado. No se requiere descarga.")

    if descargar:
        try:
            logger.info("⛽ Descargando datos actualizados de gasolineras desde la API del Ministerio...")
            # Aumentamos el timeout a 30 segundos para dar más margen a la API
            r = requests.get(URL_API, timeout=30)
            r.raise_for_status() # Lanza una excepción si la respuesta no es 200 OK
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(r.json(), f, ensure_ascii=False, indent=2)
            logger.info("✅ Datos guardados en 'gasolineras.json' correctamente.")
            return True # Indica que la descarga fue exitosa
        except requests.exceptions.Timeout:
            logger.error(f"❌ Error al descargar los datos: Tiempo de espera excedido (Timeout).")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error al descargar los datos (RequestException): {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Error inesperado al descargar los datos: {e}")
            return False
    return True # No se requirió descarga o ya se había descargado antes

def haversine(lat1, lon1, lat2, lon2):
    """
    Calcula la distancia Haversine entre dos puntos (latitud, longitud) en kilómetros.
    """
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
    logger.debug(f"Distancia calculada entre ({lat1},{lon1}) y ({lat2},{lon2}): {distance:.2f} km")
    return distance

def obtener_datos_gasolineras():
    """
    Intenta cargar los datos de gasolineras desde el archivo de caché.
    Retorna los datos o None si hay un error.
    """
    if not descargar_si_es_necesario():
        logger.error("No se pudo asegurar la descarga o existencia de 'gasolineras.json'.")
        return None

    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            datos = json.load(f)["ListaEESSPrecio"]
            logger.info(f"Cargados {len(datos)} estaciones de servicio desde '{CACHE_FILE}'.")
            return datos
    except FileNotFoundError:
        logger.error(f"❌ Error: El archivo '{CACHE_FILE}' no se encontró después de intentar descargar. Esto no debería ocurrir.")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"❌ Error al decodificar JSON de '{CACHE_FILE}': {e}. El archivo podría estar corrupto.")
        return None
    except KeyError:
        logger.error(f"❌ Error: El formato del JSON no contiene 'ListaEESSPrecio'. La API pudo haber cambiado.")
        return None
    except Exception as e:
        logger.error(f"❌ Error inesperado al leer los datos de gasolineras: {e}")
        return None

def filtrar_y_obtener_top_3(gasolineras, criterio_busqueda, tipo_busqueda="ciudad", umbral_distancia=20):
    """
    Filtra las gasolineras y obtiene el top 3 según el criterio de búsqueda
    (ciudad o ubicación).
    """
    filtradas = []
    logger.info(f"Iniciando filtrado por {tipo_busqueda} para '{criterio_busqueda}'...")

    for g in gasolineras:
        try:
            # Reemplazar ',' por '.' para que float pueda parsear los precios y coordenadas correctamente
            diesel = float(g.get("Precio Gasoleo A", "0").replace(",", "."))
            gasolina = float(g.get("Precio Gasolina 95 E5", "0").replace(",", "."))
            
            # Asegurarse de que los precios son válidos (no 0 si se asume que deberían tener precio)
            if diesel == 0 or gasolina == 0:
                logger.debug(f"Saltando gasolinera '{g.get('Rótulo', 'N/A')}' por precio 0.")
                continue

            g_lat = float(g.get("Latitud", "0").replace(",", "."))
            g_lon = float(g.get("Longitud (WGS84)", "0").replace(",", "."))
            
            if g_lat == 0 or g_lon == 0: # Coordenadas 0/0 suelen ser datos faltantes o inválidos
                logger.debug(f"Saltando gasolinera '{g.get('Rótulo', 'N/A')}' por coordenadas inválidas.")
                continue

            es_valida = False
            if tipo_busqueda == "ciudad":
                municipio = normalizar(g.get("Municipio", ""))
                if criterio_busqueda in municipio:
                    es_valida = True
            elif tipo_busqueda == "ubicacion":
                user_lat, user_lon = criterio_busqueda
                dist = haversine(user_lat, user_lon, g_lat, g_lon)
                if dist <= umbral_distancia:
                    g["distancia"] = dist
                    es_valida = True
            
            if es_valida:
                g["diesel"] = diesel
                g["gasolina"] = gasolina
                filtradas.append(g)
        except (ValueError, KeyError) as e:
            logger.debug(f"Saltando gasolinera por error de datos: {e} en {g.get('Rótulo', 'N/A')}")
            continue # Ignorar gasolineras con datos incompletos o malformados

    if not filtradas:
        logger.info("No se encontraron gasolineras que cumplan el criterio.")
        return None, f"⚠️ No se encontraron gasolineras en ese rango o ciudad."

    # Ordenar y obtener el top 3
    if tipo_busqueda == "ciudad":
        top_diesel = sorted(filtradas, key=lambda x: x["diesel"])[:3]
        top_gasolina = sorted(filtradas, key=lambda x: x["gasolina"])[:3]
    else: # Por ubicación, ordenar también por distancia en caso de precios iguales
        top_diesel = sorted(filtradas, key=lambda x: (x["diesel"], x.get("distancia", 0)))[:3]
        top_gasolina = sorted(filtradas, key=lambda x: (x["gasolina"], x.get("distancia", 0)))[:3]

    logger.info(f"Encontradas {len(top_diesel)} top diésel y {len(top_gasolina)} top gasolina.")
    return (top_diesel, top_gasolina), None

# --- Comandos del Bot ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Comando /start recibido de {update.effective_user.id}")
    await update.message.reply_text(
        "👋 ¡Bienvenido al bot de precios de gasolina ⛽!\n\n"
        "Usa /precio para consultar el precio más barato en tu ciudad o cerca de ti.\n"
        "Escribe /cancelar para salir de la búsqueda."
    )

async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Comando /precio recibido de {update.effective_user.id}")
    await update.message.reply_text("📍 ¿Qué ciudad quieres consultar? O si lo prefieres, ¡envíame tu ubicación actual!")
    return ESPERANDO_CIUDAD

async def recibir_ciudad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ciudad = update.message.text
    logger.info(f"Mensaje de ciudad recibido de {update.effective_user.id}: '{ciudad}'")

    gasolineras_disponibles = obtener_datos_gasolineras()
    if gasolineras_disponibles is None:
        await update.message.reply_text(f"❌ No se pudieron cargar los datos de gasolineras. Inténtalo de nuevo más tarde.")
        return ConversationHandler.END

    resultado, error = filtrar_y_obtener_top_3(gasolineras_disponibles, normalizar(ciudad), tipo_busqueda="ciudad")

    if error:
        await update.message.reply_text(error)
        return ConversationHandler.END

    top_diesel, top_gasolina = resultado
    full_keyboard = []

    msg = f"⛽ *Top 3 Diésel en {ciudad.title()}*\n"
    for g in top_diesel:
        try:
            lat = float(g.get("Latitud", "0").replace(",", "."))
            lon = float(g.get("Longitud (WGS84)", "0").replace(",", "."))
            Maps_url = f"http://maps.google.com/maps?q={lat},{lon}"
            
            msg += f"• {g['Rótulo']} - {g['diesel']} €\n  📍 {g['Dirección']}\n"
            full_keyboard.append([InlineKeyboardButton(f"📍 {g['Rótulo']} (Diésel)", url=Maps_url)])
        except (ValueError, KeyError):
            msg += f"• {g['Rótulo']} - {g['diesel']} €\n  📍 {g['Dirección']} (Coordenadas no disponibles)\n"
            logger.warning(f"Coordenadas inválidas para gasolinera {g.get('Rótulo', 'N/A')}")


    msg += f"\n⛽ *Top 3 Gasolina 95 en {ciudad.title()}*\n"
    for g in top_gasolina:
        try:
            lat = float(g.get("Latitud", "0").replace(",", "."))
            lon = float(g.get("Longitud (WGS84)", "0").replace(",", "."))
            Maps_url = f"http://maps.google.com/maps?q={lat},{lon}"
            
            msg += f"• {g['Rótulo']} - {g['gasolina']} €\n  📍 {g['Dirección']}\n"
            full_keyboard.append([InlineKeyboardButton(f"📍 {g['Rótulo']} (Gasolina)", url=Maps_url)])
        except (ValueError, KeyError):
            msg += f"• {g['Rótulo']} - {g['gasolina']} €\n  📍 {g['Dirección']} (Coordenadas no disponibles)\n"
            logger.warning(f"Coordenadas inválidas para gasolinera {g.get('Rótulo', 'N/A')}")

    reply_markup = InlineKeyboardMarkup(full_keyboard)
    logger.info(f"Enviando resultados de ciudad para {ciudad}.")
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
    return ConversationHandler.END

async def recibir_ubicacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_location = update.message.location
    user_lat = user_location.latitude
    user_lon = user_location.longitude
    logger.info(f"Ubicación recibida de {update.effective_user.id}: Lat={user_lat}, Lon={user_lon}")

    await update.message.reply_text("🔎 Buscando gasolineras cercanas a tu ubicación...")

    gasolineras_disponibles = obtener_datos_gasolineras()
    if gasolineras_disponibles is None:
        await update.message.reply_text(f"❌ No se pudieron cargar los datos de gasolineras. Inténtalo de nuevo más tarde.")
        return ConversationHandler.END

    resultado, error = filtrar_y_obtener_top_3(gasolineras_disponibles, (user_lat, user_lon), tipo_busqueda="ubicacion", umbral_distancia=20)

    if error:
        await update.message.reply_text(error)
        return ConversationHandler.END

    top_diesel, top_gasolina = resultado
    full_keyboard = []

    msg = f"⛽ *Top 3 Diésel cerca de ti*\n"
    for g in top_diesel:
        try:
            lat = float(g.get("Latitud", "0").replace(",", "."))
            lon = float(g.get("Longitud (WGS84)", "0").replace(",", "."))
            Maps_url = f"http://maps.google.com/maps?q={lat},{lon}"
            msg += f"• {g['Rótulo']} - {g['diesel']} € ({g['distancia']:.2f} km)\n  📍 {g['Dirección']}\n"
            full_keyboard.append([InlineKeyboardButton(f"📍 {g['Rótulo']} (Diésel)", url=Maps_url)])
        except (ValueError, KeyError):
            msg += f"• {g['Rótulo']} - {g['diesel']} € ({g['distancia']:.2f} km)\n  📍 {g['Dirección']} (Coordenadas no disponibles)\n"
            logger.warning(f"Coordenadas inválidas para gasolinera {g.get('Rótulo', 'N/A')} en ubicación.")


    msg += f"\n⛽ *Top 3 Gasolina 95 cerca de ti*\n"
    for g in top_gasolina:
        try:
            lat = float(g.get("Latitud", "0").replace(",", "."))
            lon = float(g.get("Longitud (WGS84)", "0").replace(",", "."))
            Maps_url = f"http://maps.google.com/maps?q={lat},{lon}"
            msg += f"• {g['Rótulo']} - {g['gasolina']} € ({g['distancia']:.2f} km)\n  📍 {g['Dirección']}\n"
            full_keyboard.append([InlineKeyboardButton(f"📍 {g['Rótulo']} (Gasolina)", url=Maps_url)])
        except (ValueError, KeyError):
            msg += f"• {g['Rótulo']} - {g['gasolina']} € ({g['distancia']:.2f} km)\n  📍 {g['Dirección']} (Coordenadas no disponibles)\n"
            logger.warning(f"Coordenadas inválidas para gasolinera {g.get('Rótulo', 'N/A')} en ubicación.")

    reply_markup = InlineKeyboardMarkup(full_keyboard)
    logger.info(f"Enviando resultados de ubicación para Lat={user_lat}, Lon={user_lon}.")
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
    return ConversationHandler.END

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Comando /cancelar recibido de {update.effective_user.id}")
    await update.message.reply_text("❌ Consulta cancelada.")
    return ConversationHandler.END

# --- Configuración y Ejecución del Bot ---
if __name__ == "__main__":
    logger.info("Iniciando aplicación Telegram Bot...")
    app = ApplicationBuilder().token(TOKEN).build()

    # Manejador de conversación para /precio
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

    # Añadir manejadores de comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    logger.info(f"Configurando webhook para URL: {WEBHOOK_URL}{TOKEN} en puerto {os.environ.get('PORT', 8080)}")
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        url_path=TOKEN,
        webhook_url=f"{WEBHOOK_URL}{TOKEN}"
    )
    logger.info("Aplicación Telegram Bot iniciada y escuchando por webhooks. ")