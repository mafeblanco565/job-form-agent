"""
web/app.py - Servidor FastAPI para Job Form Agent
Corre con: uvicorn web.app:app --reload --port 8000
"""

import asyncio
import base64
import json
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

# Permite importar desde el directorio raiz del proyecto
sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv(Path(__file__).parent.parent / ".env")

import google.generativeai as genai
from agent import build_system_prompt, load_profile, run_agent

# En Railway apunta al Volume montado en /data; localmente usa web/uploads
UPLOADS_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent / "uploads"))
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Job Form Agent")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Cola de mensajes SSE por sesion
agent_queues: dict[str, asyncio.Queue] = {}


# ─── Pagina principal ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


# ─── Screenshot ───────────────────────────────────────────────────────────────

@app.get("/screenshot")
async def get_screenshot():
    path = UPLOADS_DIR / "screenshot.png"
    if not path.exists():
        return Response(status_code=404)
    return Response(content=path.read_bytes(), media_type="image/png")


# ─── Subir CV ─────────────────────────────────────────────────────────────────

@app.post("/upload-cv")
async def upload_cv(file: UploadFile = File(...)):
    if not file.filename.endswith(".docx"):
        return JSONResponse({"error": "Solo se aceptan archivos .docx"}, status_code=400)

    cv_path = UPLOADS_DIR / "cv.docx"
    cv_path.write_bytes(await file.read())

    # Extraer texto del .docx
    try:
        from docx import Document
        doc = Document(cv_path)
        full_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        return JSONResponse({"error": f"No se pudo leer el archivo: {str(e)}"}, status_code=400)

    if not full_text.strip():
        return JSONResponse({"error": "El archivo esta vacio o no tiene texto legible"}, status_code=400)

    # Usar Gemini Flash para extraer el perfil estructurado
    genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
    model = genai.GenerativeModel("gemini-2.0-flash")
    response = await model.generate_content_async(
        f"""Extrae la informacion del siguiente CV y devuelvela en formato JSON con esta estructura exacta.
Si un campo no esta en el CV, dejalo vacio ("") o 0 para numeros o [] para listas.
Solo devuelve el JSON, sin explicaciones ni markdown.

{{
  "personal": {{
    "first_name": "",
    "last_name": "",
    "email": "",
    "phone": "",
    "birth_date": "",
    "nationality": "",
    "id_type": "",
    "gender": "",
    "civil_status": "",
    "address": {{
      "street": "",
      "number": "",
      "city": "",
      "state": "",
      "country": "",
      "postal_code": ""
    }}
  }},
  "online": {{
    "linkedin": "",
    "portfolio": ""
  }},
  "professional_profile": {{
    "title": "",
    "summary": "",
    "desired_position": "",
    "salary_min": 0,
    "salary_max": 0,
    "salary_currency": "COP",
    "work_type": "",
    "contract_type": ""
  }},
  "experience": [],
  "education": [],
  "courses": [],
  "languages": [],
  "skills": []
}}

CV:
{full_text}"""
    )

    try:
        text = response.text.strip()
        # Limpiar posible markdown
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        profile = json.loads(text)
    except Exception as e:
        return JSONResponse({"error": f"Error al parsear respuesta de IA: {str(e)}"}, status_code=500)

    # Guardar perfil extraido
    profile_path = UPLOADS_DIR / "profile_extracted.json"
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")

    missing = _evaluate_missing_fields(profile)
    return {"profile": profile, "missing": missing}


def _evaluate_missing_fields(profile: dict) -> list:
    p = profile.get("personal", {})
    addr = p.get("address", {})
    pp = profile.get("professional_profile", {})
    checks = [
        ("first_name",    "Nombre",               p.get("first_name")),
        ("last_name",     "Apellido",              p.get("last_name")),
        ("email",         "Correo electronico",    p.get("email")),
        ("phone",         "Telefono / Celular",    p.get("phone")),
        ("birth_date",    "Fecha de nacimiento",   p.get("birth_date")),
        ("city",          "Ciudad",                addr.get("city")),
        ("country",       "Pais",                  addr.get("country")),
        ("title",         "Titulo profesional",    pp.get("title")),
        ("summary",       "Perfil / Resumen",      pp.get("summary")),
        ("salary_min",    "Salario esperado",      pp.get("salary_min")),
        ("linkedin",      "LinkedIn",              profile.get("online", {}).get("linkedin")),
        ("experience",    "Experiencia laboral",   profile.get("experience")),
        ("education",     "Educacion",             profile.get("education")),
        ("skills",        "Habilidades",           profile.get("skills")),
        ("languages",     "Idiomas",               profile.get("languages")),
    ]
    missing = []
    for key, label, value in checks:
        if not value or value == 0 or value == []:
            missing.append({"key": key, "label": label})
    return missing


# ─── Subir foto ───────────────────────────────────────────────────────────────

@app.post("/upload-photo")
async def upload_photo(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        return JSONResponse({"error": "Solo JPG, PNG o WEBP"}, status_code=400)
    photo_path = UPLOADS_DIR / f"photo{ext}"
    photo_path.write_bytes(await file.read())
    return {"success": True, "path": str(photo_path)}


# ─── Ejecutar agente ──────────────────────────────────────────────────────────

@app.post("/run-agent")
async def start_agent(url: str = Form(...)):
    profile_path = UPLOADS_DIR / "profile_extracted.json"
    if not profile_path.exists():
        return JSONResponse({"error": "Primero sube tu CV"}, status_code=400)

    # Detectar foto si existe
    photo_path = None
    for ext in [".jpg", ".jpeg", ".png", ".webp"]:
        candidate = UPLOADS_DIR / f"photo{ext}"
        if candidate.exists():
            photo_path = str(candidate)
            break

    session_id = uuid.uuid4().hex[:8]
    queue: asyncio.Queue = asyncio.Queue()
    agent_queues[session_id] = queue

    async def status_callback(msg: str):
        await queue.put({"type": "log", "text": msg})

    async def screenshot_callback(b64: str):
        # Guardar screenshot en disco
        img_data = base64.b64decode(b64)
        (UPLOADS_DIR / "screenshot.png").write_bytes(img_data)
        await queue.put({"type": "screenshot"})

    async def run():
        try:
            profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
            await run_agent(
                url=url,
                profile_data=profile_data,
                photo_path=photo_path,
                update_callback=status_callback,
                screenshot_callback=screenshot_callback,
            )
        except Exception as e:
            await queue.put({"type": "error", "text": str(e)})
        finally:
            await queue.put({"type": "done"})

    asyncio.create_task(run())
    return {"session_id": session_id}


# ─── SSE de estado ────────────────────────────────────────────────────────────

@app.get("/status/{session_id}")
async def status_stream(session_id: str):
    queue = agent_queues.get(session_id)
    if not queue:
        return JSONResponse({"error": "Sesion no encontrada"}, status_code=404)

    async def generator():
        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("type") in ("done", "error"):
                break

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
