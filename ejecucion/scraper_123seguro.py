# -*- coding: utf-8 -*-
"""
Scraper stealth para 123Seguro — Flujo MANUAL (nunca por patente).

ESTRATEGIA DE ANONIMATO:
- Datos del vehículo: REALES (marca, modelo, versión, año)
- Datos personales: FALSOS (generados por placebo_generator)
- 123Seguro NUNCA recibe la patente ni datos reales del cliente

FLUJO DE 123SEGURO (SPA actual):
1. Marca → 2. Año → 3. Modelo → 4. Versión →
5. 0km/accesorios si aplica → 6. Zona (Prov/Localidad) →
7. Datos placebo → RESULTADOS

Autor: Sistema Agéntico GPY
Fecha: 2026-05-07
"""

import asyncio
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime

# Importar generador de datos placebo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from placebo_generator import generar_persona_placebo, generar_delay_humanizado

# Playwright usará los navegadores instalados en la imagen Docker

# Constantes
# Constantes de tiempo (incrementadas para evitar fallos en producción)
URL_123SEGURO = (
    "https://123seguro.com.ar/seguros/auto/cotizar/1/vehicle-brand"
    "?referer=https%3A%2F%2Fsearch.brave.com%2F"
)
TIMEOUT_NAVEGACION = 120000  # 2 minutos para cargar la página inicial
TIMEOUT_SELECTOR = 30000    # 30 segundos para encontrar elementos
TIMEOUT_RESULTADOS = 180000 # 3 minutos para esperar cotizaciones finales


async def _configurar_stealth(page):
    """Aplica técnicas stealth para ocultar que es un bot."""
    # Ocultar navigator.webdriver
    await page.add_init_script("""
        // Ocultar webdriver
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        
        // Ocultar que es headless
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });
        
        // Chrome runtime
        window.chrome = { runtime: {} };
        
        // Permissions
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) =>
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters);
        
        // Languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['es-AR', 'es', 'en-US', 'en']
        });
        
        // Platform
        Object.defineProperty(navigator, 'platform', {
            get: () => 'Win32'
        });
        
        // Hardware concurrency (simular CPU real)
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: () => 4
        });
        
        // Device memory
        Object.defineProperty(navigator, 'deviceMemory', {
            get: () => 8
        });
    """)


async def _configurar_log_red_wizard(page):
    """Loguea llamadas clave del wizard para diagnosticar bloqueos o listas vacías."""
    page._wizard_api_blocked = None

    async def _on_response(response):
        url = response.url
        if "/wizard/api/" not in url:
            return
        if not any(path in url for path in ("/cars/brands", "/cars/years", "/cars/models", "/cars/versions")):
            return
        try:
            status = response.status
            print(f"  🌐 Wizard API {status}: {url.split('?')[0]}")
            if status >= 400:
                body = (await response.text())[:300]
                print(f"  🌐 Wizard API body: {body}")
                if status == 403 and "Unusual traffic" in body:
                    page._wizard_api_blocked = {
                        "url": url.split("?")[0],
                        "body": body,
                    }
        except Exception as e:
            print(f"  ⚠️ Error logueando Wizard API: {e}")

    page.on("response", _on_response)


async def _verificar_bloqueo_wizard(page, contexto: str):
    bloqueo = getattr(page, "_wizard_api_blocked", None)
    if not bloqueo:
        return
    raise RuntimeError(
        f"123Seguro bloqueó la API del wizard ({contexto}): "
        f"{bloqueo.get('url')} — {bloqueo.get('body')}"
    )


async def _delay_humano(minimo=1.0, maximo=3.0):
    """Espera un tiempo aleatorio humanizado."""
    delay = generar_delay_humanizado(minimo, maximo)
    await asyncio.sleep(delay)


async def _cerrar_modales_y_cookies(page):
    """Cierra modales de cookies, publicidad y popups."""
    print("  🍪 Verificando modales emergentes...")

    try:
        resultado = await page.evaluate("""
            () => {
                const textos = ['Aceptar todas las cookies', 'Aceptar', 'Acepto', 'Entendido'];
                const candidatos = Array.from(document.querySelectorAll('button, a, [role="button"]'));
                const boton = candidatos.find((el) => {
                    const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                    return textos.some((value) => text.includes(value.toLowerCase()));
                });
                if (boton) {
                    boton.click();
                    return 'clicked';
                }
                return 'not_found';
            }
        """)
        if resultado == "clicked":
            await _delay_humano(0.5, 1.0)
            print("    ✅ Cookies aceptadas")
            return
    except Exception:
        pass
    
    # Selectores comunes de modales de cookies/publicidad
    selectores_modal = [
        # Cookies
        'button:has-text("Aceptar")',
        'button:has-text("Acepto")',
        'button:has-text("Entendido")',
        'button:has-text("Cerrar")',
        '[class*="cookie"] button',
        '[id*="cookie"] button',
        # Popups publicidad
        '[class*="popup"] button',
        '[class*="modal"] button',
        '[class*="banner"] button',
        # Botones de close genéricos
        'button[class*="close"]',
        '[aria-label="Cerrar"]',
        'button:has-text("×")',
    ]
    
    for selector in selectores_modal:
        try:
            boton = await page.query_selector(selector)
            if boton:
                await boton.click()
                await _delay_humano(0.5, 1.0)
                print(f"    ✅ Modal cerrado: {selector}")
        except Exception:
            pass

    try:
        ocultado = await page.evaluate("""
            () => {
                const selectors = [
                    '#onetrust-consent-sdk',
                    '.onetrust-pc-dark-filter',
                    '[data-nosnippet="true"]',
                    '[class*="cookie"]',
                    '[id*="cookie"]'
                ];
                let changed = false;
                selectors.forEach((selector) => {
                    document.querySelectorAll(selector).forEach((el) => {
                        el.style.display = 'none';
                        el.style.pointerEvents = 'none';
                        changed = true;
                    });
                });
                return changed;
            }
        """)
        if ocultado:
            print("    ✅ Banner de cookies ocultado")
    except Exception:
        pass


async def _esperar_carga_dinamica(page):
    """Espera a que desaparezcan spinners de carga."""
    print("  ⏳ Esperando carga de elementos...")
    
    # Selectores de cargando/spinner
    selectores_carga = [
        '[class*="loading"]',
        '[class*="spinner"]',
        '[class*="loader"]',
        '[class*="skeleton"]',
        '[class*="fetching"]',
    ]
    
    for selector in selectores_carga:
        try:
            await page.wait_for_selector(selector, state="hidden", timeout=8000)
        except Exception:
            pass
    
    await _delay_humano(1.0, 2.0)


