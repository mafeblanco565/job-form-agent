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
from anthropic import Anthropic

load_dotenv()
from browser_tools import BrowserAgent
from form_detector import FormDetector


def load_profile(profile_path: str = "profile.json") -> dict:
    """Carga el perfil del candidato desde un archivo JSON."""
    path = Path(profile_path)
    if not path.exists():
        raise FileNotFoundError(f"Perfil no encontrado: {profile_path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_system_prompt(profile: dict) -> str:
    """Construye el system prompt con el perfil del candidato."""
    return f"""Eres un asistente experto en diligenciar formularios de empleo en Colombia.

PERFIL DEL CANDIDATO:
{json.dumps(profile, ensure_ascii=False, indent=2)}

INSTRUCCIONES:
1. Analiza el formulario de empleo que el usuario te proporciona
2. Mapea cada campo del formulario con los datos del perfil
3. Usa browser_tools para interactuar con el formulario
4. Llena TODOS los campos disponibles con la informacion del perfil
5. Si un campo no tiene informacion en el perfil, dejalo en blanco
6. NUNCA envies/submitas el formulario - solo llenalo
7. Al finalizar, reporta un resumen de lo que llenaste

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


async def run_agent(url: str, profile_path: str = "profile.json"):
    """Ejecuta el agente de diligenciamiento de formularios."""
    
    # Cargar perfil
    profile = load_profile(profile_path)
    print(f"Perfil cargado: {profile['personal']['first_name']} {profile['personal']['last_name']}")
    
    # Inicializar cliente Anthropic
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    
    # Inicializar detector de formularios
    detector = FormDetector()
    form_type = detector.detect(url)
    print(f"Tipo de formulario detectado: {form_type}")
    
    # Inicializar agente de navegador
    async with BrowserAgent() as browser:
        # Navegar al formulario
        print(f"Navegando a: {url}")
        await browser.navigate(url)
        
        # Obtener estructura del formulario
        form_structure = await browser.get_form_structure()
        
        # Construir historial de mensajes
        messages = [
            {
                "role": "user",
                "content": f"""Necesito que llenes este formulario de empleo con mi informacion.

URL del formulario: {url}
Tipo detectado: {form_type}

Estructura del formulario encontrada:
{json.dumps(form_structure, ensure_ascii=False, indent=2)}

Por favor, llena todos los campos posibles usando mi perfil. 
IMPORTANTE: NO hagas clic en el boton de enviar/submit al final.
"""
            }
        ]
        
        # Ejecutar el agente con loop de herramientas
        max_iterations = 10
        for i in range(max_iterations):
            response = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=4096,
                system=build_system_prompt(profile),
                messages=messages,
                tools=browser.get_tool_definitions()
            )
            
            # Verificar si terminamos
            if response.stop_reason == "end_turn":
                print("\nAgente finalizo exitosamente.")
                # Extraer y mostrar el resumen final
                for block in response.content:
                    if hasattr(block, 'text'):
                        print("\nRESUMEN DEL AGENTE:")
                        print(block.text)
                break
            
            # Procesar tool calls
            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        print(f"  -> Ejecutando: {block.name}({list(block.input.keys())})")
                        result = await browser.execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, ensure_ascii=False)
                        })
                
                # Agregar respuesta del asistente y resultados al historial
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
        
        print("\nFormulario llenado. Por favor revisa y envia manualmente.")
        input("Presiona Enter para cerrar el navegador...")


def main():
    parser = argparse.ArgumentParser(
        description="Agente para diligenciar formularios de empleo automaticamente"
    )
    parser.add_argument(
        "--url", 
        required=True,
        help="URL del formulario de empleo"
    )
    parser.add_argument(
        "--profile",
        default="profile.json",
        help="Ruta al archivo de perfil JSON (default: profile.json)"
    )
    
    args = parser.parse_args()
    asyncio.run(run_agent(args.url, args.profile))


if __name__ == "__main__":
    main()
