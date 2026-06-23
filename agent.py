"""
job-form-agent - Agente principal
Automatiza el diligenciamiento de formularios de empleo usando Claude AI

Uso:
    python agent.py --url "https://empresa.pandape.computrabajo.com/Apply?..."
    python agent.py --url "https://..." --profile profile.json
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from anthropic import AsyncAnthropic

load_dotenv()
from browser_tools import BrowserAgent
from form_detector import FormDetector


def load_profile(profile_path: str = "profile.json") -> dict:
    path = Path(profile_path)
    if not path.exists():
        raise FileNotFoundError(f"Perfil no encontrado: {profile_path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_system_prompt(profile: dict, photo_path: str = None) -> str:
    photo_info = f"\nFOTO DEL CANDIDATO (ruta local para upload): {photo_path}" if photo_path else ""
    return f"""Eres un asistente experto en diligenciar y enviar formularios de empleo en Colombia.

PERFIL DEL CANDIDATO:
{json.dumps(profile, ensure_ascii=False, indent=2)}{photo_info}

TU TAREA - SIGUE ESTOS PASOS EN ORDEN:

PASO 1 - Ver el formulario:
- Usa get_page_text para leer el texto completo de la pagina
- Identifica todas las secciones visibles y colapsadas

PASO 2 - Expandir secciones colapsadas:
- Si hay secciones tipo acordeon (Habilidades, Salario, Informacion adicional, etc.)
  USA click_text con el nombre exacto de cada seccion para expandirla
- Despues de expandir cada seccion, usa get_form_structure para ver los campos nuevos
- Repite para TODAS las secciones colapsadas antes de llenar cualquier campo

PASO 3 - Llenar todos los campos:
- Usa get_form_structure para ver los selectores exactos de cada campo
- Llena con fill_input todos los campos que tengan datos en el perfil
- NO toques botones de foto ("Añadir foto", "Subir foto", "Agregar foto") - la foto es opcional y abre un dialogo complejo, ignorala completamente
- CAMPO CRITICO "Salario deseado":
  * El campo con placeholder "Entre $ (Bruto mensual)" es salary_min
  * El campo con placeholder "y $ (Bruto Mensual)" es salary_max
  * Si salary_min es 0 o vacio en el perfil, usa 3000000 como valor por defecto
  * Si salary_max es 0 o vacio, usa 5000000 como valor por defecto
  * ESTE CAMPO ES OBLIGATORIO - sin el SIGUIENTE queda gris
- Si hay checkboxes de terminos/privacidad ya marcados, no los toques
- Para dropdowns "Jornada" y "Tipo de contrato" usa select_option o click_text

PASO 4 - Tu tarea termina cuando hayas llenado todos los campos visibles.
NO necesitas hacer clic en SIGUIENTE - eso lo maneja el sistema automaticamente.
Solo toma get_screenshot cuando termines de llenar.

MAPEO DE CAMPOS:
- Nombre / Primer nombre -> personal.first_name
- Apellido / Apellidos -> personal.last_name
- Correo / Email -> personal.email
- Telefono / Celular -> personal.phone
- Fecha de nacimiento -> personal.birth_date (DD/MM/YYYY)
- Direccion -> personal.address.street
- Ciudad -> personal.address.city
- Pais -> personal.address.country
- Titulo profesional -> professional_profile.title
- Perfil / Resumen -> professional_profile.summary
- Entre $ Bruto mensual -> professional_profile.salary_min (default 3000000 si es 0)
- y $ Bruto Mensual -> professional_profile.salary_max (default 5000000 si es 0)
- Habilidades -> skills (lista separada por comas)
- LinkedIn -> online.linkedin
"""


async def run_agent(
    url: str,
    profile_path: str = "profile.json",
    profile_data: dict = None,
    photo_path: str = None,
    update_callback=None,
    screenshot_callback=None,
):
    async def notify(msg: str):
        print(msg)
        if update_callback:
            await update_callback(msg)

    profile = profile_data if profile_data else load_profile(profile_path)
    await notify(f"Perfil cargado: {profile['personal']['first_name']} {profile['personal']['last_name']}")

    client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    detector = FormDetector()
    form_type = detector.detect(url)
    await notify(f"Tipo de formulario detectado: {form_type}")

    headless = os.environ.get("BROWSER_HEADLESS", "false").lower() == "true"
    email = profile.get("personal", {}).get("email", "")

    async with BrowserAgent(headless=headless) as browser:
        await notify(f"Navegando a: {url}")
        await browser.navigate(url)

        # Para Pandape/Computrabajo: ejecutar el flujo completo en Python (sin AI)
        if any(d in url.lower() for d in ["pandape", "computrabajo"]):
            nav = await browser.pandape_apply_flow(email=email, profile_data=profile, notify_fn=update_callback)

            # Tomar screenshot siempre, sin importar el resultado
            sc = await browser.get_screenshot()
            if sc.get("success") and screenshot_callback:
                await screenshot_callback(sc["screenshot_base64"])

            if not nav.get("success"):
                await notify(f"Error en navegacion: {nav.get('error', 'desconocido')}")
                return

            if nav.get("submitted"):
                # PASO 8 alcanzado — postulación enviada
                await notify("✓ POSTULACION ENVIADA — revisa tu correo para verificar identidad y confirmar candidatura")
                return

            # No se pudo enviar automáticamente — informar motivo
            error_msg = nav.get("error", "")
            if error_msg:
                await notify(f"No se completó la postulación: {error_msg}")
            else:
                await notify("No se alcanzó la página de verificación. Verifica el formulario en el screenshot.")
            return

        if not update_callback:
            input("Presiona Enter para cerrar el navegador...")


def main():
    parser = argparse.ArgumentParser(
        description="Agente para diligenciar formularios de empleo automaticamente"
    )
    parser.add_argument("--url", required=True, help="URL del formulario de empleo")
    parser.add_argument("--profile", default="profile.json", help="Ruta al perfil JSON")
    args = parser.parse_args()
    asyncio.run(run_agent(args.url, args.profile))


if __name__ == "__main__":
    main()
