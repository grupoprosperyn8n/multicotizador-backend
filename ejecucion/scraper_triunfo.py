# -*- coding: utf-8 -*-
"""
Scraper Triunfo Seguros — Cotizador Angular via Playwright UI.

ESTRATEGIA:
- Todo el flujo via Playwright (navegador real)
- Cloudflare bloquea requests directos desde VPS/datacenter IPs
- Playwright maneja cookies, JavaScript y challenges automáticamente
- Flujo: navegar → seleccionar marca/modelo/version → llenar form → extraer resultados

Autor: Sistema Agéntico GPY
Fecha: 2026-07-28
"""

import asyncio
import json
import re
import traceback

URL_COTIZADOR = "https://cotizador.triunfonet.com.ar"
TIMEOUT_NAVEGACION = 60000


async def _delay(minimo=0.5, maximo=1.5):
    import random
    await asyncio.sleep(random.uniform(minimo, maximo))


async def _click_grid_item(page, texto: str):
    """Click en un elemento de grilla del modal Angular."""
    await _delay(1.0, 2.0)
    result = await page.evaluate("""
        (texto) => {
            const all = document.querySelectorAll('.col-12, .col-6, .col-md-6, .col-md-4');
            for (const el of all) {
                const t = el.innerText.trim();
                if (t === texto && el.offsetHeight > 5) {
                    el.click();
                    return 'clicked:' + t;
                }
            }
            const allEl = document.querySelectorAll('*');
            for (const el of allEl) {
                if (el.innerText && el.innerText.trim() === texto && el.offsetHeight > 5 && el.offsetWidth > 5) {
                    el.click();
                    return 'clicked_fallback:' + el.tagName;
                }
            }
            return 'not_found';
        }
    """, texto)
    return result.startswith("clicked")


async def _select_brand(page, marca: str):
    """Selecciona marca en el modal del cotizador."""
    await page.locator('input[placeholder="Marca"]').first.click()
    await asyncio.sleep(2)
    try:
        await page.locator(f'span.brand-name:has-text("{marca}")').first.click(timeout=5000)
        return True
    except Exception:
        pass
    return await _click_grid_item(page, marca.upper())


async def _select_year(page, anio: int):
    """Selecciona año en el modal."""
    await page.locator('input[placeholder="Año"]').first.click()
    await asyncio.sleep(2)
    return await _click_grid_item(page, str(anio))


async def _select_model(page, modelo: str):
    """Selecciona modelo en el modal."""
    await page.locator('input[placeholder="Modelo"]').first.click()
    await asyncio.sleep(3)
    return await _click_grid_item(page, modelo.upper())