async def _click_seguro(page, selector, timeout=TIMEOUT_SELECTOR):
    """Click con delay humanizado y manejo de errores - estrategia múltiple."""
    # Estrategia 1: Playwright normal
    try:
        elemento = await page.wait_for_selector(selector, timeout=timeout)
        if elemento:
            await elemento.scroll_into_view_if_needed()
            await _delay_humano(0.3, 0.8)
            await elemento.click()
            await _delay_humano(0.5, 1.5)
            return True
    except Exception:
        pass
    
    # Estrategia 2: Click via locator
    try:
        locator = page.locator(selector).first
        if await locator.is_visible(timeout=3000):
            await locator.scroll_into_view_if_needed()
            await locator.click(timeout=5000)
            await _delay_humano(0.5, 1.0)
            return True
    except Exception:
        pass
    
    # Estrategia 3: Click via JavaScript
    try:
        elemento = await page.query_selector(selector)
        if elemento:
            await elemento.scroll_into_view_if_needed()
            await page.evaluate("el => el.click()", elemento)
            await _delay_humano(0.5, 1.0)
            return True
    except Exception:
        pass
    
    return False


async def _escribir_en_input(page, selector, texto, timeout=8000):
    """Escribe en un input con estrategias múltiples."""
    # Estrategia 1: playwright normal
    try:
        elemento = await page.wait_for_selector(selector, timeout=timeout)
        if elemento:
            await elemento.click()
            await elemento.fill(texto)
            await _delay_humano(0.3, 0.8)
            return True
    except Exception:
        pass
    
    # Estrategia 2: keyboard typing
    try:
        elemento = await page.query_selector(selector)
        if elemento:
            await elemento.click()
            await page.keyboard.type(texto, delay=50)
            await _delay_humano(0.3, 0.8)
            return True
    except Exception:
        pass
    
    return False


async def _escribir_en_campo(page, selector, texto):
    """Escribe en cualquier campo usando selectors múltiples."""
    selectors = selector.split(',')
    for sel in selectors:
        sel = sel.strip()
        if await _escribir_en_input(page, sel, texto, timeout=5000):
            return True
    return False


async def _log_opciones_visibles(page, contexto: str):
    """Imprime una muestra breve del DOM visible para depurar cambios del wizard."""
    try:
        opciones = await page.evaluate('''
            () => {
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 5
                        && rect.height > 5
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                const textOf = (el) => [
                    el.innerText,
                    el.textContent,
                    el.getAttribute('aria-label'),
                    el.getAttribute('title'),
                    el.getAttribute('alt'),
                    el.getAttribute('placeholder'),
                    el.value,
                    el.getAttribute('name'),
                    el.getAttribute('data-value'),
                    el.getAttribute('data-brand'),
                    el.querySelector?.('img')?.getAttribute('alt'),
                ].filter(Boolean).join(' ').replace(/\\s+/g, ' ').trim();
                return Array.from(document.querySelectorAll(
                    'button, a, label, li, input, img, [role="button"], [role="option"], [aria-label], [title], div, span'
                ))
                    .filter(visible)
                    .map((el) => {
                        const rect = el.getBoundingClientRect();
                        const text = textOf(el);
                        const inChrome = Boolean(el.closest('header, nav, footer, [class*="navbar"], [class*="menu"], [class*="header"]'));
                        let score = 0;
                        if (rect.x > 100 && rect.x < window.innerWidth - 100) score += 30;
                        if (rect.y > 80 && rect.y < window.innerHeight - 40) score += 30;
                        if (/modelo|marca|año|anio|versi[oó]n|sin resultados|buscar/i.test(text)) score += 40;
                        if (inChrome || rect.x < 0) score -= 80;
                        return { text, score };
                    })
                    .sort((a, b) => b.score - a.score)
                    .map((item) => item.text)
                    .filter((text) => text && text.length <= 120)
                    .slice(0, 25);
            }
        ''')
        print(f"    🧭 Debug wizard ({contexto}) URL: {page.url}")
        print(f"    🧭 Opciones visibles: {opciones}")
    except Exception as e:
        print(f"    ⚠️ No se pudo capturar debug del wizard: {e}")


