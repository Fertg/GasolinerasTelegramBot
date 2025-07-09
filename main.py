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

# --- Configuración del Bot y Entorno ---
# Estas variables se leerán desde el entorno de Railway (o donde lo despliegues)
TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# --- Configuración de Caché y API de Carburantes ---
CACHE_FILE = "gasolineras.json"
CACHE_TIEMPO = 6 * 60 * 60  # 6 horas (tiempo antes de volver a descargar los datos)
URL_API = "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/"

# --- Configuración de Logging ---
# Configura el formato de los logs y el nivel.
# Cambia 'logging.INFO' a 'logging.DEBUG' si quieres ver más detalles en los logs.
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__) # Obtiene un logger para este módulo

# --- Estados para ConversationHandler ---
ESPERANDO_CIUDAD = range(1) # Un estado para la conversación de búsqueda por ciudad/ubicación

# --- Funciones de Utilidad ---

def normalizar(texto):
    """
    Normaliza un texto (ej. nombre de ciudad): elimina tildes y convierte a minúsculas.
    Esto ayuda a hacer las búsquedas más flexibles e independientes de mayúsculas/minúsculas o acentos.
    """
    logger.debug(f"Normalizando texto: '{texto}'")
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto) # Normaliza a forma NFD (caracter + diacrítico)
        if unicodedata.category(c) != 'Mn' # Filtra los diacríticos (tildes, etc.)
    ).lower() # Convierte a minúsculas

def descargar_si_es_necesario():
    """
    Gestiona la caché de datos de gasolineras.
    Descarga los datos de la API del Ministerio si el archivo de caché no existe
    o si su última modificación excede el tiempo definido en CACHE_TIEMPO.
    Retorna True si los datos están disponibles (descargados o ya en caché), False en caso contrario.
    """
    descargar = False
    if not os.path.exists(CACHE_FILE):
        logger.info(f"Cache: El archivo '{CACHE_FILE}' no existe. Se requiere descarga inicial.")
        descargar = True
    elif (time.time() - os.path.getmtime(CACHE_FILE)) > CACHE_TIEMPO:
        logger.info(f"Cache: El archivo '{CACHE_FILE}' ha caducado (más de {CACHE_TIEMPO / 3600:.1f} horas). Se requiere descarga.")
        descargar = True
    else:
        logger.info(f"Cache: El archivo '{CACHE_FILE}' está actualizado. No se requiere descarga.")

    if descargar:
        logger.info("⛽ Iniciando descarga de datos de gasolineras desde la API del Ministerio...")
        try:
            # Realiza la petición GET a la API con un timeout generoso de 60 segundos
            r = requests.get(URL_API, timeout=60)
            r.raise_for_status() # Lanza una excepción para códigos de estado HTTP 4xx/5xx
            
            # Guarda la respuesta JSON en el archivo de caché
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(r.json(), f, ensure_ascii=False, indent=2)
            logger.info(f"✅ Datos guardados en '{CACHE_FILE}' correctamente.")
            return True # Descarga exitosa
        except requests.exceptions.Timeout:
            logger.error(f"❌ Error al descargar los datos: Tiempo de espera excedido (Timeout). La API tardó demasiado en responder.")
            return False
        except requests.exceptions.ConnectionError as e:
            logger.error(f"❌ Error al descargar los datos (ConnectionError): Problema de red o conexión con la API: {e}")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error al descargar los datos (RequestException): Problema con la petición HTTP: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Error inesperado al descargar los datos: {e}")
            return False
    return True # No se necesitó descarga o ya se había descargado con éxito

