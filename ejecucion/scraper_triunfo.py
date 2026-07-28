# -*- coding: utf-8 -*-
"""
Scraper Triunfo Seguros — Cotizador Angular + API REST.

ESTRATEGIA:
- API pública de Triunfo para buscar marca/modelo/version/city (sin UI)
- Playwright SOLO para obtener token reCAPTCHA desde la página /applicant
- POST directo a la API con los campos correctos descubiertos

La API NO tiene Cloudflare blocking — funciona directo con requests.

Autor: Sistema Agéntico GPY
Fecha: 2026-07-27
"""

import asyncio
import json
import os
import re
import traceback
from datetime import datetime

import requests

URL_COTIZADOR = "https://cotizador.triunfonet.com.ar"
URL_API = "https://api-cotizador.triunfonet.com.ar"
FILTER_B64 = "eyJvcmRlciI6InBvcHVsYXJpdHkgREVTQyJ9"  # {"order":"popularity DESC"}
RECAPTCHA_SITE_KEY = "6LeXk2YfAAAAAPILVCWT7BWz-UTAmiA4b26Utt5f"

TIMEOUT_NAVEGACION = 60000


async def _delay(minimo=0.5, maximo=1.5):
    import random
    await asyncio.sleep(random.uniform(minimo, maximo))


# ─── API Helpers (sin Playwright) ──────────────────────────────────────────