async def _seleccionar_opcion_del_wizard(page, texto: str):
    """Selecciona una opción del wizard de 123seguro por su texto."""
    # Esperar más tiempo para que carguen las opciones
    print(f"    🔍 Buscando opción: '{texto}'...")
    await _delay_humano(2.0, 3.0)
    
    # Estrategia 1: click directo por JavaScript en el elemento más específico.
    try:
        resultado = await page.evaluate('''
            (textoOriginal) => {
                const texto = String(textoOriginal || '').toLowerCase();
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 5
                        && rect.height > 5
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                const textOf = (el) => [
                    el.innerText,
                    el.textContent,
                    el.getAttribute('aria-label'),
                    el.getAttribute('title'),
                    el.getAttribute('alt'),
                    el.getAttribute('data-value'),
                    el.getAttribute('data-brand'),
                    el.querySelector?.('img')?.getAttribute('alt'),
                    el.closest?.('[aria-label]')?.getAttribute('aria-label'),
                    el.closest?.('[title]')?.getAttribute('title'),
                ].filter(Boolean).join(' ').replace(/\\s+/g, ' ').trim();
                const allElements = Array.from(document.querySelectorAll(
                    'button, a, label, li, img, [role="button"], [role="option"], [data-testid], [aria-label], [title], div, span'
                ));
                const candidates = allElements
                    .filter(visible)
                    .map((el) => ({ el, text: textOf(el) }))
                    .filter(({ text }) => {
                        const normalized = text.toLowerCase();
                        return normalized === texto || normalized.includes(texto);
                    })
                    .map(({ el, text }) => {
                        let score = 0;
                        const normalized = text.toLowerCase();
                        if (normalized === texto) score += 100;
                        if (['BUTTON', 'A', 'LABEL', 'LI'].includes(el.tagName)) score += 25;
                        if (['button', 'option'].includes(el.getAttribute('role'))) score += 25;
                        if (el.closest('button,a,label,[role="button"],[role="option"]')) score += 15;
                        score -= Math.min(text.length, 300) / 10;
                        return { el, text, score };
                    })
                    .sort((a, b) => b.score - a.score);
                if (candidates.length > 0) {
                    const target = candidates[0].el.closest('button,a,label,[role="button"],[role="option"]') || candidates[0].el;
                    target.scrollIntoView({block: 'center'});
                    target.click();
                    return `clicked:${candidates[0].text}`;
                }
                return 'not_found';
            }
        ''', texto)
        if resultado.startswith('clicked:'):
            await _delay_humano(1.0, 2.0)
            print(f"    ✅ Seleccionado: {resultado.split(':', 1)[1]}")
            return True
    except Exception as e:
        print(f"    ⚠️ JS click error: {e}")

    # Estrategia 2: algunas marcas quedan detrás de "Otra marca".
    try:
        resultado = await page.evaluate('''
            () => {
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 5
                        && rect.height > 5
                        && rect.bottom > 0
                        && rect.top < window.innerHeight
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                const candidates = Array.from(document.querySelectorAll('button, a, label, [role="button"]'));
                const other = candidates.find((el) => {
                    const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                    return visible(el) && (
                        text === 'otra marca'
                        || text === 'otra'
                        || text === 'otro'
                        || text.startsWith('otra marca ')
                        || text.startsWith('otro ')
                        || text.startsWith('otra ')
                    );
                });
                if (!other) return 'not_found';
                other.scrollIntoView({block: 'center'});
                other.click();
                return `clicked:${(other.innerText || other.textContent || '').replace(/\\s+/g, ' ').trim()}`;
            }
        ''')
        if resultado.startswith('clicked:'):
            await _delay_humano(1.0, 2.0)
            print(f"    ✅ Abierto selector alternativo: {resultado.split(':', 1)[1]}")
            try:
                resultado = await page.evaluate('''
                    (textoOriginal) => {
                        const texto = String(textoOriginal || '').toLowerCase();
                        const visible = (el) => {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            return rect.width > 5
                                && rect.height > 5
                                && style.visibility !== 'hidden'
                                && style.display !== 'none';
                        };
                        const textOf = (el) => [
                            el.innerText,
                            el.textContent,
                            el.getAttribute('aria-label'),
                            el.getAttribute('title'),
                            el.getAttribute('alt'),
                            el.getAttribute('data-value'),
                            el.getAttribute('data-brand'),
                            el.querySelector?.('img')?.getAttribute('alt'),
                            el.closest?.('[aria-label]')?.getAttribute('aria-label'),
                            el.closest?.('[title]')?.getAttribute('title'),
                        ].filter(Boolean).join(' ').replace(/\\s+/g, ' ').trim();
                        const candidates = Array.from(document.querySelectorAll(
                            'button, a, label, li, img, [role="button"], [role="option"], [aria-label], [title]'
                        ))
                            .filter(visible)
                            .map((el) => ({ el, text: textOf(el) }))
                            .filter(({ text }) => {
                                const normalized = text.toLowerCase();
                                return normalized === texto || normalized.includes(texto);
                            })
                            .sort((a, b) => {
                                const exactA = a.text.toLowerCase() === texto;
                                const exactB = b.text.toLowerCase() === texto;
                                if (exactA !== exactB) return exactA ? -1 : 1;
                                return a.text.length - b.text.length;
                            });
                        if (!candidates.length) return 'not_found';
                        candidates[0].el.scrollIntoView({block: 'center'});
                        candidates[0].el.click();
                        return `clicked:${candidates[0].text}`;
                    }
                ''', texto)
                if resultado.startswith('clicked:'):
                    await _delay_humano(1.0, 2.0)
                    print(f"    ✅ Seleccionado tras abrir lista: {resultado.split(':', 1)[1]}")
                    return True
            except Exception:
                pass
    except Exception:
        pass

    # Estrategia 3: si hay un buscador visible, escribir y presionar Enter.
    try:
        resultado = await page.evaluate('''
            () => {
                const visibles = Array.from(document.querySelectorAll('input[type="search"], input'))
                    .filter((el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 5
                            && rect.height > 5
                            && rect.bottom > 0
                            && rect.top < window.innerHeight
                            && style.visibility !== 'hidden'
                            && style.display !== 'none'
                            && !el.disabled
                            && !el.readOnly;
                    });
                const scored = visibles
                    .map((el) => {
                        const rect = el.getBoundingClientRect();
                        const attrs = [
                            el.getAttribute('placeholder'),
                            el.getAttribute('aria-label'),
                            el.getAttribute('name'),
                            el.getAttribute('id'),
                            el.getAttribute('type'),
                        ].filter(Boolean).join(' ').toLowerCase();
                        const inChrome = Boolean(el.closest('header, nav, footer, [class*="navbar"], [class*="menu"], [class*="header"]'));
                        let score = 0;
                        if (/buscar|search|modelo|marca|version|versión|año|anio|auto|veh/i.test(attrs)) score += 80;
                        if (rect.top > 120) score += 35;
                        if (rect.width > 140) score += 20;
                        if (inChrome) score -= 120;
                        if (/email|mail|phone|tel|cel|nombre|name|login|password|pass|dni/i.test(attrs)) score -= 80;
                        return { el, score, attrs, top: Math.round(rect.top), width: Math.round(rect.width) };
                    })
                    .sort((a, b) => b.score - a.score);
                const input = scored[0]?.el;
                if (!input) return 'not_found';
                input.scrollIntoView({block: 'center'});
                input.focus();
                input.click();
                const chosen = scored[0];
                return `focused:${chosen.score}:${chosen.top}:${chosen.width}:${chosen.attrs}`;
            }
        ''')
        if resultado.startswith('focused:'):
            print(f"    🔎 Input buscador enfocado: {resultado}")
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await page.keyboard.type(texto, delay=80)
            await _delay_humano(1.0, 2.0)
            seleccion = await page.evaluate('''
                (textoOriginal) => {
                    const texto = String(textoOriginal || '').toLowerCase();
                    const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return rect.width > 5
                            && rect.height > 5
                            && style.visibility !== 'hidden'
                            && style.display !== 'none';
                    };
                    const textOf = (el) => [
                        el.innerText,
                        el.textContent,
                        el.getAttribute('aria-label'),
                        el.getAttribute('title'),
                        el.getAttribute('alt'),
                        el.getAttribute('data-value'),
                        el.getAttribute('data-brand'),
                        el.querySelector?.('img')?.getAttribute('alt'),
                        el.closest?.('[aria-label]')?.getAttribute('aria-label'),
                        el.closest?.('[title]')?.getAttribute('title'),
                    ].filter(Boolean).join(' ').replace(/\\s+/g, ' ').trim();
                    const candidates = Array.from(document.querySelectorAll(
                        'button, a, label, li, img, [role="button"], [role="option"], [aria-label], [title], div, span'
                    ))
                        .filter(visible)
                        .map((el) => ({ el, text: textOf(el) }))
                        .filter(({ text }) => {
                            const normalized = text.toLowerCase();
                            return normalized === texto || normalized.includes(texto);
                        })
                        .sort((a, b) => a.text.length - b.text.length);
                    if (!candidates.length) return 'not_found';
                    const target = candidates[0].el.closest('button,a,label,[role="button"],[role="option"]') || candidates[0].el;
                    target.scrollIntoView({block: 'center'});
                    target.click();
                    return `clicked:${candidates[0].text}`;
                }
            ''', texto)
            if seleccion.startswith('clicked:'):
                await _delay_humano(1.0, 2.0)
                print(f"    ✅ Seleccionado desde buscador: {seleccion.split(':', 1)[1]}")
                return True
            await page.keyboard.press("ArrowDown")
            await _delay_humano(0.3, 0.7)
            await page.keyboard.press("Enter")
            await _delay_humano(1.0, 2.0)
            print(f"    ✅ Escrito en buscador y confirmado con teclado: {texto}")
            return True
    except Exception:
        pass

    # Estrategia 4: buscar con querySelector y click
    try:
        resultado = await page.evaluate('''
            (textoOriginal) => {
                const texto = String(textoOriginal || '').toLowerCase();
                const elementos = Array.from(document.querySelectorAll('*')).filter(el => {
                    const contenido = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return contenido
                        && contenido.toLowerCase().includes(texto)
                        && contenido.length <= 160
                        && rect.width > 5
                        && rect.height > 5
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                });
                if (elementos.length > 0) {
                    const el = elementos[0].closest('button,a,label,[role="button"],[role="option"]') || elementos[0];
                    el.scrollIntoView({block: 'center'});
                    setTimeout(() => el.click(), 500);
                    return 'clicked';
                }
                return 'not_found';
            }
        ''', texto)
        await _delay_humano(1.5, 2.5)
        if resultado == 'clicked':
            print(f"    ✅ Estrategia 3: {texto}")
            return True
    except Exception:
        pass
    
    # Estrategia 5: esperar a que aparezca el elemento y hacer click
    try:
        await page.wait_for_timeout(2000)
        locator = page.get_by_text(texto, exact=False).first
        if await locator.is_visible(timeout=3000):
            await locator.scroll_into_view_if_needed()
            await locator.click(timeout=5000)
            await _delay_humano(1.0, 2.0)
            print(f"    ✅ Por locator: {texto}")
            return True
    except Exception:
        pass
    
    await _log_opciones_visibles(page, f"no encontrado: {texto}")
    print(f"    ⚠️ No se pudo seleccionar: {texto}")
    return False


