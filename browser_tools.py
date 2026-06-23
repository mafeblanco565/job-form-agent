"""
browser_tools.py - Herramientas de automatizacion del navegador

Usa Playwright para controlar el navegador y llenar formularios.
Compatible con formularios de Pandape, Computrabajo, LinkedIn y otros.
"""

import asyncio
import json
import base64
import os
from pathlib import Path
from typing import Any
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

# Perfil persistente: guarda cookies y sesiones entre ejecuciones del agente
_DEFAULT_PROFILE = str(Path(__file__).parent / "data" / "browser-profile")


class BrowserAgent:
    """Agente de navegador con Playwright para automatizar formularios."""

    def __init__(self, headless: bool = False):
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        profile_dir = os.environ.get("PLAYWRIGHT_PROFILE_DIR", _DEFAULT_PROFILE)
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        args = ["--disable-blink-features=AutomationControlled"]
        if self.headless:
            args += ["--no-sandbox", "--disable-dev-shm-usage"]

        # Contexto persistente: las cookies/sesiones se guardan entre ejecuciones.
        # Primera vez: el usuario inicia sesion manualmente en la ventana que se abre.
        # Siguientes veces: el agente ya esta autenticado automaticamente.
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=self.headless,
            args=args,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        self.page = await self.context.new_page()
        return self

    async def __aexit__(self, *args):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
    
    async def navigate(self, url: str) -> dict:
        await self.page.goto(url, wait_until="networkidle", timeout=30000)
        return {"success": True, "url": self.page.url, "title": await self.page.title()}
    
    async def get_form_structure(self) -> dict:
        return await self.page.evaluate("""() => {
            const inputs = Array.from(document.querySelectorAll(
                'input:not([type="hidden"]):not([type="submit"]), select, textarea'
            ));
            return inputs.map(el => ({
                tag: el.tagName, type: el.type || '', id: el.id || '',
                name: el.name || '', placeholder: el.placeholder || '',
                label: (() => {
                    if (el.id) {
                        const lbl = document.querySelector('label[for="' + el.id + '"]');
                        if (lbl) return lbl.textContent.trim();
                    }
                    const parent = el.closest('label');
                    return parent ? parent.textContent.trim() : '';
                })(),
                required: el.required || el.getAttribute('aria-required') === 'true'
            }));
        }""")
    
    async def fill_input(self, selector: str, value: str) -> dict:
        try:
            element = await self.page.wait_for_selector(selector, timeout=5000)
            await element.triple_click()
            await element.type(value, delay=50)
            return {"success": True, "selector": selector, "value": value}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def select_option(self, selector: str, value: str) -> dict:
        try:
            await self.page.select_option(selector, label=value)
            return {"success": True, "selector": selector, "value": value}
        except Exception as e:
            try:
                await self.page.select_option(selector, value=value)
                return {"success": True}
            except Exception as e2:
                return {"success": False, "error": str(e2)}
    
    async def click_element(self, selector: str) -> dict:
        try:
            await self.page.click(selector)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_screenshot(self) -> dict:
        screenshot = await self.page.screenshot(full_page=False)
        return {"success": True, "screenshot_base64": base64.b64encode(screenshot).decode()}
    
    async def get_page_text(self) -> dict:
        text = await self.page.inner_text("body")
        return {"success": True, "text": text[:2000]}
    
    async def fill_date_field(self, selector: str, date: str) -> dict:
        try:
            element = await self.page.wait_for_selector(selector, timeout=5000)
            await element.triple_click()
            await element.type(date, delay=100)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _dismiss_cookies(self):
        """Cierra popup de cookies si existe."""
        try:
            for sel in [
                "button:has-text('Aceptar y cerrar')",
                "button:has-text('Aceptar')",
                "button:has-text('Accept')",
                "#onetrust-accept-btn-handler",
            ]:
                btn = self.page.locator(sel).first
                if await btn.is_visible(timeout=1500):
                    await btn.click()
                    await self.page.wait_for_timeout(400)
                    return
        except Exception:
            pass

    async def _click_visible(self, *texts, timeout=6000):
        """Hace clic en el primer elemento visible que contenga alguno de los textos dados."""
        for text in texts:
            try:
                el = self.page.get_by_text(text, exact=False).first
                if await el.is_visible(timeout=timeout):
                    await el.click()
                    return True
            except Exception:
                pass
        return False

    async def pandape_apply_flow(self, email: str, profile_data: dict = None, notify_fn=None) -> dict:
        """
        Ejecuta los 8 pasos completos del flujo Pandape en Python puro.
        No depende del AI para ningún paso.
        """
        profile_data = profile_data or {}
        personal = profile_data.get("personal", {})
        pp = profile_data.get("professional_profile", {})

        first_name = personal.get("first_name", "")
        last_name  = personal.get("last_name", "")
        birth_date = personal.get("birth_date", "")
        phone      = personal.get("phone", "").replace("+57", "").replace(" ", "").strip()
        sal_min    = str(int(pp.get("salary_min") or 3000000))
        sal_max    = str(int(pp.get("salary_max") or 5000000))

        async def log(msg):
            if notify_fn:
                await notify_fn(msg)

        async def safe_fill(selector, value):
            """Llena un campo si está visible y vacío."""
            if not value:
                return False
            try:
                el = self.page.locator(selector).first
                if not await el.is_visible(timeout=2000):
                    return False
                current = await el.input_value()
                if current.strip():
                    return True  # ya tiene valor
                await el.click()
                await el.fill(value)
                await self.page.wait_for_timeout(150)
                return True
            except Exception:
                return False

        async def safe_click(selector, timeout=3000):
            try:
                el = self.page.locator(selector).first
                if await el.is_visible(timeout=timeout):
                    await el.click()
                    return True
            except Exception:
                pass
            return False

        # ── PASO 3: Clic en APLICAR A ESTE PROCESO ─────────────────────────
        await log("Paso 3: Clic en APLICAR A ESTE PROCESO...")
        await self._dismiss_cookies()
        await self.page.wait_for_timeout(800)

        clicked = False
        for _ in range(3):
            for loc in [
                self.page.get_by_text("APLICAR A ESTE PROCESO", exact=False).first,
                self.page.locator("button", has_text="APLICAR").first,
            ]:
                try:
                    if await loc.is_visible(timeout=2000):
                        await loc.click()
                        clicked = True
                        break
                except Exception:
                    pass
            if clicked:
                break
            await self.page.wait_for_timeout(600)

        if not clicked:
            return {"success": False, "step": "apply_button", "error": "No se encontró APLICAR A ESTE PROCESO"}

        await self.page.wait_for_timeout(1200)

        # ── PASO 3b: Dropdown → Redactar currículum ─────────────────────────
        for text in ["Redactar currículum", "Redactar curriculum"]:
            try:
                el = self.page.get_by_text(text, exact=False).first
                if await el.is_visible(timeout=2000):
                    await el.click()
                    await log("✓ Redactar currículum seleccionado")
                    break
            except Exception:
                pass
        await self.page.wait_for_timeout(2000)

        # ── PASO 4: Correo electrónico + CONTINUAR ──────────────────────────
        page_text = await self.page.inner_text("body")
        if "correo" in page_text.lower() or "email" in page_text.lower():
            await log(f"Paso 4: Ingresando correo {email}...")
            try:
                inp = self.page.locator("input[type='email'], input[placeholder*='orreo' i]").first
                await inp.wait_for(state="visible", timeout=5000)
                await inp.fill(email)
                await self.page.wait_for_timeout(300)
                await self._click_visible("CONTINUAR", "Continuar")
                await self.page.wait_for_timeout(2500)
                await log("✓ Correo ingresado")
            except Exception as e:
                await log(f"Error correo: {e}")

        # ── PASO 5: CV → Incluir nuevo CV + CONTINUAR ───────────────────────
        page_text = await self.page.inner_text("body")
        if "encontramos tu cv" in page_text.lower() or "nuevo cv" in page_text.lower():
            await log("Paso 5: Seleccionando Incluir un nuevo CV...")
            try:
                # El radio "Incluir un nuevo CV" puede estar ya seleccionado
                await self._click_visible("Incluir un nuevo CV", "nuevo CV")
                await self.page.wait_for_timeout(500)
                await self._click_visible("CONTINUAR", "Continuar")
                await self.page.wait_for_timeout(2500)
                await log("✓ CV paso completado")
            except Exception as e:
                await log(f"Error CV: {e}")

        # ── PASO 6: Llenar Información personal ─────────────────────────────
        await self.page.wait_for_timeout(1000)
        await log("Paso 6: Llenando información personal...")

        await safe_fill('input[placeholder="Nombre"]', first_name)
        await safe_fill('input[placeholder="Apellido"]', last_name)

        # Fecha de nacimiento — intentar fill y luego type si falla
        if birth_date:
            filled = await safe_fill('input[placeholder="Fecha de nacimiento"]', birth_date)
            if not filled:
                try:
                    el = self.page.locator('input[placeholder="Fecha de nacimiento"]').first
                    if await el.is_visible(timeout=1500):
                        await el.click()
                        await self.page.keyboard.type(birth_date, delay=80)
                        await self.page.keyboard.press("Tab")
                except Exception:
                    pass

        # Teléfono
        if phone:
            await safe_fill('input[placeholder*="Teléfono" i]', phone)
            await safe_fill('input[placeholder*="Móvil" i]', phone)

        await log("✓ Información personal llenada")

        # ── PASO 7a: Expandir y llenar Salario deseado (REQUERIDO) ──────────
        await log("Paso 7: Expandiendo y llenando Salario deseado...")
        try:
            sal_header = self.page.get_by_text("Salario deseado", exact=False).first
            if await sal_header.is_visible(timeout=2000):
                await sal_header.click()
                await self.page.wait_for_timeout(800)
        except Exception:
            pass

        await safe_fill('input[placeholder*="Entre"]', sal_min)
        await safe_fill('input[placeholder*="Bruto Mensual" i]', sal_max)
        await safe_fill('input[placeholder*="bruto mensual" i]', sal_max)
        await self.page.wait_for_timeout(500)
        await log(f"✓ Salario llenado: {sal_min} - {sal_max}")

        # ── PASO 7b: Clic en ENVIAR APLICACIÓN ─────────────────────────────
        await log("Paso 7: Buscando botón ENVIAR APLICACIÓN...")
        await self.page.wait_for_timeout(1000)

        enviar_clicked = False
        for btn_text in ["ENVIAR APLICACIÓN", "ENVIAR APLICACION", "Enviar aplicación"]:
            try:
                btn = self.page.get_by_text(btn_text, exact=False).first
                if await btn.is_visible(timeout=2000):
                    is_enabled = await btn.is_enabled(timeout=1000)
                    if is_enabled:
                        await btn.click()
                        enviar_clicked = True
                        await log(f"✓ Clic en '{btn_text}'")
                        break
                    else:
                        await log(f"Botón '{btn_text}' visible pero deshabilitado — campos requeridos incompletos")
            except Exception:
                pass

        if not enviar_clicked:
            return {"success": True, "submitted": False,
                    "error": "ENVIAR APLICACIÓN deshabilitado — verifica Nombre, Apellido o Salario"}

        # ── PASO 8: Esperar página de verificación ──────────────────────────
        try:
            await self.page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        await self.page.wait_for_timeout(2000)

        page_text = await self.page.inner_text("body")
        if "verificar tu identidad" in page_text.lower() or "enviamos un correo" in page_text.lower():
            await log("✓ PASO 8: POSTULACION ENVIADA — revisa tu correo para verificar identidad")
            return {"success": True, "submitted": True}
        else:
            await log("ENVIAR presionado pero no apareció página de verificación — puede haber error en el formulario")
            return {"success": True, "submitted": False}

    async def dismiss_cookies(self) -> dict:
        await self._dismiss_cookies()
        return {"success": True}

    async def click_and_wait(self, selector: str) -> dict:
        try:
            await self._dismiss_cookies()
            await self.page.click(selector)
            await self.page.wait_for_load_state("networkidle", timeout=15000)
            return {"success": True, "url": self.page.url, "title": await self.page.title()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def click_text(self, text: str) -> dict:
        try:
            await self._dismiss_cookies()
            locator = self.page.get_by_text(text, exact=False).first
            await locator.wait_for(state="visible", timeout=8000)
            await locator.click()
            try:
                await self.page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            await self.page.wait_for_timeout(800)
            page_text = await self.page.inner_text("body")
            return {"success": True, "url": self.page.url, "page_preview": page_text[:500]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def expand_section(self, section_text: str) -> dict:
        """Expande una seccion colapsada de acordeon haciendo clic en su encabezado."""
        try:
            el = self.page.get_by_text(section_text, exact=False).first
            await el.wait_for(state="visible", timeout=5000)
            await el.click()
            await self.page.wait_for_timeout(600)
            return {"success": True, "expanded": section_text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def upload_file(self, selector: str, file_path: str) -> dict:
        try:
            await self.page.set_input_files(selector, file_path)
            return {"success": True, "selector": selector, "file": file_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def execute_js(self, script: str) -> dict:
        try:
            result = await self.page.evaluate(script)
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_tool_definitions(self) -> list:
        return [
            {
                "name": "navigate",
                "description": "Navega a una URL",
                "input_schema": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"]
                }
            },
            {
                "name": "fill_input",
                "description": "Llena un campo de texto con un valor",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string"},
                        "value": {"type": "string"}
                    },
                    "required": ["selector", "value"]
                }
            },
            {
                "name": "select_option",
                "description": "Selecciona una opcion en un dropdown",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string"},
                        "value": {"type": "string"}
                    },
                    "required": ["selector", "value"]
                }
            },
            {
                "name": "click_element",
                "description": "Hace clic en un elemento",
                "input_schema": {
                    "type": "object",
                    "properties": {"selector": {"type": "string"}},
                    "required": ["selector"]
                }
            },
            {
                "name": "get_form_structure",
                "description": "Obtiene todos los campos del formulario",
                "input_schema": {"type": "object", "properties": {}}
            },
            {
                "name": "get_screenshot",
                "description": "Toma un screenshot para analisis visual",
                "input_schema": {"type": "object", "properties": {}}
            },
            {
                "name": "get_page_text",
                "description": "Obtiene el texto visible de la pagina",
                "input_schema": {"type": "object", "properties": {}}
            },
            {
                "name": "fill_date_field",
                "description": "Llena un campo de fecha en formato DD/MM/YYYY",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string"},
                        "date": {"type": "string", "description": "Formato DD/MM/YYYY"}
                    },
                    "required": ["selector", "date"]
                }
            },
            {
                "name": "click_and_wait",
                "description": "Hace clic en un elemento CSS y espera que cargue la pagina. Usa click_text si no conoces el selector exacto.",
                "input_schema": {
                    "type": "object",
                    "properties": {"selector": {"type": "string"}},
                    "required": ["selector"]
                }
            },
            {
                "name": "click_text",
                "description": "Busca y hace clic en cualquier elemento por su texto visible. USAR para botones como 'APLICAR A ESTE PROCESO', 'CONTINUAR', 'SIGUIENTE', 'Incluir un nuevo CV'. Cierra cookies automaticamente antes de hacer clic.",
                "input_schema": {
                    "type": "object",
                    "properties": {"text": {"type": "string", "description": "Texto visible del boton o enlace a hacer clic"}},
                    "required": ["text"]
                }
            },
            {
                "name": "expand_section",
                "description": "Expande una seccion colapsada (acordeon) del formulario haciendo clic en su titulo. Usar antes de fill_input para secciones como 'Habilidades', 'Salario deseado', 'Informacion adicional'.",
                "input_schema": {
                    "type": "object",
                    "properties": {"section_text": {"type": "string", "description": "Texto del encabezado de la seccion a expandir"}},
                    "required": ["section_text"]
                }
            },
            {
                "name": "upload_file",
                "description": "Sube un archivo (foto/documento) a un campo de tipo file",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string"},
                        "file_path": {"type": "string", "description": "Ruta local al archivo"}
                    },
                    "required": ["selector", "file_path"]
                }
            },
            {
                "name": "execute_js",
                "description": "Ejecuta JavaScript en la pagina",
                "input_schema": {
                    "type": "object",
                    "properties": {"script": {"type": "string"}},
                    "required": ["script"]
                }
            }
        ]
    
    async def execute_tool(self, tool_name: str, tool_input: dict) -> Any:
        tool_map = {
            "navigate": self.navigate,
            "click_and_wait": self.click_and_wait,
            "click_text": self.click_text,
            "expand_section": self.expand_section,
            "fill_input": self.fill_input,
            "select_option": self.select_option,
            "click_element": self.click_element,
            "get_form_structure": self.get_form_structure,
            "get_screenshot": self.get_screenshot,
            "get_page_text": self.get_page_text,
            "fill_date_field": self.fill_date_field,
            "upload_file": self.upload_file,
            "execute_js": self.execute_js,
        }
        if tool_name not in tool_map:
            return {"success": False, "error": f"Herramienta desconocida: {tool_name}"}
        return await tool_map[tool_name](**tool_input)
