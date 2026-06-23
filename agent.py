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
    return f"""Eres un asistente experto en diligenciar formularios de empleo en Colombia.

PERFIL DEL CANDIDATO:
{json.dumps(profile, ensure_ascii=False, indent=2)}{photo_info}

INSTRUCCIONES:
1. Analiza el formulario de empleo que el usuario te proporciona
2. Mapea cada campo del formulario con los datos del perfil
3. Usa las herramientas disponibles para interactuar con el formulario
4. Llena TODOS los campos disponibles con la informacion del perfil
5. Si un campo no tiene informacion en el perfil, dejalo en blanco
6. Si hay campo de foto/imagen y se proporciono ruta de foto, usa upload_file para subirla
7. NUNCA envies/submitas el formulario - solo llenalo
8. Al finalizar, usa get_screenshot para tomar una captura y reporta un resumen

CAMPOS COMUNES EN FORMULARIOS COLOMBIANOS:
- Nombre / Primer nombre -> first_name
- Apellido / Apellidos -> last_name
- Correo / Email -> email
- Telefono / Celular -> phone
- Fecha de nacimiento -> birth_date (formato DD/MM/YYYY)
- Direccion -> address.street + address.number
- Ciudad -> address.city
- Pais -> address.country
- Cargo actual / Titulo -> professional_profile.title
- Perfil / Resumen -> professional_profile.summary
- Salario esperado -> professional_profile.salary_min / salary_max
- LinkedIn -> online.linkedin

FORMULARIOS MULTI-PASO (Pandape / Computrabajo):
Estos formularios tienen varios pasos antes del formulario real. Debes navegarlos asi:
1. Si ves boton "APLICAR A ESTE PROCESO" o similar -> usa click_and_wait para hacer clic
2. Si ves "¿Cual es tu correo electronico?" -> llena el email del perfil y usa click_and_wait en "CONTINUAR"
3. Si ves "Encontramos tu CV en nuestro sistema" -> selecciona "Incluir un nuevo CV" con click_element, luego click_and_wait en "CONTINUAR"
4. Cuando llegues al formulario con campos Nombre/Apellido/Fecha -> llena todos los campos
5. Despues de cada click_and_wait, usa get_form_structure para ver los nuevos campos disponibles

BOTONES PERMITIDOS (usa click_and_wait):
- "APLICAR A ESTE PROCESO", "CONTINUAR", "SIGUIENTE", "GUARDAR Y CONTINUAR"

BOTONES PROHIBIDOS (NUNCA hacer clic):
- "Enviar postulacion", "Confirmar aplicacion", "Aplicar ahora", "Submit", "Enviar"

REGLAS DE SEGURIDAD:
- NO hacer clic en el boton final de envio de la postulacion
- NO aceptar terminos sin confirmacion del usuario
- NO compartir informacion con terceros
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

    async with BrowserAgent(headless=headless) as browser:
        await notify(f"Navegando a: {url}")
        await browser.navigate(url)

        form_structure = await browser.get_form_structure()
        await notify(f"Formulario analizado: {len(form_structure)} campos encontrados")

        messages = [
            {
                "role": "user",
                "content": f"""Necesito que apliques a esta oferta de empleo y llenes el formulario con mi informacion.

URL: {url}
Tipo detectado: {form_type}
Campos encontrados en la pagina actual: {len(form_structure)}

PASOS A SEGUIR:
1. Usa get_page_text para entender en que paso del proceso estas
2. Si ves boton "APLICAR A ESTE PROCESO" o similar -> usa click_and_wait
3. Si pide email -> llenalo con el del perfil y click_and_wait en CONTINUAR
4. Si ves opciones de CV -> selecciona "Incluir un nuevo CV" con click_element, luego click_and_wait en CONTINUAR
5. Cuando llegues al formulario (Nombre, Apellido, Fecha, etc.) -> usa get_form_structure y llena todos los campos
6. Al terminar de llenar, toma un screenshot con get_screenshot
7. NUNCA hagas clic en el boton final de envio de postulacion

Estructura actual de la pagina:
{json.dumps(form_structure, ensure_ascii=False, indent=2)}
"""
            }
        ]

        max_iterations = 15
        for i in range(max_iterations):
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                system=build_system_prompt(profile, photo_path),
                messages=messages,
                tools=browser.get_tool_definitions()
            )

            if response.stop_reason == "end_turn":
                await notify("Agente finalizo exitosamente.")
                for block in response.content:
                    if hasattr(block, "text"):
                        await notify(f"RESUMEN:\n{block.text}")
                break

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        await notify(f"-> {block.name}")
                        result = await browser.execute_tool(block.name, block.input)

                        # Enviar screenshot al frontend pero NO incluir el base64 en el historial
                        if block.name == "get_screenshot" and result.get("success"):
                            if screenshot_callback:
                                await screenshot_callback(result["screenshot_base64"])
                            result = {"success": True, "message": "Screenshot capturado correctamente"}

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, ensure_ascii=False)
                        })

                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

        await notify("Formulario llenado. Revisa y envia manualmente.")

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