async def _esperar_ruta(page, slugs, timeout=12000):
    """Espera hasta que la SPA cambie a una de las rutas esperadas."""
    if isinstance(slugs, str):
        slugs = [slugs]
    deadline = time.monotonic() + (timeout / 1000)
    while time.monotonic() < deadline:
        current_url = page.url
        if any(slug in current_url for slug in slugs):
            return True
        await asyncio.sleep(0.3)
    return False


async def _seleccionar_y_avanzar(page, texto, rutas_siguientes, descripcion):
    """Selecciona una opción y confirma que el wizard avanzó al paso esperado."""
    await _verificar_bloqueo_wizard(page, f"antes de seleccionar {descripcion}")
    if not await _seleccionar_opcion_del_wizard(page, texto):
        await _verificar_bloqueo_wizard(page, f"falló selección de {descripcion}")
        if await _esperar_ruta(page, rutas_siguientes, timeout=2000):
            return True
        raise RuntimeError(f"No se pudo seleccionar {descripcion}: {texto}")

    if await _esperar_ruta(page, rutas_siguientes, timeout=8000):
        await _verificar_bloqueo_wizard(page, f"después de seleccionar {descripcion}")
        return True

    await _buscar_boton_continuar(page)
    if await _esperar_ruta(page, rutas_siguientes, timeout=12000):
        await _verificar_bloqueo_wizard(page, f"después de continuar {descripcion}")
        return True

    await _verificar_bloqueo_wizard(page, f"sin avance tras seleccionar {descripcion}")
    await _log_opciones_visibles(page, f"sin avance tras seleccionar {descripcion}: {texto}")
    raise RuntimeError(
        f"El wizard no avanzó después de seleccionar {descripcion}: {texto}. URL actual: {page.url}"
    )


async def _seleccionar_zona(page, provincia: str, localidad: str):
    """Selecciona la zona (provincia y localidad)."""
    await _delay_humano(0.5, 1.0)
    
    # 123seguro puede tener selects anidados o búsqueda por ciudad
    # Primero intentar seleccionar provincia
    await _seleccionar_opcion_del_wizard(page, provincia)
    await _delay_humano(1.0, 2.0)
    
    # Luego intentar localidad
    if localidad:
        await _seleccionar_opcion_del_wizard(page, localidad)
    
    return True


async def _escribir_seguro(page, selector, texto, timeout=TIMEOUT_SELECTOR):
    """Escribe texto con estrategias múltiples."""
    # Estrategia 1: fill directo
    try:
        elemento = await page.wait_for_selector(selector, timeout=timeout)
        if elemento:
            await elemento.click()
            await elemento.fill(texto)
            await _delay_humano(0.2, 0.5)
            return True
    except Exception:
        pass
    
    # Estrategia 2: type carácter por carácter
    try:
        elemento = await page.wait_for_selector(selector, timeout=timeout)
        if elemento:
            await elemento.click()
            await _delay_humano(0.2, 0.5)
            for char in str(texto):
                await page.keyboard.type(char, delay=50 + int(generar_delay_humanizado(20, 100)))
            await _delay_humano(0.3, 0.8)
            return True
    except Exception:
        pass
    
    # Estrategia 3: con locator
    try:
        locator = page.locator(selector).first
        if await locator.is_visible(timeout=3000):
            await locator.fill(texto)
            return True
    except Exception:
        pass
    
    print(f"  ⚠️ No se pudo escribir en '{selector}'")
    return False


async def _paso_fecha_nacimiento(page, fecha_nac: dict):
    """Paso 1: Ingresar fecha de nacimiento."""
    print("  📅 Paso 1: Fecha de nacimiento...")
    
    # Buscar el input de fecha
    selectores_fecha = [
        'input[placeholder*="nacimiento"]',
        'input[type="date"]',
        'input[name*="birth"]',
        'input[name*="fecha"]',
        'input[data-testid*="birth"]',
        'input[aria-label*="nacimiento"]',
    ]
    
    for selector in selectores_fecha:
        try:
            elemento = await page.wait_for_selector(selector, timeout=5000)
            if elemento:
                fecha_str = fecha_nac["formato_ddmmaaaa"]
                await elemento.click()
                await _delay_humano(0.3, 0.6)
                # Limpiar campo
                await page.keyboard.press("Control+A")
                await page.keyboard.type(fecha_str, delay=80)
                await _delay_humano(0.5, 1.0)
                print(f"    ✅ Fecha ingresada: {fecha_str}")
                break
        except Exception:
            continue
    
    # Buscar y clickear botón Continuar
    await _buscar_boton_continuar(page)