def api_get_brands() -> list:
    """Obtiene todas las marcas de autos."""
    resp = requests.get(
        f"{URL_API}/car-brands",
        params={"filter": FILTER_B64},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def api_get_brand_models(brand_id: str) -> dict:
    """Obtiene los modelos de una marca (con include vehicleModels)."""
    import base64
    model_filter = json.dumps({"include": [{"relation": "vehicleModels"}]})
    encoded = base64.b64encode(model_filter.encode()).decode()
    resp = requests.get(
        f"{URL_API}/car-brands/{brand_id}",
        params={"filter": encoded},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def api_get_versions(model_id: str) -> list:
    """Obtiene las versiones de un modelo."""
    resp = requests.get(
        f"{URL_API}/vehicle-models/{model_id}/versions",
        params={"filter": FILTER_B64},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def api_get_cities(query: str, limit: int = 5) -> list:
    """Busca ciudades por nombre."""
    import base64
    city_filter = json.dumps({
        "where": {"name": {"like": query.upper()}},
        "limit": limit,
    })
    encoded = base64.b64encode(city_filter.encode()).decode()
    resp = requests.get(
        f"{URL_API}/cities",
        params={"filter": encoded},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _find_brand(marca: str) -> dict | None:
    """Busca una marca por nombre (fuzzy match)."""
    brands = api_get_brands()
    marca_upper = marca.upper().strip()

    for b in brands:
        if b["name"].upper() == marca_upper:
            return b

    for b in brands:
        if marca_upper in b["name"].upper() or b["name"].upper() in marca_upper:
            return b

    return None


def _find_model(brand_data: dict, modelo: str, anio: int) -> dict | None:
    """Busca un modelo por nombre y año dentro de la marca."""
    models = brand_data.get("vehicleModels", brand_data.get("models", []))
    modelo_upper = modelo.upper().strip()

    for m in models:
        name_match = modelo_upper in m.get("name", "").upper() or m.get("name", "").upper() in modelo_upper
        year_ok = m.get("priceFrom", 0) <= anio <= m.get("priceTo", 9999)
        if name_match and year_ok:
            return m

    for m in models:
        if modelo_upper in m.get("name", "").upper() or m.get("name", "").upper() in modelo_upper:
            return m

    return None


def _find_version(versions: list, version: str) -> dict | None:
    """Busca una versión por nombre (fuzzy match)."""
    if not version:
        return versions[0] if versions else None

    version_upper = version.upper().strip()

    for v in versions:
        if v.get("name", "").upper() == version_upper:
            return v

    for v in versions:
        vname = v.get("name", "").upper()
        if version_upper in vname or vname in version_upper:
            return v

    version_words = set(version_upper.split())
    for v in versions:
        vname = v.get("name", "").upper()
        vwords = set(vname.split())
        if len(version_words & vwords) >= 2:
            return v

    return versions[0] if versions else None


def _find_city(localidad: str) -> dict | None:
    """Busca una ciudad por nombre."""
    try:
        cities = api_get_cities(localidad, limit=10)
    except Exception:
        return None

    if not cities:
        return None

    localidad_upper = localidad.upper().strip()
    for c in cities:
        if localidad_upper in c.get("name", "").upper():
            return c

    return cities[0] if cities else None


# ─── reCAPTCHA Token via Playwright ────────────────────────────────────────

async def _obtener_token_recaptcha(marca: str, modelo: str, version_id: str, anio: int) -> str | None:
    """
    Abre la página /applicant en Playwright y extrae un token reCAPTCHA v3 válido.
    Solo necesitamos la página para que reCAPTCHA genere el token.
    """
    from playwright.async_api import async_playwright

    applicant_url = (
        f"{URL_COTIZADOR}/applicant"
        f"?brandName={marca}"
        f"&yearName={anio}"
        f"&modelName={modelo}"
        f"&versionId={version_id}"
        f"&usage=0"
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="es-AR",
        )
        page = await context.new_page()

        try:
            await page.goto(applicant_url, timeout=TIMEOUT_NAVEGACION)
            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            await asyncio.sleep(3)

            token = await page.evaluate("""() => {
                return new Promise((resolve) => {
                    try {
                        if (!window.grecaptcha || !window.grecaptcha.execute) {
                            resolve(null);
                            return;
                        }
                        window.grecaptcha.ready(function() {
                            window.grecaptcha.execute('%s', {action: 'submit'}).then(resolve).catch(e => resolve(null));
                        });
                    } catch(e) {
                        resolve(null);
                    }
                });
            }""" % RECAPTCHA_SITE_KEY)

            return token

        except Exception as e:
            print(f"  ⚠️ Error obteniendo token reCAPTCHA: {e}")
            return None
        finally:
            await browser.close()


# ─── Scraping Principal ────────────────────────────────────────────────────

async def scrape_triunfo(
    marca: str,
    modelo: str,
    version: str = "",
    anio: int = 2024,
    gnc: bool = False,
    provincia: str = "Buenos Aires",
    localidad: str = "Capital Federal",
) -> dict:
    """
    Scraping del cotizador de Triunfo Seguros.

    Flujo:
    1. API: buscar marca, modelo, version, city IDs
    2. Playwright: obtener token reCAPTCHA desde /applicant
    3. POST directo a API /estimates con los campos correctos
    4. Parsear respuesta

    Retorna dict con cotizaciones, total, exito, error.
    """
    print(f"🚗 [TRIUNFO] Cotización: {marca} {modelo} {version} {anio}", flush=True)
    print(f"  📍 Provincia: {provincia}, Localidad: {localidad}", flush=True)
    resultado = {
        "cotizaciones": [],
        "total_cotizaciones": 0,
        "exito": False,
        "marca": marca,
        "modelo": modelo,
        "version": version,
        "anio": anio,
    }

    # ── Paso 1: Buscar IDs via API ────────────────────────────────────
    print("  📡 Buscando marca en API...", flush=True)
    try:
        brand_data = _find_brand(marca)
        if not brand_data:
            resultado["error"] = f"Marca no encontrada: {marca}"
            print(f"    ❌ {resultado['error']}", flush=True)
            return resultado
        print(f"    ✅ Marca: {brand_data['name']} (id={brand_data['id']})", flush=True)
    except Exception as e:
        resultado["error"] = f"Error consultando API de marcas: {e}"
        print(f"    ❌ {resultado['error']}", flush=True)
        traceback.print_exc()
        return resultado

    print("  📡 Buscando modelo en API...", flush=True)
    try:
        brand_full = api_get_brand_models(brand_data["id"])
        model_data = _find_model(brand_full, modelo, anio)
        if not model_data:
            resultado["error"] = f"Modelo no encontrado: {modelo} (año {anio})"
            print(f"    ❌ {resultado['error']}", flush=True)
            return resultado
        print(f"    ✅ Modelo: {model_data['name']} (id={model_data['id']})", flush=True)
    except Exception as e:
        resultado["error"] = f"Error consultando API de modelos: {e}"
        print(f"    ❌ {resultado['error']}", flush=True)
        traceback.print_exc()
        return resultado

    print("  📡 Buscando versiones en API...", flush=True)
    try:
        versions = api_get_versions(model_data["id"])
        version_data = _find_version(versions, version)
        if not version_data:
            resultado["error"] = f"Versión no encontrada: {version}"
            print(f"    ❌ {resultado['error']}", flush=True)
            return resultado
        print(f"    ✅ Versión: {version_data['name']} (id={version_data['id']})", flush=True)
    except Exception as e:
        resultado["error"] = f"Error consultando API de versiones: {e}"
        print(f"    ❌ {resultado['error']}", flush=True)
        traceback.print_exc()
        return resultado

    print("  📡 Buscando ciudad en API...")
    city_data = _find_city(localidad)
    if not city_data:
        # La Plata (capital de Buenos Aires) es cubierta por Triunfo; CABA no
        print(f"    ⚠️ Ciudad no encontrada: {localidad}, usando La Plata por defecto")
        city_data = {
            "id": "5c3cdc39b3728814ddcbfc9a",
            "name": "Campo la Plata",
            "zipCode": "7623",
            "province": "Buenos Aires",
        }
    print(f"    ✅ Ciudad: {city_data['name']}, {city_data['province']} (id={city_data['id']})")

    # Ciudad de respaldo si la principal no está cubierta
    LA_PLATA_DEFAULT = {
        "id": "5c3cdc39b3728814ddcbfc9a",
        "name": "Campo la Plata",
        "zipCode": "7623",
        "province": "Buenos Aires",
    }

    # ── Paso 2: Obtener token reCAPTCHA ───────────────────────────────
    print("  🔑 Obteniendo token reCAPTCHA...")
    token = await _obtener_token_recaptcha(
        marca=brand_data["name"],
        modelo=model_data["name"],
        version_id=version_data["id"],
        anio=anio,
    )
    if not token:
        resultado["error"] = "No se pudo obtener token reCAPTCHA"
        return resultado
    print(f"    ✅ Token reCAPTCHA: {token[:50]}...")

    # ── Paso 3: POST a /estimates ─────────────────────────────────────
    print("  📡 Enviando cotización a API...")

    phone_code = "11"
    phone_number = "55551234"
    phone_full = f"{phone_code}{phone_number}"

    payload = {
        "captcha": token,
        "versionId": version_data["id"],
        "clientEmail": "cotizacion@temp.com",
        "clientLastName": "Cliente",
        "clientName": "Cotización",
        "clientPhoneNumber": phone_full,
        "cityId": city_data["id"],
        "year": anio,
        "zeroKm": False,
        "vehicleType": "car",
        "usage": "0",
    }

    try:
        # Intentar con la ciudad seleccionada primero, luego La Plata como fallback
        cities_to_try = [city_data]
        if city_data.get("id") != LA_PLATA_DEFAULT["id"]:
            cities_to_try.append(LA_PLATA_DEFAULT)

        for attempt_city in cities_to_try:
            payload["cityId"] = attempt_city["id"]

            resp = requests.post(
                f"{URL_API}/estimates",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            print(f"    📊 Status: {resp.status_code} (ciudad: {attempt_city['name']})")

            if resp.status_code == 200:
                data = resp.json()
                cotizaciones = _parsear_respuesta_api(data)
                if cotizaciones:
                    resultado["cotizaciones"] = cotizaciones
                    resultado["total_cotizaciones"] = len(cotizaciones)
                    resultado["exito"] = True
                    print(f"    ✅ {len(cotizaciones)} cotizaciones obtenidas")
                    break
                else:
                    resultado["error"] = "Respuesta OK pero sin cotizaciones parseables"
                    resultado["raw_response"] = data
                    print(f"    ⚠️ Sin cotizaciones: {json.dumps(data, indent=2)[:500]}")
                    break
            else:
                try:
                    error_data = resp.json()
                    error_msg = error_data.get("message", str(error_data))
                    error_code = error_data.get("errorCode", "")
                    # Si es error de zona, intentar con La Plata
                    if "zona" in error_msg.lower() and attempt_city.get("id") != LA_PLATA_DEFAULT["id"]:
                        print(f"    ⚠️ Zona no cubierta, reintentando con La Plata...")
                        continue
                    resultado["error"] = f"API error {resp.status_code}: {error_msg}"
                    resultado["error_code"] = error_code
                    resultado["raw_response"] = error_data
                    print(f"    ❌ Error: {error_msg}")
                    break
                except Exception:
                    resultado["error"] = f"API error {resp.status_code}: {resp.text[:500]}"
                    print(f"    ❌ Error raw: {resp.text[:500]}")
                    break

    except requests.Timeout:
        resultado["error"] = "Timeout al contactar API de Triunfo"
    except requests.ConnectionError:
        resultado["error"] = "Error de conexión a API de Triunfo"
    except Exception as e:
        resultado["error"] = f"Error inesperado: {e}"
        traceback.print_exc()

    return resultado


def _parsear_respuesta_api(data: dict) -> list:
    """
    Parsea la respuesta JSON de /estimates en cotizaciones normalizadas.
    Respuesta exitosa: { id, estimateNumber, quotes: [...] }
    """
    cotizaciones = []

    # Direct estimates response with quotes array
    if isinstance(data, dict) and "quotes" in data:
        estimate_id = data.get("id", "")
        estimate_number = data.get("estimateNumber", "")
        insured_sum = data.get("insuredSum", "")
        vehicle_type = data.get("vehicleType", "")

        for q in data["quotes"]:
            if not isinstance(q, dict):
                continue

            coverage = q.get("coverage", {})
            payment_desc = q.get("triunfoPaymentDesc", "")
            monthly_fee = float(q.get("monthlyFee", 0))
            coverage_name = coverage.get("name", "")
            coverage_code = coverage.get("coverageNom", q.get("coverageNom", ""))

            extras = coverage.get("extras", [])
            extra_names = [e.get("name", "") for e in extras if e.get("name")]

            cot = {
                "aseguradora": "Triunfo Seguros",
                "plan": coverage_name,
                "codigo_cobertura": coverage_code,
                "metodo_pago": payment_desc,
                "precio_mensual": monthly_fee,
                "precio_texto": f"${monthly_fee:,.2f}" if monthly_fee > 0 else "",
                "suma_asegurada": insured_sum,
                "estimate_id": estimate_id,
                "estimate_number": estimate_number,
                "extras": extra_names,
                "cobertura_detalle": coverage.get("risks", []),
            }

            cotizaciones.append(cot)

        return cotizaciones

    # Fallback: list of items
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("estimates", data.get("results", data.get("quotes", [])))
        if not isinstance(items, list):
            items = [data]
    else:
        return cotizaciones

    for item in items:
        if not isinstance(item, dict):
            continue

        cot = {
            "aseguradora": "Triunfo Seguros",
            "plan": item.get("planName", item.get("plan", item.get("name", ""))),
            "precio_mensual": _extract_price(item),
            "precio_texto": "",
            "cobertura": item.get("coverage", item.get("description", "")),
            "detalle": item,
        }

        price = cot["precio_mensual"]
        if price > 0:
            cot["precio_texto"] = f"${price:,.2f}"

        cotizaciones.append(cot)

    return cotizaciones


def _extract_price(item: dict) -> float:
    """Extrae el precio mensual de un item de cotización."""
    for key in ["monthlyPremium", "monthlyPrice", "premium", "price", "cuota", "totalPremium"]:
        val = item.get(key)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                continue

    if "amounts" in item and isinstance(item["amounts"], dict):
        for key in ["monthly", "total", "premium"]:
            val = item["amounts"].get(key)
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    continue

    return 0.0


# ── Para testing directo ────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio

    async def main():
        resultado = await scrape_triunfo(
            marca="Fiat",
            modelo="Cronos",
            version="1.3 GSE",
            anio=2023,
        )
        print(json.dumps(resultado, indent=2, ensure_ascii=False))

    asyncio.run(main())
