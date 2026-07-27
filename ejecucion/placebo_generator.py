# -*- coding: utf-8 -*-
"""
Generador de datos placebo para scraping anónimo.
Produce datos personales FALSOS rotativos para cada sesión de scraping.

PROPÓSITO: 123Seguro nunca recibe datos reales del cliente.
Solo recibe datos del vehículo reales + persona ficticia.

Autor: Sistema Agéntico GPY
Fecha: 2026-05-07
"""

import random
import string
from datetime import datetime

# === POOLS DE DATOS FALSOS ===

NOMBRES_MASCULINOS = [
    "Juan", "Carlos", "Pedro", "Diego", "Martín",
    "Pablo", "Nicolás", "Tomás", "Lucas", "Matías",
    "Santiago", "Facundo", "Agustín", "Sebastián", "Gonzalo",
    "Federico", "Alejandro", "Andrés", "Fernando", "Roberto"
]

NOMBRES_FEMENINOS = [
    "María", "Ana", "Laura", "Sofía", "Valentina",
    "Camila", "Florencia", "Lucía", "Carolina", "Paula",
    "Daniela", "Andrea", "Gabriela", "Romina", "Julieta",
    "Victoria", "Mariana", "Cecilia", "Natalia", "Silvina"
]

APELLIDOS = [
    "García", "López", "Martínez", "Rodríguez", "González",
    "Fernández", "Pérez", "Sánchez", "Ramírez", "Torres",
    "Díaz", "Romero", "Álvarez", "Morales", "Acosta",
    "Ruiz", "Flores", "Gutiérrez", "Castro", "Ortiz",
    "Silva", "Méndez", "Rojas", "Vargas", "Herrera",
    "Molina", "Medina", "Suárez", "Ríos", "Peralta"
]

DOMINIOS_EMAIL = [
    "gmail.com", "hotmail.com", "yahoo.com.ar",
    "outlook.com", "live.com.ar", "hotmail.com.ar",
    "yahoo.com", "outlook.com.ar", "mail.com"
]

# Códigos de área reales de Argentina (para que el número parezca legítimo)
CODIGOS_AREA = [
    "11",   # Buenos Aires
    "341",  # Rosario
    "351",  # Córdoba
    "261",  # Mendoza
    "221",  # La Plata
    "223",  # Mar del Plata
    "299",  # Neuquén
    "381",  # Tucumán
    "264",  # San Juan
    "343",  # Paraná
    "362",  # Resistencia
    "266",  # San Luis
]

# User-Agents reales actualizados (Chrome en Windows/Mac/Linux)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 OPR/111.0.0.0",
]

# Resoluciones de pantalla comunes
RESOLUCIONES = [
    (1366, 768),
    (1920, 1080),
    (1536, 864),
    (1440, 900),
    (1280, 720),
    (1600, 900),
    (1280, 800),
    (1024, 768),
]


def _slugify_nombre(nombre: str) -> str:
    """Convierte nombre a slug para email (sin acentos, minúscula)."""
    reemplazos = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "ñ": "n", "ü": "u", " ": "."
    }
    slug = nombre.lower()
    for original, reemplazo in reemplazos.items():
        slug = slug.replace(original, reemplazo)
    return slug


def generar_persona_placebo() -> dict:
    """
    Genera una identidad falsa completa para una sesión de scraping.
    Cada llamada produce datos únicos e irrelacionables.
    
    Returns:
        dict con: nombre, email, telefono_area, telefono_numero,
                  fecha_nacimiento (dict con dia, mes, anio),
                  user_agent, viewport
    """
    # Elegir género aleatorio para consistencia nombre
    es_masculino = random.random() > 0.5
    nombre = random.choice(NOMBRES_MASCULINOS if es_masculino else NOMBRES_FEMENINOS)
    apellido = random.choice(APELLIDOS)
    
    # Email: nombre.apellido + sufijo aleatorio
    nombre_slug = _slugify_nombre(nombre)
    apellido_slug = _slugify_nombre(apellido)
    sufijo = random.randint(10, 999)
    separador = random.choice([".", "_", ""])
    dominio = random.choice(DOMINIOS_EMAIL)
    email = f"{nombre_slug}{separador}{apellido_slug}{sufijo}@{dominio}"
    
    # Teléfono: código de área real + número aleatorio
    codigo_area = random.choice(CODIGOS_AREA)
    # Los números de celular en Argentina tienen 6-8 dígitos después del área
    digitos_restantes = 10 - len(codigo_area)
    numero_min = 10 ** (digitos_restantes - 1)
    numero_max = (10 ** digitos_restantes) - 1
    telefono_numero = str(random.randint(numero_min, numero_max))
    
    # Fecha de nacimiento: entre 25 y 55 años (rango típico de asegurados)
    anio_actual = datetime.now().year
    anio_nac = random.randint(anio_actual - 55, anio_actual - 25)
    mes_nac = random.randint(1, 12)
    dia_nac = random.randint(1, 28)  # 28 para evitar meses cortos
    
    # Browser fingerprint
    user_agent = random.choice(USER_AGENTS)
    viewport = random.choice(RESOLUCIONES)
    
    return {
        "nombre": nombre,
        "apellido": apellido,
        "nombre_completo": f"{nombre} {apellido}",
        "email": email,
        "telefono_area": codigo_area,
        "telefono_numero": telefono_numero,
        "telefono_completo": f"{codigo_area}{telefono_numero}",
        "fecha_nacimiento": {
            "dia": dia_nac,
            "mes": mes_nac,
            "anio": anio_nac,
            "formato_ddmmaaaa": f"{dia_nac:02d}/{mes_nac:02d}/{anio_nac}"
        },
        "user_agent": user_agent,
        "viewport": {"width": viewport[0], "height": viewport[1]},
    }


def generar_delay_humanizado(minimo: float = 1.0, maximo: float = 3.5) -> float:
    """
    Genera un delay aleatorio que simula comportamiento humano.
    Usa distribución normal truncada para parecer más natural.
    """
    media = (minimo + maximo) / 2
    std = (maximo - minimo) / 4
    delay = random.gauss(media, std)
    return max(minimo, min(maximo, delay))


if __name__ == "__main__":
    # Test rápido
    for i in range(3):
        datos = generar_persona_placebo()
        print(f"\n--- Persona {i+1} ---")
        print(f"  Nombre: {datos['nombre_completo']}")
        print(f"  Email: {datos['email']}")
        print(f"  Tel: +549{datos['telefono_completo']}")
        print(f"  Nacimiento: {datos['fecha_nacimiento']['formato_ddmmaaaa']}")
        print(f"  UA: {datos['user_agent'][:50]}...")
        print(f"  Viewport: {datos['viewport']}")
        print(f"  Delay test: {generar_delay_humanizado():.2f}s")
