"""
Backend Multicotizador 123Seguro — Desplegado en Coolify (VPS).
Versión minimalista: solo endpoints de cotización + scraper con Playwright.
"""
import os
import sys
import json
import asyncio
import requests
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from dotenv import load_dotenv
from pyairtable import Table

load_dotenv()

app = FastAPI(title="Multicotizador Backend")

# ─── Airtable Config ───────────────────────────────────────────────────────
API_KEY = os.getenv("AIRTABLE_API_KEY")
BASE_ID = os.getenv("AIRTABLE_BASE_ID")
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

TABLE_MAPPING = {
    "PROSPECTOS_MULTICOTIZADOR": os.getenv(
        "TABLE_PROSPECTOS_MULTICOTIZADOR", "PROSPECTOS MULTICOTIZADOR"
    ),
}


def get_table(table_name_key):
    if not API_KEY or not BASE_ID:
        return None
    table_name = TABLE_MAPPING.get(table_name_key, table_name_key)
    return Table(API_KEY, BASE_ID, table_name)


def build_airtable_request(table_name_key):
    if not API_KEY or not BASE_ID:
        raise HTTPException(status_code=500, detail="Error de configuración de base de datos")
    table_name = TABLE_MAPPING.get(table_name_key, table_name_key)
    url = f"https://api.airtable.com/v0/{BASE_ID}/{table_name}"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    return table_name, url, headers


def create_airtable_record(table_name_key, fields, typecast=False):
    table = get_table(table_name_key)
    if not table:
        return None
    return table.create(fields, typecast=typecast)


# ─── CORS ──────────────────────────────────────────────────────────────────
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ─── Scraping Background ──────────────────────────────────────────────────
def ejecutar_scraping_background(
    marca: str,
    modelo: str,
    version: str,
    anio: int,
    gnc: bool,
    provincia: str,
    localidad: str,
    id_prospecto: str,
):
    import json as _json

    print(f"🔄 [BACKGROUND] Iniciando scraping para prospecto {id_prospecto}")

    try:
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "ejecucion"))
        from scraper_123seguro import scrape_123seguro
    except ImportError as e:
        print(f"❌ [BACKGROUND] Error importando scraper: {e}")
        return

    try:
        resultado = asyncio.run(scrape_123seguro(
            marca=marca,
            modelo=modelo,
            version=version,
            anio=anio,
            gnc=gnc,
            provincia=provincia,
            localidad=localidad,
        ))
    except Exception as e:
        print(f"❌ [BACKGROUND] Error en scraping: {e}")
        resultado = {
            "cotizaciones": [],
            "total_cotizaciones": 0,
            "exito": False,
            "error": str(e),
        }

    if id_prospecto:
        try:
            campos_update = {
                "TOTAL_COTIZACIONES": int(resultado.get("total_cotizaciones", 0)),
                "ESTADO": "cotizado",
            }
            if resultado.get("cotizaciones"):
                campos_update["JSON_COTIZACIONES"] = _json.dumps(
                    resultado["cotizaciones"], ensure_ascii=False, default=str
                )

            table_name, url, headers = build_airtable_request("PROSPECTOS_MULTICOTIZADOR")
            response = requests.patch(
                f"{url}/{id_prospecto}",
                headers=headers,
                json={"fields": campos_update},
                timeout=10,
            )
            if response.status_code == 200:
                print(f"✅ [BACKGROUND] Prospecto {id_prospecto} actualizado con {resultado.get('total_cotizaciones', 0)} cotizaciones")
            else:
                print(f"⚠️ [BACKGROUND] Error actualizando Airtable: {response.status_code}")
        except Exception as e:
            print(f"⚠️ [BACKGROUND] Error guardando resultados: {e}")

    print(f"🏁 [BACKGROUND] Scraping completado para {id_prospecto}")


# ─── Models ────────────────────────────────────────────────────────────────
class CotizarRequest(BaseModel):
    marca: str
    modelo: str
    version: str = ""
    anio: int
    gnc: bool = False
    provincia: str = "Buenos Aires"
    localidad: str = "Capital Federal"
    cliente_nombre: str = ""
    cliente_whatsapp: str = ""
    cliente_email: str = ""
    cliente_patente: str = ""


class ElegirCotizacionRequest(BaseModel):
    id_prospecto: str
    cotizacion_elegida: str