def haversine(lat1, lon1, lat2, lon2):
    """
    Calcula la distancia Haversine entre dos puntos (latitud, longitud) en kilómetros.
    Útil para encontrar gasolineras cercanas a una ubicación dada.
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
    logger.debug(f"Distancia calculada entre ({lat1:.4f},{lon1:.4f}) y ({lat2:.4f},{lon2:.4f}): {distance:.2f} km")
    return distance

def obtener_datos_gasolineras():
    """
    Intenta cargar los datos de gasolineras desde el archivo de caché.
    Si el caché no está actualizado o no existe, intenta descargarlos primero.
    Retorna la lista de gasolineras o None si hay un error crítico.
    """
    if not descargar_si_es_necesario():
        logger.error("No se pudieron obtener los datos de 'gasolineras.json' (falló la descarga o no se pudo acceder).")
        return None

    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            datos = json.load(f)["ListaEESSPrecio"]
            logger.info(f"Cargados {len(datos)} estaciones de servicio desde '{CACHE_FILE}'.")
            return datos
    except FileNotFoundError:
        logger.error(f"❌ Error: El archivo '{CACHE_FILE}' no se encontró después de intentar asegurar su existencia. Esto es inesperado.")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"❌ Error al decodificar JSON de '{CACHE_FILE}': {e}. El archivo podría estar corrupto o vacío.")
        # Opcional: Podrías intentar borrar el archivo corrupto aquí para forzar una nueva descarga en el siguiente intento.
        return None
    except KeyError:
        logger.error(f"❌ Error: El formato del JSON no contiene la clave esperada 'ListaEESSPrecio'. La API pudo haber cambiado su estructura.")
        return None
    except Exception as e:
        logger.error(f"❌ Error inesperado al leer los datos de gasolineras desde '{CACHE_FILE}': {e}")
        return None

def filtrar_y_obtener_top_3(gasolineras, criterio_busqueda, tipo_busqueda="ciudad", umbral_distancia=20):
    """
    Filtra la lista de gasolineras y obtiene las 3 más baratas para diésel y gasolina.
    Puede filtrar por ciudad o por cercanía a una ubicación (lat/lon).
    """
    filtradas = []
    logger.info(f"Iniciando filtrado por {tipo_busqueda} para criterio: '{criterio_busqueda}'")

    for g in gasolineras:
        try:
            # Limpiar y convertir precios y coordenadas a float, usando .get() para seguridad
            diesel = float(g.get("Precio Gasoleo A", "0").replace(",", "."))
            gasolina = float(g.get("Precio Gasolina 95 E5", "0").replace(",", "."))
            g_lat = float(g.get("Latitud", "0").replace(",", "."))
            g_lon = float(g.get("Longitud (WGS84)", "0").replace(",", "."))
            
            # Validar precios y coordenadas (valores 0.0 o menos suelen ser datos faltantes/inválidos)
            if diesel <= 0.0 or gasolina <= 0.0:
                logger.debug(f"Saltando gasolinera '{g.get('Rótulo', 'N/A')}' por precio inválido (Diésel: {diesel}, Gasolina: {gasolina}).")
                continue
            if (g_lat == 0.0 and g_lon == 0.0) or not (-90 <= g_lat <= 90 and -180 <= g_lon <= 180):
                logger.debug(f"Saltando gasolinera '{g.get('Rótulo', 'N/A')}' por coordenadas inválidas ({g_lat},{g_lon}).")
                continue

            es_valida = False
            if tipo_busqueda == "ciudad":
                municipio = normalizar(g.get("Municipio", ""))
                if criterio_busqueda in municipio: # Búsqueda de subcadena en el municipio normalizado
                    es_valida = True
            elif tipo_busqueda == "ubicacion":
                user_lat, user_lon = criterio_busqueda
                dist = haversine(user_lat, user_lon, g_lat, g_lon)
                if dist <= umbral_distancia: # Filtrar por distancia máxima
                    g["distancia"] = dist
                    es_valida = True
            
            if es_valida:
                g["diesel"] = diesel
                g["gasolina"] = gasolina
                filtradas.append(g)
        except (ValueError, KeyError) as e:
            logger.debug(f"Saltando gasolinera '{g.get('Rótulo', 'N/A')}' debido a error al procesar datos: {e}. Datos brutos: {g}")
            continue # Continúa con la siguiente gasolinera si los datos no son válidos

    if not filtradas:
        logger.info(f"No se encontraron gasolineras que cumplan el criterio para '{criterio_busqueda}'.")
        return None, f"⚠️ No se encontraron gasolineras que cumplan los criterios de búsqueda (precios válidos, coordenadas, o distancia/ciudad). Prueba con un nombre de ciudad más general o amplía el rango de búsqueda."

    # Ordena las gasolineras filtradas por precio para obtener el top 3
    # Si es por ubicación, también considera la distancia en caso de precios iguales.
    top_diesel = sorted(filtradas, key=lambda x: (x["diesel"], x.get("distancia", 0)))[:3]
    top_gasolina = sorted(filtradas, key=lambda x: (x["gasolina"], x.get("distancia", 0)))[:3]

    logger.info(f"Encontradas {len(top_diesel)} top diésel y {len(top_gasolina)} top gasolina para '{criterio_busqueda}'.")
    return (top_diesel, top_gasolina), None

# --- Manejadores de Comandos del Bot ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /start. Envía un mensaje de bienvenida."""
    logger.info(f"Comando /start recibido de usuario {update.effective_user.id} ({update.effective_user.full_name})")
    await update.message.reply_text(
        "👋 ¡Bienvenido al bot de precios de gasolina ⛽!\n\n"
        "Usa /precio para consultar el precio más barato en tu ciudad o cerca de ti.\n"
        "Escribe /cancelar para salir de la búsqueda actual."
    )

