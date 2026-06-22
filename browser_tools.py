"""
browser_tools.py - Herramientas de automatizacion del navegador

Usa Playwright para controlar el navegador y llenar formularios.
Compatible con formularios de Pandape, Computrabajo, LinkedIn y otros.
"""

import asyncio
import json
import base64
from typing import Any
from playwright.async_api import async_playwright, Browser, BrowserContext, Page


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
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        self.page = await self.context.new_page()
        return self
    
    async def __aexit__(self, *args):
        if self.browser:
            await self.browser.close()
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
        return {"success": True, "text": text[:5000]}
    
    async def fill_date_field(self, selector: str, date: str) -> dict:
        try:
            element = await self.page.wait_for_selector(selector, timeout=5000)
            await element.triple_click()
            await element.type(date, delay=100)
            return {"success": True}
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
            "fill_input": self.fill_input,
            "select_option": self.select_option,
            "click_element": self.click_element,
            "get_form_structure": self.get_form_structure,
            "get_screenshot": self.get_screenshot,
            "get_page_text": self.get_page_text,
            "fill_date_field": self.fill_date_field,
            "execute_js": self.execute_js,
        }
        if tool_name not in tool_map:
            return {"success": False, "error": f"Herramienta desconocida: {tool_name}"}
        return await tool_map[tool_name](**tool_input)