async def _paso_nombre(page, nombre: str):
    """Paso 2: Ingresar nombre (FALSO)."""
    print(f"  👤 Paso 2: Nombre ({nombre})...")
    
    selectores_nombre = [
        'input[placeholder*="nombre"]',
        'input[name*="name"]',
        'input[name*="nombre"]',
        'input[data-testid*="name"]',
    ]
    
    for selector in selectores_nombre:
        try:
            elemento = await page.wait_for_selector(selector, timeout=5000)
            if elemento:
                await elemento.click()
                await page.keyboard.press("Control+A")
                await page.keyboard.type(nombre, delay=60)
                await _delay_humano(0.5, 1.0)
                print(f"    ✅ Nombre ingresado")
                break
        except Exception:
            continue
    
    await _buscar_boton_continuar(page)


async def _esperar_y_buscar_opcion(page, texto: str, timeout=15000):
    """Busca y hace clic en una opción por su texto."""
    await _esperar_carga_dinamica(page)
    
    # Estrategia 1: click directo en elemento visible con el texto
    estrategias = [
        # Click en cualquier elemento que contenga el texto
        f'div[role="button"]:has-text("{texto}")',
        f'div[class*="option"]:has-text("{texto}")',
        f'div[class*="item"]:has-text("{texto}")',
        f'span:has-text("{texto}")',
        # Por data attributes
        f'[data-value*="{texto.lower()}"]',
        # Por texto parcial
        f'text="{texto}"',
    ]
    
    for selector in estrategias:
        try:
            elemento = await page.query_selector(selector)
            if elemento:
                # Verificar que esté visible
                box = await elemento.bounding_box()
                if box:
                    await elemento.scroll_into_view_if_needed()
                    await _delay_humano(0.3, 0.8)
                    await elemento.click()
                    await _delay_humano(0.5, 1.0)
                    return True
        except Exception:
            continue
    
    # Estrategia 2: buscar en lista/grid de opciones
    try:
        # Buscar todos los elementos cliqueables y buscar el que contenga el texto
        items = await page.query_selector_all('[class*="brand"], [class*="make"], [class*="logo"], div[role="button"], a')
        for item in items:
            try:
                texto_item = await item.text_content()
                if texto_item and texto.lower() in texto_item.lower():
                    await item.scroll_into_view_if_needed()
                    await item.click()
                    await _delay_humano(0.5, 1.0)
                    return True
            except Exception:
                continue
    except Exception:
        pass
    
    return False


async def _paso_marca(page, marca: str):
    """Paso 1: Seleccionar marca del vehículo."""
    print(f"  🚗 Paso 1: Marca ({marca})...")
    
    # Intentar con la función helper mejorada
    if await _esperar_y_buscar_opcion(page, marca, timeout=20000):
        print(f"    ✅ Marca '{marca}' seleccionada")
        return
    
    # Fallback: método original con más selectores
    marca_lower = marca.lower()
    
    selectores = [
        f'button:has-text("{marca}")',
        f'div:has-text("{marca}")',
        f'a:has-text("{marca}")',
        f'span:has-text("{marca}")',
        f'[data-brand="{marca_lower}"]',
        f'[data-make="{marca_lower}"]',
    ]
    
    for selector in selectores:
        try:
            btn = await page.query_selector(selector)
            if btn:
                await btn.scroll_into_view_if_needed()
                await _delay_humano(0.3, 0.8)
                await btn.click()
                await _delay_humano(0.5, 1.0)
                print(f"    ✅ Marca seleccionada: {selector}")
                return
        except Exception:
            continue
    
    print(f"    ⚠️ No se encontró la marca '{marca}' - intentar con búsqueda")
    
    # Fallback: buscar input de búsqueda
    inputs_busqueda = [
        'input[placeholder*="marca"]',
        'input[placeholder*="buscar"]',
        'input[placeholder*="search"]',
        'input[type="search"]',
    ]
    
    for selector in inputs_busqueda:
        try:
            elemento = await page.wait_for_selector(selector, timeout=5000)
            if elemento:
                await elemento.click()
                await page.keyboard.type(marca, delay=80)
                await _delay_humano(1.0, 2.0)
                # Click en primer resultado
                await page.keyboard.press("Enter")
                await _delay_humano(0.5, 1.0)
                print(f"    ✅ Marca buscada y seleccionada")
                return
        except Exception:
            continue
    
    print(f"    ⚠️ No se pudo seleccionar marca automáticamente")


async def _paso_modelo(page, modelo: str):
    """Paso 2: Seleccionar modelo."""
    print(f"  🏷️ Paso 2: Modelo ({modelo})...")
    
    if await _esperar_y_buscar_opcion(page, modelo, timeout=20000):
        print(f"    ✅ Modelo '{modelo}' seleccionado")
        return
    
    # Fallback
    await _esperar_carga_dinamica(page)
    await _delay_humano(1.0, 2.0)
    
    # Buscar por texto o input de búsqueda - selectores más flexibles
    selectores = [
        f'button:has-text("{modelo}")',
        f'div:has-text("{modelo}")',
        f'a:has-text("{modelo}")',
        f'li:has-text("{modelo}")',
        f'span:has-text("{modelo}")',
        f'text():{modelo}',  # Cualquier elemento con el texto
    ]
    
    for selector in selectores:
        if await _click_seguro(page, selector, timeout=15000):  # 15s timeout para vehículo
            print(f"    ✅ Modelo seleccionado")
            return
    
    # Fallback: input búsqueda
    inputs = ['input[placeholder*="modelo"]', 'input[placeholder*="buscar"]', 'input[type="search"]']
    for selector in inputs:
        try:
            elemento = await page.wait_for_selector(selector, timeout=8000)
            if elemento:
                await elemento.click()
                await page.keyboard.type(modelo, delay=80)
                await _delay_humano(1.0, 2.0)
                await page.keyboard.press("Enter")
                print(f"    ✅ Modelo buscado y seleccionado")
                return
        except Exception:
            continue
    
    print(f"    ⚠️ No se encontró el modelo '{modelo}'")


async def _paso_version(page, version: str):
    """Paso 3: Seleccionar versión."""
    print(f"  📋 Paso 3: Versión ({version})...")
    
    if version and await _esperar_y_buscar_opcion(page, version, timeout=20000):
        print(f"    ✅ Versión '{version}' seleccionada")
        return
    
    await _esperar_carga_dinamica(page)
    await _delay_humano(1.0, 2.0)
    
    # Si no encuentra la versión exacta, clickear la primera opción disponible
    try:
        primer_opcion = await page.wait_for_selector('button, div[role="option"], li[role="option"], div[class*="option"]', timeout=8000)
        if primer_opcion:
            await primer_opcion.scroll_into_view_if_needed()
            await primer_opcion.click()
            print(f"    ⚠️ Versión aproximada seleccionada (primera opción)")
    except Exception as e:
        print(f"    ⚠️ No se encontró versión: {e}")