async def precio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /precio. Pide al usuario que ingrese una ciudad o su ubicación."""
    logger.info(f"Comando /precio recibido de usuario {update.effective_user.id}")
    await update.message.reply_text("📍 ¿Qué ciudad quieres consultar? O si lo prefieres, ¡envíame tu ubicación actual!")
    return ESPERANDO_CIUDAD # Cambia el estado a ESPERANDO_CIUDAD para la conversación

async def recibir_ciudad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Maneja el mensaje de texto del usuario (considerado como nombre de ciudad).
    Busca gasolineras por ciudad y envía los resultados.
    """
    ciudad = update.message.text
    logger.info(f"Mensaje de texto recibido de usuario {update.effective_user.id} (asumiendo ciudad): '{ciudad}'")

    # Intenta obtener los datos de gasolineras (descargará si es necesario)
    gasolineras_disponibles = obtener_datos_gasolineras()
    if gasolineras_disponibles is None:
        await update.message.reply_text(f"❌ Lo siento, no pude cargar los datos de gasolineras. Por favor, inténtalo de nuevo más tarde.")
        return ConversationHandler.END # Termina la conversación

    # Filtra y obtiene el top 3 por la ciudad proporcionada
    resultado, error = filtrar_y_obtener_top_3(gasolineras_disponibles, normalizar(ciudad), tipo_busqueda="ciudad")

    # Si hay un error en el filtrado (no se encontraron gasolineras), envía el error y termina.
    if error:
        logger.info(f"No se encontraron resultados de gasolineras para la ciudad '{ciudad}'. Mensaje de error: {error}")
        await update.message.reply_text(error)
        return ConversationHandler.END
    
    # Si hay resultados, construye y envía el mensaje
    top_diesel, top_gasolina = resultado
    full_keyboard = [] # Para los botones de mapa

    msg_content = "" # Variable para construir el cuerpo del mensaje

    if top_diesel:
        msg_content += f"⛽ *Top 3 Diésel en {ciudad.title()}*\n"
        for i, g in enumerate(top_diesel):
            try:
                lat = float(g.get("Latitud", "0").replace(",", "."))
                lon = float(g.get("Longitud (WGS84)", "0").replace(",", "."))
                # URL de Google Maps para abrir la ubicación
                Maps_url = f"http://maps.google.com/maps?q={lat},{lon}" 
                
                msg_content += f"• {g['Rótulo']} - {g['diesel']} €\n  📍 {g['Dirección']}\n"
                full_keyboard.append([InlineKeyboardButton(f"📍 {g['Rótulo']} (Diésel)", url=Maps_url)])
            except (ValueError, KeyError) as e:
                msg_content += f"• {g['Rótulo']} - {g['diesel']} €\n  📍 {g['Dirección']} (Coordenadas no disponibles)\n"
                logger.warning(f"Coordenadas inválidas para gasolinera {g.get('Rótulo', 'N/A')} en búsqueda por ciudad: {e}")

    if top_gasolina:
        if msg_content: msg_content += "\n" # Añade un salto de línea si ya hay contenido de diésel
        msg_content += f"⛽ *Top 3 Gasolina 95 en {ciudad.title()}*\n"
        for i, g in enumerate(top_gasolina):
            try:
                lat = float(g.get("Latitud", "0").replace(",", "."))
                lon = float(g.get("Longitud (WGS84)", "0").replace(",", "."))
                Maps_url = f"http://maps.google.com/maps?q={lat},{lon}"
                
                msg_content += f"• {g['Rótulo']} - {g['gasolina']} €\n  📍 {g['Dirección']}\n"
                full_keyboard.append([InlineKeyboardButton(f"📍 {g['Rótulo']} (Gasolina)", url=Maps_url)])
            except (ValueError, KeyError) as e:
                msg_content += f"• {g['Rótulo']} - {g['gasolina']} €\n  📍 {g['Dirección']} (Coordenadas no disponibles)\n"
                logger.warning(f"Coordenadas inválidas para gasolinera {g.get('Rótulo', 'N/A')} en búsqueda por ciudad: {e}")

    # Fallback final si por alguna razón el mensaje sigue vacío
    if not msg_content.strip(): # .strip() para verificar si no hay solo espacios en blanco
        msg_content = "⚠️ Lo siento, no pude generar una lista detallada de gasolineras para esa ciudad. Intenta con un nombre diferente o con tu ubicación."
        reply_markup = None # No hay botones si no hay resultados detallados
    else:
        reply_markup = InlineKeyboardMarkup(full_keyboard)

    logger.info(f"Enviando resultados de ciudad para '{ciudad}'. Longitud del mensaje: {len(msg_content)} caracteres.")
    await update.message.reply_text(msg_content, parse_mode="Markdown", reply_markup=reply_markup)
    return ConversationHandler.END # Termina la conversación