async def _select_version(page, version_name: str):
    """Selecciona versión en el modal."""
    await page.locator('input[placeholder="Version"], input[placeholder="Versión"]').first.click()
    await asyncio.sleep(3)
    result = await page.evaluate("""
        (texto) => {
            const all = document.querySelectorAll('.col-12, .col-6, .col-md-6');
            for (const el of all) {
                const t = el.innerText.trim();
                if (t.length > 5 && !t.startsWith('Versiones') && el.offsetHeight > 5) {
                    if (!texto || t.toUpperCase().includes(texto.toUpperCase())) {
                        el.click();
                        return 'clicked:' + t;
                    }
                }
            }
            for (const el of all) {
                const t = el.innerText.trim();
                if (t.length > 5 && !t.startsWith('Versiones') && el.offsetHeight > 5) {
                    el.click();
                    return 'clicked_first:' + t;
                }
            }
            return 'not_found';
        }
    """, version_name)
    return result.startswith("clicked")


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
    Scraping del cotizador de Triunfo Seguros via Playwright UI.

    Flujo:
    1. Navegar al cotizador
    2. Seleccionar marca/año/modelo/version via UI
    3. Llenar formulario de applicant
    4. Extraer cotizaciones de la página de resultados

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

    from playwright.async_api import async_playwright
    from playwright_stealth import stealth_async

    # Paso 0: obtener cookies de Cloudflare via cloudscraper
    print("  🔑 Obteniendo cookies via cloudscraper...", flush=True)
    cf_cookies = {}
    try:
        import cloudscraper
        scraper_cf = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        resp = scraper_cf.get(f"{URL_COTIZADOR}/?product=car", timeout=30)
        print(f"    📊 cloudscraper status: {resp.status_code}", flush=True)
        cf_cookies = dict(scraper_cf.cookies)
        print(f"    ✅ Cookies obtenidas: {len(cf_cookies)}", flush=True)
        for k, v in cf_cookies.items():
            print(f"       - {k}: {str(v)[:30]}...", flush=True)
    except Exception as e:
        print(f"    ⚠️ cloudscraper falló: {e}", flush=True)

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
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale="es-AR",
            timezone_id="America/Argentina/Buenos_Aires",
        )

        # Inyectar cookies de Cloudflare en el contexto de Playwright
        if cf_cookies:
            pw_cookies = []
            for name, value in cf_cookies.items():
                pw_cookies.append({
                    "name": name,
                    "value": str(value),
                    "domain": ".triunfonet.com.ar",
                    "path": "/",
                })
            await context.add_cookies(pw_cookies)
            print(f"    ✅ {len(pw_cookies)} cookies inyectadas en Playwright", flush=True)

        page = await context.new_page()
        await stealth_async(page)

        try:
            # ── Navegar al cotizador ──────────────────────────────────
            print("  🌐 Navegando al cotizador...", flush=True)
            await page.goto(f"{URL_COTIZADOR}/?product=car", timeout=TIMEOUT_NAVEGACION, wait_until="domcontentloaded")
            
            # Esperar challenge de Cloudflare
            print("  ⏳ Esperando Cloudflare...", flush=True)
            await asyncio.sleep(10)
            
            title = await page.title()
            if "momento" in title.lower() or "checking" in title.lower():
                print("  ⏳ Challenge activo, esperando más...", flush=True)
                await asyncio.sleep(15)
            
            print(f"  📄 Título: {await page.title()}", flush=True)

            # ── Seleccionar vehículo via UI ───────────────────────────
            print(f"  📌 Seleccionando Marca ({marca})...", flush=True)
            if not await _select_brand(page, marca):
                resultado["error"] = f"No se pudo seleccionar marca {marca}"
                return resultado
            await _delay(1.0, 2.0)

            print(f"  📌 Seleccionando Año ({anio})...", flush=True)
            if not await _select_year(page, anio):
                resultado["error"] = f"No se pudo seleccionar año {anio}"
                return resultado
            await _delay(1.0, 2.0)

            print(f"  📌 Seleccionando Modelo ({modelo})...", flush=True)
            if not await _select_model(page, modelo):
                resultado["error"] = f"No se pudo seleccionar modelo {modelo}"
                return resultado
            await _delay(1.0, 2.0)

            print(f"  📌 Seleccionando Versión...", flush=True)
            if not await _select_version(page, version):
                resultado["error"] = "No se pudo seleccionar versión"
                return resultado
            await _delay(1.0, 2.0)

            # ── Click Cotizar ─────────────────────────────────────────
            print("  📌 Click Cotizar...", flush=True)
            await page.evaluate("""
                () => {
                    const btn = document.getElementById('estimateBtn');
                    if (btn) { btn.disabled = false; btn.click(); }
                }
            """)
            await asyncio.sleep(5)

            # ── Verificar que llegamos a /applicant ───────────────────
            current_url = page.url
            print(f"  📍 URL actual: {current_url}", flush=True)

            if "/applicant" not in current_url:
                print("  ⚠️ No se llegó a /applicant", flush=True)
                resultado["error"] = "No se pudo navegar al formulario"
                return resultado

            # ── Completar formulario de applicant ─────────────────────
            print("  📝 Completando formulario...", flush=True)
            
            try:
                await page.locator('input[formcontrolname="firstName"]').fill("Juan")
                await _delay(0.3, 0.6)
                await page.locator('input[formcontrolname="lastName"]').fill("Perez")
                await _delay(0.3, 0.6)
                await page.locator('input[formcontrolname="email"]:visible').fill("cotizacion@temp.com")
                await _delay(0.3, 0.6)
                await page.locator('input[formcontrolname="code"]').fill("11")
                await _delay(0.3, 0.6)
                await page.locator('input[formcontrolname="cellphone"]').fill("55551234")
                await _delay(0.3, 0.6)
                
                # Localidad
                await page.locator('input[formcontrolname="finder"]').type(localidad, delay=50)
                await asyncio.sleep(2)
                await page.locator('button.dropdown-item:visible').first.click()
                await _delay(0.5, 1.0)
            except Exception as e:
                print(f"  ⚠️ Error llenando form: {e}", flush=True)

            # ── Click "Ver la cotización" ─────────────────────────────
            print("  📌 Click 'Ver la cotización'...", flush=True)
            ver_btn = page.locator('button:has-text("Ver la cotización")').first
            if await ver_btn.is_visible(timeout=5000):
                await ver_btn.click()
                await asyncio.sleep(15)
            else:
                print("  ⚠️ Botón no visible", flush=True)
                resultado["error"] = "Botón de cotización no visible"
                return resultado

            # ── Extraer cotizaciones ──────────────────────────────────
            print("  📊 Extrayendo cotizaciones...", flush=True)
            text = await page.inner_text("body")
            cotizaciones = _parsear_resultados(text)

            if cotizaciones:
                resultado["cotizaciones"] = cotizaciones
                resultado["total_cotizaciones"] = len(cotizaciones)
                resultado["exito"] = True
                print(f"  ✅ {len(cotizaciones)} cotizaciones obtenidas", flush=True)
            else:
                resultado["error"] = "No se encontraron cotizaciones"
                resultado["texto_debug"] = text[:1500]
                print(f"  ❌ Sin cotizaciones", flush=True)

            return resultado

        except Exception as e:
            print(f"  ❌ Error: {e}", flush=True)
            traceback.print_exc()
            resultado["error"] = str(e)
            return resultado

        finally:
            await browser.close()


def _parsear_resultados(text: str) -> list:
    """Parsea cotizaciones del texto de la página de resultados."""
    cotizaciones = []

    precios = re.findall(r'\$\s*([\d.,]+)', text)
    precios_validos = []
    for p in precios:
        try:
            val = float(p.replace('.', '').replace(',', '.'))
            if 5000 < val < 500000:
                precios_validos.append({"raw": p, "value": val})
        except ValueError:
            continue

    if not precios_validos:
        return cotizaciones

    plan_keywords = [
        "premium", "básica", "basica", "total", "integral", "contra todo",
        "responsabilidad civil", "rc", "todo riesgo", "daño propio",
    ]

    for precio in precios_validos:
        cot = {
            "aseguradora": "Triunfo Seguros",
            "plan": "",
            "precio_mensual": precio["value"],
            "precio_texto": f"${precio['raw']}",
            "texto_completo": "",
        }

        precio_idx = text.find(f"${precio['raw']}")
        if precio_idx > 0:
            contexto = text[max(0, precio_idx - 200):precio_idx + 200]
            cot["texto_completo"] = contexto.strip()[:500]

            for kw in plan_keywords:
                if kw in contexto.lower():
                    cot["plan"] = kw.title()
                    break

        cotizaciones.append(cot)

    return cotizaciones


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