async def _paso_anio(page, anio: int):
    """Paso 6: Seleccionar año."""
    print(f"  📅 Paso 6: Año ({anio})...")
    await _delay_humano(0.5, 1.5)
    
    selectores = [
        f'button:has-text("{anio}")',
        f'div:has-text("{anio}")',
        f'a:has-text("{anio}")',
        f'span:has-text("{anio}")',
    ]
    
    for selector in selectores:
        if await _click_seguro(page, selector, timeout=8000):
            print(f"    ✅ Año seleccionado")
            return


async def _paso_gnc(page, tiene_gnc: bool):
    """Paso 7: GNC Sí/No."""
    print(f"  ⛽ Paso 7: GNC ({'Sí' if tiene_gnc else 'No'})...")
    
    texto_opcion = "Sí" if tiene_gnc else "No"
    selectores = [
        f'button:has-text("{texto_opcion}")',
        f'div:has-text("{texto_opcion}")',
        f'label:has-text("{texto_opcion}")',
    ]
    
    for selector in selectores:
        if await _click_seguro(page, selector, timeout=8000):
            print(f"    ✅ GNC: {texto_opcion}")
            return


async def _paso_zona(page, provincia: str, localidad: str):
    """Paso 8: Seleccionar zona (provincia → localidad)."""
    print(f"  📍 Paso 8: Zona ({provincia} - {localidad})...")
    
    # Buscar input de zona/localidad/CP
    inputs = [
        'input[placeholder*="localidad"]',
        'input[placeholder*="zona"]',
        'input[placeholder*="código postal"]',
        'input[placeholder*="ubicación"]',
        'input[name*="location"]',
        'input[type="search"]',
    ]
    
    busqueda = f"{localidad}, {provincia}"
    
    for selector in inputs:
        try:
            elemento = await page.wait_for_selector(selector, timeout=5000)
            if elemento:
                await elemento.click()
                await page.keyboard.type(busqueda, delay=60)
                await _delay_humano(1.5, 3.0)
                # Seleccionar primer resultado del autocomplete
                await page.keyboard.press("ArrowDown")
                await _delay_humano(0.3, 0.6)
                await page.keyboard.press("Enter")
                await _delay_humano(0.5, 1.0)
                print(f"    ✅ Zona seleccionada")
                return
        except Exception:
            continue
    
    await _buscar_boton_continuar(page)


async def _paso_email(page, email: str):
    """Paso 9: Ingresar email (FALSO)."""
    print(f"  📧 Paso 9: Email ({email})...")
    
    selectores = [
        'input[type="email"]',
        'input[placeholder*="mail"]',
        'input[name*="email"]',
        'input[placeholder*="correo"]',
    ]
    
    for selector in selectores:
        if await _escribir_seguro(page, selector, email, timeout=8000):
            print(f"    ✅ Email ingresado")
            break
    
    await _buscar_boton_continuar(page)


async def _paso_celular(page, area: str, numero: str):
    """Paso 10: Ingresar celular (FALSO)."""
    print(f"  📱 Paso 10: Celular (+549{area}{numero})...")
    
    # 123Seguro puede tener campos separados para área y número
    # o un solo campo
    
    # Intentar campo único
    selectores = [
        'input[type="tel"]',
        'input[placeholder*="celular"]',
        'input[placeholder*="teléfono"]',
        'input[name*="phone"]',
        'input[name*="celular"]',
    ]
    
    for selector in selectores:
        try:
            elementos = await page.query_selector_all(selector)
            if len(elementos) >= 2:
                # Campos separados: área + número
                await elementos[0].click()
                await page.keyboard.type(area, delay=80)
                await _delay_humano(0.3, 0.6)
                await elementos[1].click()
                await page.keyboard.type(numero, delay=50)
                print(f"    ✅ Celular ingresado (campos separados)")
                break
            elif len(elementos) == 1:
                # Campo único
                await elementos[0].click()
                await page.keyboard.type(f"{area}{numero}", delay=50)
                print(f"    ✅ Celular ingresado (campo único)")
                break
        except Exception:
            continue
    
    await _buscar_boton_continuar(page)


async def _buscar_boton_continuar(page, timeout=10000, es_boton_final=False):
    """Busca y clickea el botón Continuar/Siguiente con estrategias múltiples."""
    await _delay_humano(1.0, 2.0)
    
    if es_boton_final:
        # Solo buscar botón de resultados final
        selectores_final = [
            'button:has-text("Ver resultados")',
            'button:has-text("Cotizar")',
            '[class*="result"]',
        ]
        for selector in selectores_final:
            if await _click_seguro(page, selector, timeout=timeout):
                print(f"    ✅ Clickeado botón final: {selector}")
                await _delay_humano(1.5, 3.0)
                return True
    else:
        # Buscar botones de navegación (NO Cotizar ni Ver resultados)
        selectores_nav = [
            'button[type="submit"]',
            'button:has-text("Continuar")',
            'button:has-text("continuar")',
            'button:has-text("Siguiente")',
            'button:has-text("siguiente")',
            'a:has-text("Continuar")',
            'a:has-text("Siguiente")',
            '[class*="next"]',
            '[class*="continue"]',
        ]
        
        for selector in selectores_nav:
            if await _click_seguro(page, selector, timeout=timeout):
                print(f"    ✅ Clickeado: {selector}")
                await _delay_humano(1.5, 3.0)
                return True
    
    return False