async def recibir_ubicacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Maneja la ubicación enviada por el usuario.
    Busca gasolineras cercanas y envía los resultados.
    """
    user_location = update.message.location
    user_lat = user_location.latitude
    user_lon = user_location.longitude
    logger.info(f"Ubicación recibida de usuario {update.effective_user.id}: Lat={user_lat:.4f}, Lon={user_lon:.4f}")

    await update.message.reply_text("🔎 Buscando gasolineras cercanas a tu ubicación (radio de 20 km)...")

    # Intenta obtener los datos de gasolineras (descargará si es necesario)
    gasolineras_disponibles = obtener_datos_gasolineras()
    if gasolineras_disponibles is None:
        await update.message.reply_text(f"❌ Lo siento, no pude cargar los datos de gasolineras. Por favor, inténtalo de nuevo más tarde.")
        return ConversationHandler.END # Termina la conversación

    # Filtra y obtiene el top 3 por cercanía a la ubicación
    resultado, error = filtrar_y_obtener_top_3(gasolineras_disponibles, (user_lat, user_lon), tipo_busqueda="ubicacion", umbral_distancia=20)

    # Si hay un error en el filtrado, envía el error y termina.
    if error:
        logger.info(f"No se encontraron resultados de gasolineras para la ubicación ({user_lat:.4f},{user_lon:.4f}). Mensaje de error: {error}")
        await update.message.reply_text(error)
        return ConversationHandler.END

    # Si hay resultados, construye y envía el mensaje
    top_diesel, top_gasolina = resultado
    full_keyboard = []

    msg_content = ""

    if top_diesel:
        msg_content += f"⛽ *Top 3 Diésel cerca de ti*\n"
        for i, g in enumerate(top_diesel):
            try:
                lat = float(g.get("Latitud", "0").replace(",", "."))
                lon = float(g.get("Longitud (WGS84)", "0").replace(",", "."))
                Maps_url = f"http://maps.google.com/maps?q={lat},{lon}"
                msg_content += f"• {g['Rótulo']} - {g['diesel']} € ({g['distancia']:.2f} km)\n  📍 {g['Dirección']}\n"
                full_keyboard.append([InlineKeyboardButton(f"📍 {g['Rótulo']} (Diésel)", url=Maps_url)])
            except (ValueError, KeyError) as e:
                msg_content += f"• {g['Rótulo']} - {g['diesel']} € ({g['distancia']:.2f} km)\n  📍 {g['Dirección']} (Coordenadas no disponibles)\n"
                logger.warning(f"Coordenadas inválidas para gasolinera {g.get('Rótulo', 'N/A')} en búsqueda por ubicación: {e}")

    if top_gasolina:
        if msg_content: msg_content += "\n" # Añade un salto de línea si ya hay contenido de diésel
        msg_content += f"⛽ *Top 3 Gasolina 95 cerca de ti*\n"
        for i, g in enumerate(top_gasolina):
            try:
                lat = float(g.get("Latitud", "0").replace(",", "."))
                lon = float(g.get("Longitud (WGS84)", "0").replace(",", "."))
                Maps_url = f"http://maps.google.com/maps?q={lat},{lon}"
                msg_content += f"• {g['Rótulo']} - {g['gasolina']} € ({g['distancia']:.2f} km)\n  📍 {g['Dirección']}\n"
                full_keyboard.append([InlineKeyboardButton(f"📍 {g['Rótulo']} (Gasolina)", url=Maps_url)])
            except (ValueError, KeyError) as e:
                msg_content += f"• {g['Rótulo']} - {g['gasolina']} € ({g['distancia']:.2f} km)\n  📍 {g['Dirección']} (Coordenadas no disponibles)\n"
                logger.warning(f"Coordenadas inválidas para gasolinera {g.get('Rótulo', 'N/A')} en búsqueda por ubicación: {e}")

    # Fallback final si el mensaje sigue vacío
    if not msg_content.strip():
        msg_content = "⚠️ Lo siento, no pude generar una lista detallada de gasolineras cercanas. Intenta con otra ubicación o especifica una ciudad."
        reply_markup = None
    else:
        reply_markup = InlineKeyboardMarkup(full_keyboard)

    logger.info(f"Enviando resultados de ubicación para Lat={user_lat:.4f}, Lon={user_lon:.4f}. Longitud del mensaje: {len(msg_content)} caracteres.")
    await update.message.reply_text(msg_content, parse_mode="Markdown", reply_markup=reply_markup)
    return ConversationHandler.END # Termina la conversación

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /cancelar. Termina la conversación actual."""
    logger.info(f"Comando /cancelar recibido de usuario {update.effective_user.id}")
    await update.message.reply_text("❌ Consulta cancelada.")
    return ConversationHandler.END # Termina la conversación

