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
Estos formularios tienen varios pasos. Navegalos usando click_text con el texto exacto del boton:
0. PRIMERO verifica con get_page_text: si la pagina muestra login/iniciar sesion -> DETENTE e informa al usuario
1. Si ves boton "APLICAR A ESTE PROCESO" -> usa click_text("APLICAR A ESTE PROCESO")
   - Puede aparecer un dropdown. Si aparece -> click_text("Redactar currículum")
   - Si no aparece dropdown, el boton navega directamente al formulario
2. Si ves "¿Cual es tu correo electronico?" -> llena el email con fill_input, luego click_text("CONTINUAR")
3. Si ves "Encontramos tu CV en nuestro sistema" -> click_text("Incluir un nuevo CV"), luego click_text("CONTINUAR")
4. Cuando llegues al formulario con campos Nombre/Apellido/Fecha -> llena todos los campos con fill_input
5. Despues de cada click_text o click_and_wait, usa get_page_text para ver en que paso estas

HERRAMIENTAS PARA NAVEGAR:
- click_text("texto del boton") -> para CUALQUIER boton por su texto visible (PREFERIR sobre click_and_wait)
- click_and_wait("#selector") -> solo si conoces el selector CSS exacto

BOTONES PERMITIDOS (usa click_text):
- "APLICAR A ESTE PROCESO", "CONTINUAR", "SIGUIENTE", "GUARDAR Y CONTINUAR", "Incluir un nuevo CV"

BOTONES PROHIBIDOS (NUNCA hacer clic):
- "Enviar postulacion", "Confirmar aplicacion", "Aplicar ahora", "Submit", "Enviar", "Postular"

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

PASOS A SEGUIR PARA PANDAPE:
1. Usa get_page_text para ver en que paso estas
2. Si la pagina muestra "Iniciar sesion", "Login" o "Ingresar" -> DETENTE y reporta: "Necesitas iniciar sesion en la ventana del navegador que se abrio. Una vez que hayas iniciado sesion, vuelve a intentar con la URL de la oferta."
3. Si ves la pagina de la oferta con boton "APLICAR A ESTE PROCESO" -> click_text("APLICAR A ESTE PROCESO")
4. Si aparece un dropdown con opciones -> click_text("Redactar currículum")
5. Si pide correo electronico -> fill_input con email del perfil, luego click_text("CONTINUAR")
6. Si ves "Encontramos tu CV" -> click_text("Incluir un nuevo CV"), luego click_text("CONTINUAR")
7. Cuando llegues al formulario (Nombre, Apellido, Fecha, etc.) -> get_form_structure y fill_input para cada campo
8. Al terminar todos los campos, toma screenshot con get_screenshot
9. NUNCA hagas clic en: "Enviar postulacion", "Confirmar", "Postular", "Aplicar ahora", "Submit"

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