async def _extraer_cotizaciones(page) -> list:
    """
    Extrae TODAS las cotizaciones de la página de resultados.
    Retorna lista de diccionarios con datos reales.
    """
    print("  📊 Extrayendo cotizaciones...")
    cotizaciones = []
    
    # Esperar a que carguen los resultados
    await _delay_humano(3.0, 5.0)
    
    # Intentar extraer datos del DOM
    try:
        datos_raw = await page.evaluate("""
            () => {
                const cotizaciones = [];
                
                // Buscar cards de cotización (adaptable a la estructura de 123seguro)
                const cards = document.querySelectorAll(
                    '[class*="quote"], [class*="cotiza"], [class*="result"], ' +
                    '[class*="card"], [class*="plan"], [class*="offer"]'
                );
                
                // También buscar en estructura de tabla/lista
                const filas = document.querySelectorAll(
                    'tr[class*="quote"], li[class*="quote"], ' +
                    'div[class*="insurance"], div[class*="company"]'
                );
                
                const elementos = cards.length > 0 ? cards : filas;
                
                elementos.forEach(card => {
                    const texto = card.innerText || '';
                    
                    // Extraer imagen/logo
                    const img = card.querySelector('img');
                    const logo = img ? img.src : '';
                    
                    // Extraer nombre de aseguradora
                    const nombreEl = card.querySelector(
                        '[class*="company"], [class*="brand"], [class*="name"], ' +
                        'h2, h3, h4, strong'
                    );
                    const nombre = nombreEl ? nombreEl.innerText.trim() : '';
                    
                    // Extraer precio (buscar patrón $XX.XXX)
                    const precioMatch = texto.match(/\\$\\s*([\\d.,]+)/);
                    const precio = precioMatch ? precioMatch[1].replace(/\\./g, '').replace(',', '.') : '';
                    
                    // Extraer tipo de cobertura
                    const coberturaEl = card.querySelector(
                        '[class*="cover"], [class*="plan"], [class*="type"]'
                    );
                    const cobertura = coberturaEl ? coberturaEl.innerText.trim() : '';
                    
                    // Extraer suma asegurada
                    const sumaMatch = texto.match(/[Ss]uma[^\\d]*\\$?\\s*([\\d.,]+)/);
                    const suma = sumaMatch ? sumaMatch[1].replace(/\\./g, '').replace(',', '.') : '';
                    
                    if (nombre || precio) {
                        cotizaciones.push({
                            aseguradora: nombre,
                            logo_url: logo,
                            precio_texto: precioMatch ? precioMatch[0] : '',
                            precio_mensual: parseFloat(precio) || 0,
                            tipo_cobertura: cobertura,
                            suma_asegurada: parseFloat(suma) || 0,
                            texto_completo: texto.substring(0, 500),
                        });
                    }
                });
                
                return cotizaciones;
            }
        """)
        
        if datos_raw and len(datos_raw) > 0:
            cotizaciones = datos_raw
            print(f"    ✅ {len(cotizaciones)} cotizaciones extraídas")
        else:
            print("    ⚠️ No se encontraron cotizaciones en el DOM, intentando método alternativo...")
            # Método alternativo: capturar todo el texto y parsear
            texto_pagina = await page.inner_text('body')
            cotizaciones = _parsear_texto_cotizaciones(texto_pagina)
            
    except Exception as e:
        print(f"    ❌ Error extrayendo cotizaciones: {e}")
        traceback.print_exc()
    
    return cotizaciones


def _parsear_texto_cotizaciones(texto: str) -> list:
    """Parsea cotizaciones del texto plano de la página."""
    cotizaciones = []
    
    # Buscar patrones de aseguradoras conocidas
    aseguradoras = [
        "Zurich", "Sancor", "Allianz", "La Segunda", "Federación Patronal",
        "Rivadavia", "San Cristóbal", "Mercantil Andina", "Mapfre", "HDI",
        "Integrity", "La Holando", "Provincia Seguros", "Orbis", "SMG",
        "Triunfo", "Nación Seguros", "Paraná", "Protección Mutual",
        "BBVA", "Galeno", "Berkley", "Chubb", "QBE", "Seguros Sura"
    ]
    
    for aseg in aseguradoras:
        if aseg.lower() in texto.lower():
            # Buscar precio cerca del nombre
            patron = re.compile(
                rf'{re.escape(aseg)}.*?\$\s*([\d.,]+)',
                re.IGNORECASE | re.DOTALL
            )
            match = patron.search(texto)
            if match:
                precio_str = match.group(1).replace('.', '').replace(',', '.')
                cotizaciones.append({
                    "aseguradora": aseg,
                    "logo_url": "",
                    "precio_texto": f"${match.group(1)}",
                    "precio_mensual": float(precio_str) if precio_str else 0,
                    "tipo_cobertura": "",
                    "suma_asegurada": 0,
                    "texto_completo": match.group(0)[:300],
                })
    
    return cotizaciones


