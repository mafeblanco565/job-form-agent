"""
web/app.py - Servidor FastAPI para Job Form Agent
Corre con: uvicorn web.app:app --reload --port 8000
"""

import asyncio
import base64
import json
import os
import sys
import threading
import traceback
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

# Permite importar desde el directorio raiz del proyecto
sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv(Path(__file__).parent.parent / ".env")

from anthropic import AsyncAnthropic
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


@app.get("/mode")
async def get_mode():
    is_railway = bool(
        os.environ.get("RAILWAY_ENVIRONMENT")
        or os.environ.get("RAILWAY_PROJECT_ID")
        or os.environ.get("RAILWAY_SERVICE_ID")
    )
    return {"mode": "railway" if is_railway else "local"}


# ─── Perfil guardado ──────────────────────────────────────────────────────────

@app.get("/profile")
async def get_saved_profile():
    """Devuelve el perfil guardado si existe, sin llamar a la API de Claude."""
    profile_path = UPLOADS_DIR / "profile_extracted.json"
    if not profile_path.exists():
        return JSONResponse({"exists": False})
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        missing = _evaluate_missing_fields(profile)
        return {"exists": True, "profile": profile, "missing": missing}
    except Exception as e:
        return JSONResponse({"exists": False, "error": str(e)})


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

    prompt = f"""Extrae la informacion del siguiente CV y devuelvela en formato JSON con esta estructura exacta.
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

    # Intentar con Gemini (gratis) primero, luego Claude como fallback
    raw_text = None
    gemini_key = os.environ.get("GEMINI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            result = model.generate_content(prompt)
            raw_text = result.text
        except Exception as e:
            raw_text = None

    if raw_text is None and anthropic_key:
        try:
            client = AsyncAnthropic(api_key=anthropic_key)
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}]
            )
            raw_text = response.content[0].text
        except Exception as e:
            return JSONResponse({"error": f"Error de IA: {str(e)}"}, status_code=500)

    if raw_text is None:
        return JSONResponse(
            {"error": "Configura GEMINI_API_KEY (gratis) o ANTHROPIC_API_KEY en el archivo .env"},
            status_code=500
        )

    try:
        text = raw_text.strip()
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

    # Capturamos el loop principal de FastAPI para poder enviar eventos desde el thread
    main_loop = asyncio.get_event_loop()

    def _bridge(coro):
        """Ejecuta una corutina en el loop principal desde un thread."""
        asyncio.run_coroutine_threadsafe(coro, main_loop).result(timeout=10)

    def run_in_thread():
        # En Windows, uvicorn usa SelectorEventLoop que no soporta subprocesos
        # (requeridos por Playwright). Usamos ProactorEventLoop en un thread separado.
        if sys.platform == "win32":
            loop = asyncio.ProactorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def status_callback(msg: str):
            _bridge(queue.put({"type": "log", "text": msg}))

        async def screenshot_callback(b64: str):
            img_data = base64.b64decode(b64)
            (UPLOADS_DIR / "screenshot.png").write_bytes(img_data)
            _bridge(queue.put({"type": "screenshot"}))

        async def _run():
            try:
                profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
                await run_agent(
                    url=url,
                    profile_data=profile_data,
                    photo_path=photo_path,
                    update_callback=status_callback,
                    screenshot_callback=screenshot_callback,
                )
            except BaseException as e:
                tb = traceback.format_exc()
                msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                _bridge(queue.put({"type": "error", "text": msg}))
            finally:
                _bridge(queue.put({"type": "done"}))

        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()

    threading.Thread(target=run_in_thread, daemon=True).start()
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
