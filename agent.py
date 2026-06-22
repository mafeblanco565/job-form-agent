"""
job-form-agent - Agente principal
Automatiza el diligenciamiento de formularios de empleo usando Gemini AI

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
import google.generativeai as genai
from google.generativeai import protos

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

REGLAS DE SEGURIDAD:
- NO hacer clic en boton de enviar/submit/aplicar
- NO aceptar terminos sin confirmacion del usuario
- NO compartir informacion con terceros
"""


def _build_gemini_tools(claude_tools: list) -> list:
    """Convierte el formato de tools de Claude al formato de Gemini."""
    TYPE_MAP = {
        "string": protos.Type.STRING,
        "integer": protos.Type.INTEGER,
        "number": protos.Type.NUMBER,
        "boolean": protos.Type.BOOLEAN,
        "object": protos.Type.OBJECT,
        "array": protos.Type.ARRAY,
    }
    declarations = []
    for tool in claude_tools:
        props = {}
        for prop_name, prop_def in tool["input_schema"].get("properties", {}).items():
            t = TYPE_MAP.get(prop_def.get("type", "string"), protos.Type.STRING)
            props[prop_name] = protos.Schema(
                type=t,
                description=prop_def.get("description", "")
            )
        req = tool["input_schema"].get("required", [])
        declarations.append(protos.FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parameters=protos.Schema(
                type=protos.Type.OBJECT,
                properties=props,
                required=req
            ) if props else None
        ))
    return [protos.Tool(function_declarations=declarations)]


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

    genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))

    detector = FormDetector()
    form_type = detector.detect(url)
    await notify(f"Tipo de formulario detectado: {form_type}")

    headless = os.environ.get("BROWSER_HEADLESS", "false").lower() == "true"

    async with BrowserAgent(headless=headless) as browser:
        await notify(f"Navegando a: {url}")
        await browser.navigate(url)

        form_structure = await browser.get_form_structure()
        await notify(f"Formulario analizado: {len(form_structure)} campos encontrados")

        gemini_tools = _build_gemini_tools(browser.get_tool_definitions())
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=build_system_prompt(profile, photo_path),
            tools=gemini_tools
        )

        initial_message = f"""Necesito que llenes este formulario de empleo con mi informacion.

URL del formulario: {url}
Tipo detectado: {form_type}

Estructura del formulario encontrada:
{json.dumps(form_structure, ensure_ascii=False, indent=2)}

Por favor, llena todos los campos posibles usando mi perfil.
IMPORTANTE: NO hagas clic en el boton de enviar/submit al final.
Al terminar, toma un screenshot con get_screenshot.
"""
        contents = [{"role": "user", "parts": [{"text": initial_message}]}]

        max_iterations = 15
        for i in range(max_iterations):
            response = await model.generate_content_async(contents)

            has_tool_calls = any(
                hasattr(part, "function_call") and part.function_call.name
                for part in response.parts
            )

            if not has_tool_calls:
                await notify("Agente finalizo exitosamente.")
                for part in response.parts:
                    if hasattr(part, "text") and part.text:
                        await notify(f"RESUMEN:\n{part.text}")
                break

            # Agregar respuesta del modelo al historial
            contents.append({"role": "model", "parts": response.parts})

            # Ejecutar tools y recolectar resultados
            fn_responses = []
            for part in response.parts:
                if not (hasattr(part, "function_call") and part.function_call.name):
                    continue
                fn = part.function_call
                await notify(f"-> {fn.name}")
                args = dict(fn.args)
                result = await browser.execute_tool(fn.name, args)

                if fn.name == "get_screenshot" and result.get("success") and screenshot_callback:
                    await screenshot_callback(result["screenshot_base64"])

                fn_responses.append(
                    protos.Part(
                        function_response=protos.FunctionResponse(
                            name=fn.name,
                            response={"result": json.dumps(result, ensure_ascii=False)}
                        )
                    )
                )

            contents.append({"role": "user", "parts": fn_responses})

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