# ─── Endpoints ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "online",
        "service": "multicotizador-backend",
        "playwright": _check_playwright(),
    }


def _check_playwright():
    try:
        from playwright.async_api import async_playwright
        return "installed"
    except ImportError:
        return "not_installed"


@app.post("/api/cotizar-123seguro")
async def cotizar_123seguro(req: CotizarRequest, background_tasks: BackgroundTasks):
    id_prospecto = None

    if req.cliente_nombre or req.cliente_whatsapp:
        try:
            campos_iniciales = {
                "NOMBRE": req.cliente_nombre,
                "WHATSAPP": req.cliente_whatsapp,
                "EMAIL_CLIENTE": req.cliente_email,
                "PATENTE": req.cliente_patente,
                "MARCA": req.marca,
                "MODELO": req.modelo,
                "VERSION": req.version,
                "AÑO": str(req.anio),
                "PROVINCIA": req.provincia,
                "LOCALIDAD": req.localidad,
                "ESTADO": "nuevo",
                "TOTAL_COTIZACIONES": 0,
                "FUENTE": "linktree-multicotizador",
            }
            if req.gnc:
                campos_iniciales["GNC"] = True

            record = create_airtable_record("PROSPECTOS_MULTICOTIZADOR", campos_iniciales, typecast=True)
            id_prospecto = record.get("id") if record else None
            print(f"✅ Prospecto creado en Airtable: {id_prospecto}")
        except Exception as e:
            print(f"⚠️ Error guardando prospecto inicial: {e}")

    if id_prospecto:
        background_tasks.add_task(
            ejecutar_scraping_background,
            marca=req.marca,
            modelo=req.modelo,
            version=req.version,
            anio=req.anio,
            gnc=req.gnc,
            provincia=req.provincia,
            localidad=req.localidad,
            id_prospecto=id_prospecto,
        )
        print(f"🚀 Scraping disparado en background para {id_prospecto}")

    return {
        "id_gestion": id_prospecto,
        "estado": "procesando",
        "mensaje": "Tu cotización está siendo procesada. Te contactaremos con los resultados.",
        "vehiculo": {
            "marca": req.marca,
            "modelo": req.modelo,
            "version": req.version,
            "anio": req.anio,
        },
    }


@app.get("/api/cotizar-status/{id_prospecto}")
async def cotizar_status(id_prospecto: str):
    try:
        table_name, url, headers = build_airtable_request("PROSPECTOS_MULTICOTIZADOR")
        response = requests.get(f"{url}/{id_prospecto}", headers=headers, timeout=10)

        if response.status_code != 200:
            return {"error": "Prospecto no encontrado", "estado": "error"}

        record = response.json()
        fields = record.get("fields", {})

        cotizaciones = []
        json_cotizaciones = fields.get("JSON_COTIZACIONES", "")
        if json_cotizaciones:
            try:
                cotizaciones = json.loads(json_cotizaciones)
            except Exception:
                pass

        return {
            "id_gestion": id_prospecto,
            "estado": fields.get("ESTADO", "desconocido"),
            "total_cotizaciones": fields.get("TOTAL_COTIZACIONES", 0),
            "cotizaciones": cotizaciones,
            "vehiculo": {
                "marca": fields.get("MARCA", ""),
                "modelo": fields.get("MODELO", ""),
                "version": fields.get("VERSION", ""),
                "anio": fields.get("AÑO", ""),
            },
        }
    except Exception as e:
        return {"error": str(e), "estado": "error"}


@app.post("/api/cotizar-elegir")
async def cotizar_elegir(req: ElegirCotizacionRequest):
    try:
        table_name, url, headers = build_airtable_request("PROSPECTOS_MULTICOTIZADOR")

        campos_update = {
            "COTIZACION_ELEGIDA": req.cotizacion_elegida,
            "ESTADO": "CLIENTE_INTERESADO",
            "FECHA_ELECCION": datetime.now().isoformat(),
        }

        response = requests.patch(
            f"{url}/{req.id_prospecto}",
            headers=headers,
            json={"fields": campos_update},
            timeout=10,
        )

        if response.status_code == 200:
            return {
                "exito": True,
                "mensaje": "¡Excelente elección! Un asesor se comunicará contigo pronto.",
                "id_gestion": req.id_prospecto,
            }
        else:
            return {"exito": False, "error": "Error al guardar selección"}
    except Exception as e:
        return {"exito": False, "error": str(e)}