# --- Configuración y Ejecución Principal del Bot ---
if __name__ == "__main__":
    logger.info("Iniciando configuración de la aplicación Telegram Bot...")

    # Verifica que las variables de entorno estén configuradas
    if not TOKEN:
        logger.error("❌ Error: La variable de entorno TELEGRAM_TOKEN no está configurada. El bot no puede iniciarse.")
        exit(1) # Sale de la aplicación si no hay token
    if not WEBHOOK_URL:
        logger.error("❌ Error: La variable de entorno WEBHOOK_URL no está configurada. El bot no puede iniciarse en modo webhook.")
        # Podrías optar por salir o intentar arrancar en polling si es para desarrollo local.
        # Para Railway, el webhook es esencial, así que salimos.
        exit(1)

    app = ApplicationBuilder().token(TOKEN).build()

    # Configuración del ConversationHandler para manejar el flujo de /precio
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("precio", precio)], # Punto de entrada: cuando el usuario escribe /precio
        states={
            ESPERANDO_CIUDAD: [
                # Si el usuario envía texto (y no es otro comando), se asume que es una ciudad
                MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_ciudad),
                # Si el usuario envía una ubicación, se usa para buscar gasolineras cercanas
                MessageHandler(filters.LOCATION, recibir_ubicacion)
            ]
        },
        # Fallback: si el usuario escribe /cancelar en cualquier momento durante la conversación
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )

    # Añade los manejadores a la aplicación
    app.add_handler(CommandHandler("start", start)) # Manejador para el comando /start
    app.add_handler(conv_handler) # Añade el ConversationHandler

    # Obtiene el puerto asignado por Railway (o usa 8080 por defecto)
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Configurando webhook para URL: {WEBHOOK_URL}{TOKEN} en puerto {port}")

    # Inicia el bot en modo webhook, que es lo más común para despliegues en la nube como Railway
    app.run_webhook(
        listen="0.0.0.0", # Escucha en todas las interfaces de red
        port=port,        # Puerto en el que la aplicación escuchará las peticiones de Telegram
        url_path=TOKEN,   # Ruta URL específica para tu webhook (parte final de la URL)
        webhook_url=f"{WEBHOOK_URL}{TOKEN}" # URL completa que Telegram usará para enviar actualizaciones
    )
    logger.info("Aplicación Telegram Bot iniciada y escuchando por webhooks.")