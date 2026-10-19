"""Configuración de la evidencia diaria de alertas de precio.

Todo lo que se puede querer ajustar sin tocar la lógica está aquí: tablas, plazos, límites, colores y textos.
"""
import datetime
import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()  # en local lee el .env; en Cloud Run las variables vienen del job

PROJECT_ID = "proan-quantrue"
ZONA = ZoneInfo("America/Mexico_City")

# --- Tablas de BigQuery -------------------------------------------------------------------------------------------
# Alertas tal como se enviaron cada día (las crea el DAG de Airflow, una por día de venta). Se usan estas y no
# PRECIOS_AMPLIADO porque PRECIOS_AMPLIADO se recalcula cada día y cambia las alertas de días pasados.
TABLA_ALERTAS_DIA = "proan-quantrue.D60_REPORTING.price_alerts_{fecha}"            # fecha = AAAAMMDD
TABLA_PRECIOS = "proan-quantrue.D60_REPORTING.PRECIOS_AMPLIADO"                     # resto de líneas de la factura
TABLA_FACTURAS_SAP = "proan-quantrue.D30_INTEGRATION.sap_2lis_13_vditm_billing_document_item"  # histórico de precios
TABLA_CFDI = "proan-quantrue.D30_INTEGRATION.cfdi_completo"                          # facturas timbradas
# Tabla de control: qué alertas ya se enviaron con su evidencia (la crea crear_tablas.sql, una sola vez)
TABLA_ENVIADAS = "proan-quantrue.D60_REPORTING.evidencia_precios_enviadas"

# --- Reglas del envío ---------------------------------------------------------------------------------------------
PLAZO_DIAS = 10          # días que una alerta espera su factura; después se envía sin ella
TOP_POR_DIA = 10         # alertas por día de venta que llevan evidencia (las de mayor impacto)
MAX_ALERTAS_CORREO = 20  # tope de alertas por correo (por sociedad, dentro del correo); las que no entren salen al día siguiente
MESES_HISTORICO = 6      # meses de histórico en la gráfica
DIAS_REFERENCIA = 30     # antigüedad máxima de la factura "a precio habitual"
TOLERANCIA_REFERENCIA = .05   # la factura de referencia debe estar a ±5 % del precio esperado
CLIENTES_EPISODIO = 5    # mismo material y precio en 5 clientes o más -> una sola alerta ("episodio masivo")

# Sociedades con su RFC emisor (para cruzar la factura SAP con el CFDI)
RFC_SOCIEDAD = {"AME": "AME940210Q80", "CCP": "CPR170310DSA", "DBC": "DBC040909524", "PAL": "PAL1212136K0",
                "PAN": "PAN921013AK7", "PAT": "PAT9110289PA", "SCO1": "SCO14061972A"}
RFC_GRUPO = set(RFC_SOCIEDAD.values())   # ventas a estas empresas no sirven como "precio habitual"
RFC_PUBLICO = "XAXX010101000"

# --- Fecha de ejecución -------------------------------------------------------------------------------------------
# En producción es "hoy" en México. Para probar como si fuera otro día: FECHA_EJECUCION=2026-09-08. En ese caso solo
# se tienen en cuenta las facturas que ya habían llegado a esa hora (CORTE_HORA), para que la prueba sea realista.
ZONA_ENVIO = ZoneInfo("Europe/Madrid")
CORTE_HORA = 17  # hora de España a la que se ejecuta el job (deploy.sh)
_fecha_env = os.environ.get("FECHA_EJECUCION", "").strip()
HOY = (datetime.date.fromisoformat(_fecha_env) if _fecha_env
       else datetime.datetime.now(ZONA).date())
CORTE_CFDI = (datetime.datetime.combine(HOY, datetime.time(CORTE_HORA, 0), ZONA_ENVIO) if _fecha_env else None)

# --- Correo -------------------------------------------------------------------------------------------------------
FIRESTORE_DATABASE_ID = os.environ.get("FIRESTORE_DATABASE_ID", "proan-lista-mails").strip()
FIRESTORE_LISTS_COLLECTION = os.environ.get("FIRESTORE_LISTS_COLLECTION", "lists").strip()
LISTA_CORREO = os.environ.get("ALERTAS_EVIDENCIA_LIST_ID", "alertas-precios-evidencia").strip()
SENDGRID_FROM_EMAIL_DEFAULT = "noreply@proan.com"
DRY_RUN = os.environ.get("ALERTAS_EVIDENCIA_EMAIL_DRY_RUN", "false").strip().lower() in {"1", "true", "yes"}
ENVIAR_SI_VACIO = False  # si un día no hay evidencias nuevas, no se manda correo
ASUNTO = "Evidencia de alertas de precio · {fecha} · {n} alerta{s}"

# --- Salida -------------------------------------------------------------------------------------------------------
# En Cloud Run solo se puede escribir en /tmp: deploy.sh inyecta OUTPUT_DIR=/tmp/salidas
OUTPUT_DIR = (os.environ.get("OUTPUT_DIR", "").strip()
              or os.path.join(os.path.dirname(os.path.abspath(__file__)), "salidas"))

# --- Colores ------------------------------------------------------------------------------------------------------
INK, MUTED, LINE, BAND = "#1b1f1d", "#5f6763", "#dfe3e1", "#f3f5f4"
ACCENT, CRIT, WARN = "#1d5d7a", "#c23434", "#9a6400"
C_CLIENTE, C_OTROS, C_ALERTA, C_ZONA = "#2a78d6", "#9aa39f", "#d03b3b", "#fbe3e3"
# Réplica de la factura impresa
AZUL_FACTURA, BARRA_FACTURA, ROJO_FACTURA, BORDE_FACTURA = "#1f2f8f", "#1b2f6b", "#e10600", "#1f2a6b"
# Color de la factura según la sociedad que la emite (sustituye al azul marino en barras, bordes y nombre del emisor).
# El rojo de la barra "FACTURA" y de los recuadros del producto no cambia. Sociedades sin color: azul marino.
COLOR_SOCIEDAD = {
    # Rojo
    "SCO1": "#c8102e", "MAL": "#c8102e", "MPE": "#c8102e",   # rojo puro
    "PAN": "#1b2f6b",                                         # azul marino (como la factura original)
    # Marrón / tierra
    "PAL": "#6d4c35", "FAG": "#8b6b4a",
    # Dorado
    "PRA": "#a87b0a",
    # Azul
    "CCP": "#2f6db5", "SAP": "#2f6db5",                       # azul medio
    "AME": "#1b2f6b",                                         # azul marino
    # Verde / verde azulado
    "DBC": "#1c7a1c",                                         # verde de su factura impresa
    "HEGP": "#2a8c82", "GSI": "#1f5f6b",                      # verde azulado y petróleo
    "BAG": "#6b7a2a",                                         # verde oliva
    # Gris
    "ROMM": "#6b6f72",
}

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
MES_CORTO = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
FORMA_PAGO = {"01": "Efectivo", "02": "Cheque nominativo", "03": "Transferencia", "04": "Tarjeta de crédito",
              "28": "Tarjeta de débito", "99": "Por definir"}
USO_CFDI = {"G01": "Adquisición de mercancías", "G03": "Gastos en general", "S01": "Sin efectos fiscales",
            "P01": "Por definir", "CP01": "Pagos"}
UNIDAD = {"KGM": "kg", "XBX": "caja", "H87": "pieza", "XPK": "paquete"}