async def scrape_123seguro(
    marca: str,
    modelo: str,
    version: str,
    anio: int,
    gnc: bool = False,
    provincia: str = "Buenos Aires",
    localidad: str = "Capital Federal",
) -> dict:
    """
    Función principal: Scrapea 123Seguro con flujo MANUAL.
    
    IMPORTANTE: 
    - Los datos del vehículo son REALES (del cliente)
    - Los datos personales son FALSOS (placebo)
    - 123Seguro NUNCA recibe la patente del cliente
    
    Args:
        marca: Marca del vehículo (ej: "Toyota")
        modelo: Modelo (ej: "Etios")
        version: Versión (ej: "1.5 4 PTAS X")
        anio: Año (ej: 2015)
        gnc: Si tiene GNC
        provincia: Provincia de ubicación
        localidad: Localidad/ciudad
    
    Returns:
        dict con vehiculo, cotizaciones[], metadata
    """
    from playwright.async_api import async_playwright
    
    # Generar datos placebo para esta sesión
    placebo = generar_persona_placebo()
    
    print(f"\n{'='*60}")
    print(f"🔍 SCRAPING 123SEGURO — {marca} {modelo} {version} {anio}")
    print(f"👤 Placebo: {placebo['nombre_completo']} ({placebo['email']})")
    print(f"📍 Zona: {localidad}, {provincia}")
    print(f"{'='*60}\n")
    
    resultado = {
        "vehiculo": {
            "marca": marca,
            "modelo": modelo,
            "version": version,
            "anio": anio,
            "gnc": gnc,
        },
        "ubicacion": {
            "provincia": provincia,
            "localidad": localidad,
        },
        "cotizaciones": [],
        "total_cotizaciones": 0,
        "fuente": "123seguro.com.ar",
        "fecha_scraping": datetime.now().isoformat(),
        "datos_placebo_usados": True,
        "exito": False,
        "error": None,
    }
    
    browser = None
    page = None
    context = None
    playwright = None
    
    try:
        playwright = await async_playwright().start()
        
        # Lanzar browser con configuración optimizada para memoria
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-extensions',
                '--disable-background-networking',
                '--disable-default-apps',
                '--disable-sync',
                '--disable-translate',
                '--no-first-run',
                '--single-process',
                '--memory-pressure-off',
                '--window-size=1920,1080',
            ]
        )
        
        # El viewport se configura en el contexto a continuación
        context = await browser.new_context(
            user_agent=placebo["user_agent"],
            viewport=placebo["viewport"],
            locale="es-AR",
            timezone_id="America/Argentina/Buenos_Aires",
        )
        
        # Limitar recursos adicionales del contexto
        context.set_default_timeout(TIMEOUT_SELECTOR)
        
        page = await context.new_page()
        await _configurar_stealth(page)
        await _configurar_log_red_wizard(page)
        
        # Navegar a 123Seguro con estrategia de carga más flexible
        print("  🌐 Navegando a 123seguro.com.ar...")
        try:
            await page.goto(URL_123SEGURO, wait_until="domcontentloaded", timeout=TIMEOUT_NAVEGACION)
        except Exception as e:
            print(f"  ⚠️ Advertencia en carga inicial (procediendo de todos modos): {e}")
        
        await _delay_humano(3.0, 5.0)
        
        # Cerrar modales de cookies/publicidad antes de continuar
        await _cerrar_modales_y_cookies(page)
        
        # Ejecutar el flujo correcto del wizard de 123seguro.
        # La SPA actual carga: Marca -> Año -> Modelo -> Versión.
        
        # Esperar a que cargue la página completamente
        await page.wait_for_load_state('networkidle')
        await _delay_humano(3.0, 5.0)
        
        # Paso 1: Seleccionar marca
        print(f"  🚗 Paso 1: Marca ({marca})...")
        await _delay_humano(2.0, 3.0)
        await _seleccionar_y_avanzar(page, marca, "vehicle-year", "la marca")
        
        # Paso 2: Seleccionar año
        print(f"  📅 Paso 2: Año ({anio})...")
        await _delay_humano(3.0, 5.0)
        await _seleccionar_y_avanzar(page, str(anio), "vehicle-model", "el año")
        
        # Paso 3: Seleccionar modelo
        print(f"  🏷️ Paso 3: Modelo ({modelo})...")
        await _delay_humano(3.0, 5.0)
        await _seleccionar_y_avanzar(page, modelo, "vehicle-version", "el modelo")
        
        # Paso 4: Seleccionar versión
        print(f"  📋 Paso 4: Versión ({version})...")
        await _delay_humano(3.0, 5.0)
        if version:
            await _seleccionar_y_avanzar(
                page,
                version,
                ["vehicle-zerokm", "vehicle-accessories", "vehicle-district", "person-birthdate"],
                "la versión",
            )
        
        # Paso 5: GNC
        print(f"  ⛽ Paso 5: GNC ({'Sí' if gnc else 'No'})...")
        await _delay_humano(2.0, 3.0)
        if "vehicle-is-0km" in page.url or "vehicle-zerokm" in page.url:
            await _seleccionar_opcion_del_wizard(page, "No, es usado")
            if not await _esperar_ruta(page, ["vehicle-accessories", "vehicle-district", "vehicle-subdistrict"], timeout=4000):
                await _buscar_boton_continuar(page)
        if "vehicle-accessories" in page.url:
            if gnc:
                await _seleccionar_opcion_del_wizard(page, "Equipo GNC")
            await _buscar_boton_continuar(page)
        if not await _esperar_ruta(page, ["vehicle-district", "vehicle-subdistrict", "person-birthdate"], timeout=5000):
            await _buscar_boton_continuar(page)
        
        # Paso 6: Zona (provincia/localidad)
        print(f"  📍 Paso 6: Zona ({localidad}, {provincia})...")
        await _delay_humano(3.0, 5.0)
        await _seleccionar_zona(page, provincia, localidad)
        await _delay_humano(2.0, 3.0)
        await _buscar_boton_continuar(page)
        
        # Paso 7: Email y Nombre
        print(f"  📧 Paso 7: Email y Datos...")
        await _delay_humano(2.0, 3.0)
        # El nombre de la persona placebo
        nombre_completo = placebo["nombre"].split()[0]  # Solo primer nombre
        await _escribir_en_campo(page, '[name*="email"], input[type="email"]', placebo["email"])
        await _escribir_en_campo(page, '[name*="name"], input[name*="nombre"]', nombre_completo)
        await _delay_humano(1.0, 2.0)
        await _buscar_boton_continuar(page)
        
        # Paso 8: Teléfono
        print(f"  📱 Paso 8: Teléfono...")
        await _delay_humano(2.0, 3.0)
        telefono_completo = placebo["telefono_area"] + placebo["telefono_numero"]
        await _escribir_en_campo(page, '[name*="phone"], input[type="tel"], input[name*="telefono"]', telefono_completo)
        
        # Hacer click en botón final de resultados
        print("\n  🎯 Obteniendo cotizaciones...")
        await _buscar_boton_continuar(page, es_boton_final=True, timeout=15000)
        
        # Esperar resultados
        print("\n  ⏳ Esperando resultados de cotización...")
        try:
            # Esperar a que aparezcan elementos de cotización
            await page.wait_for_selector(
                '[class*="quote"], [class*="result"], [class*="cotiza"], [class*="price"]',
                timeout=TIMEOUT_RESULTADOS
            )
            await _delay_humano(3.0, 5.0)
        except Exception:
            print("  ⚠️ Timeout esperando resultados, intentando extraer de todos modos...")
        
        # Extraer cotizaciones
        cotizaciones = await _extraer_cotizaciones(page)
        
        resultado["cotizaciones"] = cotizaciones
        resultado["total_cotizaciones"] = len(cotizaciones)
        resultado["exito"] = len(cotizaciones) > 0
        
        if not cotizaciones:
            resultado["error"] = "No se encontraron cotizaciones en la página"
        
    except Exception as e:
        resultado["error"] = str(e)
        resultado["exito"] = False
        print(f"\n  ❌ Error en scraping: {e}")
        traceback.print_exc()
    
    finally:
        # CIERRE EXHAUSTIVO DE RECURSOS - CRÍTICO para evitar memory leaks
        print("  🧹 Limpiando recursos del browser...")
        try:
            if page:
                await page.close()
        except Exception as e:
            print(f"  ⚠️ Error cerrando page: {e}")
        
        try:
            if context:
                await context.close()
        except Exception as e:
            print(f"  ⚠️ Error cerrando context: {e}")
        
        try:
            if browser:
                await browser.close()
        except Exception as e:
            print(f"  ⚠️ Error cerrando browser: {e}")
        
        try:
            if playwright:
                await playwright.stop()
        except Exception as e:
            print(f"  ⚠️ Error deteniendo playwright: {e}")
    
    print(f"\n{'='*60}")
    print(f"📊 RESULTADO: {resultado['total_cotizaciones']} cotizaciones {'✅' if resultado['exito'] else '❌'}")
    print(f"{'='*60}\n")
    
    return resultado


# === ENTRY POINT PARA TESTING ===

if __name__ == "__main__":
    async def test():
        resultado = await scrape_123seguro(
            marca="Toyota",
            modelo="Etios",
            version="1.5 4 PTAS X",
            anio=2015,
            gnc=False,
            provincia="Santa Fe",
            localidad="Rosario",
        )
        print(json.dumps(resultado, indent=2, ensure_ascii=False, default=str))
    
    asyncio.run(test())
