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

    async def _fill_codigo_postal(self, query: str, log) -> bool:
        """
        Llena el campo Código postal sin asumir framework (Vuetify/Bootstrap/select2).
        1) Vuelca la estructura real del campo
        2) Prueba: native <select>, select2/Chosen, autocomplete genérico
        """
        # 1) Diagnóstico de estructura
        info = await self.page.evaluate("""
            () => {
                let target = null;
                for (const lbl of document.querySelectorAll('label')) {
                    const t = lbl.innerText.toLowerCase();
                    if (t.includes('código postal') || t.includes('codigo postal')) {
                        // elemento de control asociado
                        let ctrl = null;
                        if (lbl.htmlFor) ctrl = document.getElementById(lbl.htmlFor);
                        const cont = lbl.closest('div');
                        target = {
                            labelText: lbl.innerText.trim(),
                            ctrlTag: ctrl ? ctrl.tagName : null,
                            ctrlType: ctrl ? ctrl.type : null,
                            contHTML: cont ? cont.outerHTML.substring(0, 400) : null
                        };
                        break;
                    }
                }
                return target;
            }
        """)
        if not info:
            await log("  ⚠ Código postal: no existe en este formulario (omitido)")
            return False
        await log(f"  🔬 Código postal estructura: ctrl={info.get('ctrlTag')}/{info.get('ctrlType')}")

        # 2a) ¿Es un <select> nativo? Intentar seleccionar opción que contenga la query
        try:
            done = await self.page.evaluate("""
                (q) => {
                    for (const lbl of document.querySelectorAll('label')) {
                        const t = lbl.innerText.toLowerCase();
                        if (t.includes('código postal') || t.includes('codigo postal')) {
                            const cont = lbl.closest('div');
                            const sel = cont && cont.querySelector('select');
                            if (sel) {
                                for (const o of sel.options) {
                                    if ((o.text||'').toLowerCase().includes(q.toLowerCase())) {
                                        sel.value = o.value;
                                        sel.dispatchEvent(new Event('change', {bubbles:true}));
                                        return o.text;
                                    }
                                }
                                return '__SELECT_SIN_OPCION__';
                            }
                        }
                    }
                    return null;
                }
            """, query)
            if done and done != "__SELECT_SIN_OPCION__":
                await log(f"  ✓ Código postal (select nativo): {done}")
                return True
        except Exception:
            pass

        # 2b) select2 / Chosen / custom: clic en el contenedor visible, escribir, elegir
        try:
            # Clic en el control: el <input> asociado o el contenedor select2
            opened = await self.page.evaluate("""
                () => {
                    for (const lbl of document.querySelectorAll('label')) {
                        const t = lbl.innerText.toLowerCase();
                        if (t.includes('código postal') || t.includes('codigo postal')) {
                            const cont = lbl.closest('div');
                            if (!cont) return false;
                            // select2 container
                            const s2 = cont.querySelector('.select2-selection, .select2-container, .chosen-container');
                            if (s2) { s2.click(); return 'select2'; }
                            // input de texto
                            const inp = cont.querySelector('input:not([type=hidden])');
                            if (inp) { inp.focus(); inp.click(); return 'input'; }
                            // cualquier elemento clicable
                            cont.click(); return 'div';
                        }
                    }
                    return false;
                }
            """)
            if not opened:
                await log("  ✗ Código postal: no se pudo enfocar el control")
                return False
            await log(f"  Código postal: control abierto ({opened}), escribiendo '{query}'...")
            await self.page.wait_for_timeout(500)

            # Escribir en el campo de búsqueda activo (select2 crea un input de búsqueda)
            search = self.page.locator(
                "input.select2-search__field, .select2-search__field, "
                ".chosen-search input, input[type='search']:visible"
            ).last
            typed = False
            try:
                if await search.is_visible(timeout=1500):
                    await search.fill(query)
                    typed = True
            except Exception:
                pass
            if not typed:
                # escribir directo con el teclado en el elemento enfocado
                await self.page.keyboard.type(query, delay=80)
            await log("  Código postal: esperando resultados del filtro...")
            await self.page.wait_for_timeout(2500)   # carga asíncrona del servidor

            # Elegir la primera opción del dropdown abierto
            for opt_sel in [
                "li.select2-results__option:not(.select2-results__message)",
                ".select2-results__option",
                ".chosen-results li.active-result",
                "ul[role='listbox'] li", "li[role='option']", "div[role='option']",
            ]:
                try:
                    opt = self.page.locator(opt_sel).first
                    if await opt.is_visible(timeout=1500):
                        txt = (await opt.inner_text())[:40]
                        await opt.click()
                        await self.page.wait_for_timeout(500)
                        await log(f"  ✓ Código postal: {txt}")
                        return True
                except Exception:
                    pass

            # último recurso: teclado
            await self.page.keyboard.press("ArrowDown")
            await self.page.wait_for_timeout(300)
            await self.page.keyboard.press("Enter")
            await self.page.wait_for_timeout(500)
            # verificar si quedó con valor (ya no muestra "Seleccione" ni está vacío)
            has_val = await self.page.evaluate("""
                () => {
                    for (const lbl of document.querySelectorAll('label')) {
                        const t = lbl.innerText.toLowerCase();
                        if (t.includes('código postal') || t.includes('codigo postal')) {
                            const cont = lbl.closest('div');
                            const txt = (cont && cont.innerText || '').toLowerCase();
                            // tiene valor si NO dice 'seleccione' y hay texto/número
                            return !txt.includes('seleccione') && /\\d|bucar|santand/.test(txt);
                        }
                    }
                    return false;
                }
            """)
            if has_val:
                await log("  ✓ Código postal: seleccionado (teclado)")
                return True
            await log("  ✗ Código postal: no apareció ninguna opción para elegir")
            return False
        except Exception as e:
            await log(f"  ✗ Código postal: {e}")
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
        sal_min    = str(int(pp.get("salary_min") or 5000000))
        sal_max    = str(int(pp.get("salary_max") or 8000000))

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

        # ── PASO 6: Llenar formulario completo ──────────────────────────────
        # Pandape usa Vuetify: las etiquetas son <label for="id">Nombre</label>+<input id="id">
        # no usa placeholder= en los inputs. Esperar a que cargue el select de Nacionalidad.
        await log("Paso 6: Esperando que el formulario cargue...")
        try:
            await self.page.wait_for_selector(
                "select[id*='nationality' i], select[id*='naciona' i]",
                state="visible", timeout=12000
            )
            await log("✓ Formulario listo (select Nacionalidad visible)")
        except Exception:
            await log("⚠ Formulario puede estar en otro estado")

        await self.page.wait_for_timeout(800)
        await log("Paso 6: Llenando campos...")

        # Debug: dump de todos los inputs visibles para ver qué hay en el DOM
        dom_inputs = await self.page.evaluate("""
            () => [...document.querySelectorAll('input,textarea')].filter(
                el => el.offsetParent !== null
            ).map(el => {
                let lbl = '';
                if (el.id) { const l = document.querySelector('label[for="'+el.id+'"]'); if(l) lbl = l.innerText.trim(); }
                if (!lbl) { const p = el.closest('.v-text-field__slot,.v-input__slot,div'); if(p){const l=p.querySelector('label');if(l)lbl=l.innerText.trim();}}
                return {type:el.type,ph:el.placeholder,label:lbl,id:el.id};
            })
        """)
        await log(f"DOM inputs ({len(dom_inputs)}): " + str([f"{x['label'] or x['ph'] or x['type']}" for x in dom_inputs[:20]]))

        async def fill_field(label_text, value):
            """Intenta llenar por label (Vuetify), luego por placeholder, luego por JS label."""
            if not value:
                return False
            val = str(value)
            # 1. Playwright get_by_label (Vuetify: <label for=id> + <input id=id>)
            try:
                el = self.page.get_by_label(label_text, exact=False).first
                if await el.is_visible(timeout=2000):
                    await el.click()
                    await el.fill(val)
                    await self.page.wait_for_timeout(120)
                    await log(f"  ✓ [label] {label_text}: {val[:30]}")
                    return True
            except Exception:
                pass
            # 2. Playwright get_by_placeholder
            try:
                el = self.page.get_by_placeholder(label_text, exact=False).first
                if await el.is_visible(timeout=1500):
                    await el.click()
                    await el.fill(val)
                    await self.page.wait_for_timeout(120)
                    await log(f"  ✓ [ph] {label_text}: {val[:30]}")
                    return True
            except Exception:
                pass
            # 3. JS: buscar input cuyo label asociado contiene el texto
            res = await self.page.evaluate(f"""
                (() => {{
                    const kw = {repr(label_text.lower())};
                    for (const inp of document.querySelectorAll('input,textarea')) {{
                        let lbl = '';
                        if (inp.id) {{
                            const l = document.querySelector('label[for="' + inp.id + '"]');
                            if (l) lbl = l.innerText.toLowerCase();
                        }}
                        if (!lbl) {{
                            const p = inp.closest('.v-text-field__slot,.v-input__slot,div');
                            if (p) {{ const l = p.querySelector('label'); if (l) lbl = l.innerText.toLowerCase(); }}
                        }}
                        if (!lbl) lbl = (inp.placeholder || '').toLowerCase();
                        if (lbl.includes(kw) && inp.offsetParent !== null) {{
                            inp.focus();
                            inp.value = {repr(val)};
                            ['input','change','blur'].forEach(ev =>
                                inp.dispatchEvent(new Event(ev, {{bubbles:true}})));
                            return lbl || inp.placeholder;
                        }}
                    }}
                    return null;
                }})()
            """)
            if res:
                await log(f"  ✓ [js] {label_text}: {val[:30]}")
                return True
            await log(f"  ✗ {label_text}: no encontrado por label/placeholder/js")
            return False

        # Alias para retrocompatibilidad con el resto del código
        fill_input = fill_field

        async def select_value(selector, value, label=""):
            if not value:
                return
            try:
                el = self.page.locator(selector).first
                await el.wait_for(state="visible", timeout=3000)
                await el.select_option(value=str(value))
                await self.page.wait_for_timeout(150)
                await log(f"  ✓ {label or selector}: {value}")
            except Exception as e:
                await log(f"  ✗ {label or selector}: {e}")

        async def fill_vuetify_select(label_text, option_text):
            """Abre un Vuetify v-select buscando el label por JS y cliqueando su contenedor."""
            try:
                # JS: busca el label, sube hasta encontrar un div Vuetify y hace click
                clicked = await self.page.evaluate(f"""
                    (() => {{
                        const kw = {repr(label_text.lower())};
                        for (const lbl of document.querySelectorAll('label')) {{
                            if (lbl.innerText.trim().toLowerCase().includes(kw)) {{
                                let el = lbl.parentElement;
                                for (let i = 0; i < 6; i++) {{
                                    if (!el) break;
                                    const cls = (el.className || '').toString();
                                    if (cls.includes('v-select') || cls.includes('v-input') || cls.includes('v-autocomplete')) {{
                                        el.click();
                                        return lbl.innerText.trim();
                                    }}
                                    el = el.parentElement;
                                }}
                                // fallback: click el parentElement del label
                                lbl.closest('div') && lbl.closest('div').click();
                                return lbl.innerText.trim() + ' (fallback)';
                            }}
                        }}
                        return null;
                    }})()
                """)
                if not clicked:
                    await log(f"  ✗ [v-select] {label_text}: label no encontrado en DOM")
                    return False
                await log(f"  [v-select] {label_text}: click → buscando '{option_text}'...")
                await self.page.wait_for_timeout(800)
                # Busca la opción en el dropdown abierto
                opt = self.page.get_by_role("option", name=option_text, exact=False).first
                if not await opt.is_visible(timeout=2500):
                    opt = self.page.get_by_text(option_text, exact=True).first
                if await opt.is_visible(timeout=2000):
                    await opt.click()
                    await self.page.wait_for_timeout(300)
                    await log(f"  ✓ [v-select] {label_text}: {option_text}")
                    return True
                await log(f"  ✗ [v-select] {label_text}: opción '{option_text}' no apareció en dropdown")
                await self.page.keyboard.press("Escape")
            except Exception as e:
                await log(f"  ✗ [v-select] {label_text}: {e}")
            return False

        # Datos personales — campos de texto (Vuetify labels)
        await fill_input("Nombre",              first_name)
        await fill_input("Apellido",            last_name)
        await fill_input("Fecha de nacimiento", birth_date or "26/11/1990")
        await fill_input("Dirección",           "Bucaramanga, Santander")

        # Prefijo de teléfono (x2: fijo y móvil) → código de Colombia "57"
        try:
            n_prefijos = await self.page.evaluate("""
                () => {
                    let n = 0;
                    for (const inp of document.querySelectorAll('input')) {
                        let lbl = '';
                        if (inp.id) { const l = document.querySelector('label[for="'+inp.id+'"]'); if(l) lbl=l.innerText.toLowerCase(); }
                        if (!lbl) { const p=inp.closest('.v-text-field__slot,.v-input__slot,div'); if(p){const l=p.querySelector('label');if(l)lbl=l.innerText.toLowerCase();}}
                        if (lbl.includes('prefijo') && inp.offsetParent !== null) {
                            inp.value = '57';
                            ['input','change','blur'].forEach(ev => inp.dispatchEvent(new Event(ev,{bubbles:true})));
                            n++;
                        }
                    }
                    return n;
                }
            """)
            await log(f"  ✓ Prefijo(s) → 57 ({n_prefijos} campos)")
        except Exception as e:
            await log(f"  ✗ Prefijo: {e}")

        await fill_input("Teléfono móvil", phone)
        await fill_input("Teléfono",       phone)   # fijo — label exacto sin "fijo"

        # Checkbox s/n (Número de dirección)
        try:
            sn = await self.page.evaluate("""
                () => {
                    for (const cb of document.querySelectorAll('input[type="checkbox"]')) {
                        const lbl = (cb.labels && cb.labels[0] && cb.labels[0].innerText) || '';
                        const par = (cb.parentElement && cb.parentElement.innerText) || '';
                        if (lbl.trim()==='s/n' || par.trim()==='s/n') { if(!cb.checked) cb.click(); return true; }
                    }
                    return false;
                }
            """)
            await log(f"  {'✓' if sn else '✗'} Checkbox s/n")
        except Exception as e:
            await log(f"  ✗ Checkbox s/n: {e}")

        # Selects nativos (Nacionalidad y Tipo ID usan <select> nativo)
        await select_value("select[id*='nationality' i], select[id*='naciona' i]", "48", "Nacionalidad")
        await select_value("select[id*='identification' i], select[id*='identifi' i]", "1", "Tipo ID")

        # Vuetify v-select para Género y País
        await fill_vuetify_select("Género", "Mujer")
        await fill_vuetify_select("País",   "Colombia")

        # ── Código postal (OBLIGATORIO) — buscar por número 680002 y elegir cualquiera ──
        await self._fill_codigo_postal("680002", log)

        # Perfil profesional (accordion)
        pp_title = profile_data.get("professional_profile", {}).get("title", "")
        pp_summary = profile_data.get("professional_profile", {}).get("summary", "")
        pp_desired = profile_data.get("professional_profile", {}).get("desired_position", "")
        if pp_title or pp_summary:
            try:
                header = self.page.get_by_text("Perfil profesional", exact=False).first
                if await header.is_visible(timeout=2000):
                    await header.click()
                    await self.page.wait_for_timeout(800)
                await fill_input("Título", pp_title)
                await fill_input("Resumen", pp_summary)
                await fill_input("Puesto deseado", pp_desired)
            except Exception as e:
                await log(f"  ✗ Perfil profesional: {e}")

        await log("✓ Información personal y perfil llenados")

        async def expand_section(header_text):
            """Expande una sección de acordeón colapsada haciendo clic en su encabezado."""
            try:
                header = self.page.get_by_text(header_text, exact=False).first
                if await header.is_visible(timeout=2000):
                    await header.scroll_into_view_if_needed()
                    await header.click()
                    await self.page.wait_for_timeout(1000)
                    return True
            except Exception:
                pass
            return False

        async def find_incluir_button(add_button_texts):
            """Busca el botón '+ Incluir X' (visible) entre varios textos posibles."""
            for t in add_button_texts:
                for getter in [
                    lambda t=t: self.page.get_by_role("button", name=t, exact=False).first,
                    lambda t=t: self.page.get_by_text(t, exact=False).first,
                ]:
                    try:
                        b = getter()
                        if await b.is_visible(timeout=1000):
                            return b
                    except Exception:
                        pass
            return None

        async def open_accordion_form(header_text, add_button_texts):
            """
            Abre el sub-formulario de una sección de acordeón:
            1) si el botón '+ Incluir' ya es visible → la sección está expandida
            2) si no → clic en el encabezado para expandir, y reintenta
            3) clic en '+ Incluir X'
            """
            btn = await find_incluir_button(add_button_texts)
            if btn is None:
                # sección colapsada → expandir por el encabezado
                await expand_section(header_text)
                btn = await find_incluir_button(add_button_texts)
            if btn is None:
                return False
            try:
                await btn.scroll_into_view_if_needed()
                await btn.click()
                await self.page.wait_for_timeout(1000)
                return True
            except Exception:
                return False

        async def click_save_incluir():
            """
            Hace clic en el botón 'Incluir' (guardar, exacto) del sub-formulario abierto
            y verifica que el sub-formulario se cerró (el botón 'Cancelar' desaparece).
            """
            # El botón de guardar es exactamente 'Incluir' (los abridores son '+ Incluir X')
            b = self.page.get_by_role("button", name="Incluir", exact=True).last
            try:
                if not (await b.is_visible(timeout=1500)):
                    return False
                if not (await b.is_enabled(timeout=1000)):
                    await log("    ⚠ Botón 'Incluir' deshabilitado (falta algún campo)")
                    return False
                await b.scroll_into_view_if_needed()
                await b.click()
                await self.page.wait_for_timeout(1000)
                # ¿se cerró el sub-form? el 'Cancelar' ya no debería estar visible
                try:
                    cancelar = self.page.get_by_role("button", name="Cancelar", exact=True).last
                    if await cancelar.is_visible(timeout=1000):
                        # sigue abierto → no se guardó (validación interna)
                        await log("    ⚠ Sub-formulario sigue abierto tras 'Incluir'")
                        return False
                except Exception:
                    pass
                return True
            except Exception:
                return False

        async def cancel_subform():
            """Cierra un sub-formulario abierto vía 'Cancelar' para no bloquear el envío."""
            try:
                b = self.page.get_by_role("button", name="Cancelar", exact=True).last
                if await b.is_visible(timeout=1500):
                    await b.click()
                    await self.page.wait_for_timeout(600)
                    return True
            except Exception:
                pass
            return False

        async def select_in_subform(label_text, option_text):
            """Selecciona una opción en un <select> nativo o v-select dentro del sub-form."""
            # 1. intentar <select> nativo cuyas opciones contengan el texto buscado
            try:
                native = self.page.locator("select")
                count = await native.count()
                for i in range(count):
                    s = native.nth(i)
                    if not await s.is_visible():
                        continue
                    opts = await s.evaluate("el => [...el.options].map(o => o.text)")
                    if any(option_text.lower() in (o or '').lower() for o in opts):
                        await s.select_option(label=[o for o in opts if option_text.lower() in o.lower()][0])
                        await log(f"    ✓ {label_text}: {option_text}")
                        return True
            except Exception:
                pass
            # 2. v-select Vuetify
            return await fill_vuetify_select(label_text, option_text)

        # DIAGNÓSTICO: volcar todos los botones visibles antes de las secciones
        botones = await self.page.evaluate("""
            () => [...document.querySelectorAll('button')]
                .filter(b => b.offsetParent !== null)
                .map(b => (b.innerText || '').trim())
                .filter(t => t.length > 0 && t.length < 50)
        """)
        await log(f"🔘 Botones visibles en la página: {botones}")

        # ── PASO 6b: Experiencia profesional ────────────────────────────────
        experiences = profile_data.get("experience", [])
        await log(f"Paso 6b: experiencias en perfil = {len(experiences)}")
        if experiences:
            exp = experiences[0]
            await log("Paso 6b: Agregando experiencia profesional...")
            try:
                if await open_accordion_form("Experiencia profesional", ["+ Incluir experiencia", "Incluir experiencia"]):
                    await fill_input("Posición", exp.get("position", ""))
                    await fill_input("Empresa", exp.get("company", ""))
                    await select_in_subform("Área", exp.get("area", "Ventas"))
                    await fill_input("Fecha de inicio", exp.get("start_date_input", "01/03/2026"))
                    if exp.get("current"):
                        try:
                            await self.page.get_by_text("Actualmente trabajo aquí", exact=False).first.click()
                            await log("    ✓ Actualmente trabajo aquí")
                        except Exception:
                            pass
                    else:
                        await fill_input("Fecha de finalización", exp.get("end_date_input", ""))
                    await fill_input("Descripción", exp.get("description", ""))
                    if await click_save_incluir():
                        await log("  ✓ Experiencia incluida")
                    else:
                        await cancel_subform()
                        await log("  ✗ Experiencia: no se pudo guardar → cancelada")
                else:
                    await log("  ✗ No se encontró '+ Incluir experiencia'")
            except Exception as e:
                await log(f"  ✗ Experiencia: {e}")

        # ── PASO 6c: Educación ──────────────────────────────────────────────
        educations = profile_data.get("education", [])
        if educations:
            edu = educations[0]
            await log("Paso 6c: Agregando educación...")
            try:
                if await open_accordion_form("Educación", ["+ Incluir formación académica", "Incluir formación académica"]):
                    await fill_input("Curso", edu.get("degree", ""))
                    await fill_input("Institución", edu.get("institution", ""))
                    await select_in_subform("Nivel", edu.get("level", "Universidad"))
                    await fill_input("Fecha de inicio", edu.get("start_date", ""))
                    await fill_input("Fecha de finalización", edu.get("end_date", ""))
                    # Estado "Concluido" ya viene seleccionado por defecto (radio)
                    if await click_save_incluir():
                        await log("  ✓ Educación incluida")
                    else:
                        await cancel_subform()
                        await log("  ✗ Educación: no se pudo guardar → cancelada")
                else:
                    await log("  ✗ No se encontró '+ Incluir formación académica'")
            except Exception as e:
                await log(f"  ✗ Educación: {e}")

        # ── PASO 6d: Cursos y Certificaciones ───────────────────────────────
        courses = profile_data.get("courses", [])
        if courses:
            course = courses[0]
            await log("Paso 6d: Agregando curso/certificación...")
            try:
                if await open_accordion_form("Cursos y Certificaciones", ["+ Incluir curso o certificación", "Incluir curso o certificación"]):
                    await fill_input("Nombre o título", course.get("name", ""))
                    await fill_input("Centro", course.get("institution", ""))
                    if await click_save_incluir():
                        await log("  ✓ Curso incluido")
                    else:
                        await cancel_subform()
                        await log("  ✗ Curso: no se pudo guardar → cancelado")
            except Exception as e:
                await log(f"  ✗ Curso: {e}")

        # ── PASO 6e: Idiomas ────────────────────────────────────────────────
        languages = profile_data.get("languages", [])
        if languages:
            lang = languages[0]
            await log("Paso 6e: Agregando idioma...")
            try:
                if await open_accordion_form("Idiomas", ["+ Incluir idioma", "Incluir idioma"]):
                    await select_in_subform("Idioma", lang.get("language", "Inglés"))
                    await select_in_subform("Nivel", lang.get("level", "Intermedio"))
                    if await click_save_incluir():
                        await log("  ✓ Idioma incluido")
                    else:
                        await cancel_subform()
                        await log("  ✗ Idioma: no se pudo guardar → cancelado")
                else:
                    await log("  ✗ No se encontró '+ Incluir idioma'")
            except Exception as e:
                await log(f"  ✗ Idioma: {e}")

        # ── PASO 6f: Habilidades (input con búsqueda + botón Incluir inline) ──
        skills = profile_data.get("skills", [])
        if skills:
            await log("Paso 6f: Agregando habilidades...")
            # Expandir la sección si el input no está visible
            try:
                inp_check = self.page.get_by_placeholder("Habilidad de búsqueda", exact=False).first
                if not await inp_check.is_visible(timeout=1500):
                    await expand_section("Habilidades")
            except Exception:
                await expand_section("Habilidades")
            added = 0
            for skill in skills[:5]:   # primeras 5 habilidades
                try:
                    inp = self.page.get_by_placeholder("Habilidad de búsqueda", exact=False).first
                    if await inp.is_visible(timeout=1500):
                        await inp.click()
                        await inp.fill(skill)
                        await self.page.wait_for_timeout(1500)   # esperar sugerencias
                        # elegir sugerencia del dropdown si aparece, si no, click Incluir
                        opt = self.page.locator(".v-list-item, div[role='option']").filter(has_text=skill).first
                        if await opt.is_visible(timeout=1500):
                            await opt.click()
                        else:
                            btn = self.page.get_by_role("button", name="Incluir", exact=True).last
                            if await btn.is_visible(timeout=1000):
                                await btn.click()
                        await self.page.wait_for_timeout(500)
                        added += 1
                except Exception:
                    pass
            await log(f"  ✓ Habilidades agregadas: {added}")

        # ── PASO 7a: Salario deseado (REQUERIDO) ────────────────────────────
        await log("Paso 7: Llenando Salario deseado...")

        # Expandir sección si está colapsada
        sal_section_visible = await self.page.evaluate("""
            () => {
                for (const inp of document.querySelectorAll('input')) {
                    if (inp.placeholder && inp.placeholder.includes('Bruto')) return true;
                }
                return false;
            }
        """)
        if not sal_section_visible:
            try:
                sal_header = self.page.get_by_text("Salario deseado", exact=False).first
                if await sal_header.is_visible(timeout=2000):
                    await sal_header.click()
                    await self.page.wait_for_timeout(1500)
                    await log("  ✓ Sección Salario expandida")
            except Exception:
                pass

        # Llenar salario buscando por label Vuetify (no placeholder)
        sal_result = await self.page.evaluate(f"""
            () => {{
                const filled = [];
                const inputs = [...document.querySelectorAll('input')].filter(i => i.offsetParent !== null);
                for (const inp of inputs) {{
                    let lbl = '';
                    if (inp.id) {{
                        const l = document.querySelector('label[for="' + inp.id + '"]');
                        if (l) lbl = l.innerText.toLowerCase();
                    }}
                    if (!lbl) {{
                        const p = inp.closest('.v-text-field__slot,.v-input__slot,div');
                        if (p) {{ const l = p.querySelector('label'); if(l) lbl = l.innerText.toLowerCase(); }}
                    }}
                    if (!lbl) lbl = (inp.placeholder || '').toLowerCase();
                    // mínimo: "entre", "desde", "mínimo", "min"
                    if (lbl && (lbl.includes('entre') || lbl.includes('desde') || lbl.includes('mínimo') || lbl.includes('minimo'))) {{
                        inp.focus(); inp.value = '{sal_min}';
                        ['input','change','blur'].forEach(ev => inp.dispatchEvent(new Event(ev,{{bubbles:true}})));
                        filled.push('min:' + lbl.substring(0,30));
                    }}
                    // máximo: "hasta", "y $", "máximo", "max"
                    if (lbl && (lbl.includes('hasta') || lbl.includes('y $') || lbl.includes('máximo') || lbl.includes('maximo'))) {{
                        inp.focus(); inp.value = '{sal_max}';
                        ['input','change','blur'].forEach(ev => inp.dispatchEvent(new Event(ev,{{bubbles:true}})));
                        filled.push('max:' + lbl.substring(0,30));
                    }}
                }}
                return filled;
            }}
        """)
        if sal_result:
            await log(f"  ✓ Salario llenado: {sal_result}")
        else:
            # fallback: llenar los primeros 2 inputs numéricos visibles de la sección
            await fill_field("Entre", sal_min)
            await fill_field("Bruto", sal_max)

        # Jornada y Tipo de contrato (selects dentro de la sección Salario)
        work_type = pp.get("work_type", "Tiempo Completo") or "Tiempo Completo"
        contract  = pp.get("contract_type", "Contrato a término indefinido") or "Contrato a término indefinido"
        try:
            sels = self.page.locator("select")
            count = await sels.count()
            for i in range(count):
                sel = sels.nth(i)
                try:
                    options = await sel.evaluate("el => [...el.options].map(o => o.text)")
                    if any("Completo" in o or "Parcial" in o for o in options):
                        await sel.select_option(label=work_type)
                        await log(f"  ✓ Jornada: {work_type}")
                    if any("indefinido" in o.lower() for o in options):
                        await sel.select_option(label=contract)
                        await log(f"  ✓ Contrato: {contract}")
                except Exception:
                    pass
        except Exception as e:
            await log(f"  ✗ Selects Jornada/Contrato: {e}")

        await self.page.wait_for_timeout(500)

        # ── PASO 7b: Marcar SOLO checkboxes "Acepto" de privacidad/términos ──
        # Usar JavaScript para encontrar SOLO checkboxes cuyo label directo dice "Acepto"
        try:
            checked_count = await self.page.evaluate("""
                () => {
                    let count = 0;
                    document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                        // Solo checkboxes que son hermanos directos de texto "Acepto..."
                        const parent = cb.parentElement;
                        if (!parent) return;
                        const text = parent.innerText || '';
                        // El texto del contenedor INMEDIATO debe empezar con "Acepto"
                        if (text.trim().startsWith('Acepto') && !cb.checked) {
                            cb.click();
                            count++;
                        }
                    });
                    return count;
                }
            """)
            if checked_count:
                await log(f"✓ {checked_count} checkbox(es) 'Acepto' marcados")
                await self.page.wait_for_timeout(400)
        except Exception:
            pass

        # ── PASO 7c: DIAGNÓSTICO de validación + clic en ENVIAR APLICACIÓN ──
        await self.page.wait_for_timeout(1000)

        async def diagnose_validation():
            """Lee el estado real de validación de Vuetify: campos en error y mensajes."""
            return await self.page.evaluate("""
                () => {
                    const result = {invalid_fields: [], messages: [], submit_disabled: null};
                    // 1. Campos Vuetify en estado de error (clase error--text en .v-input)
                    document.querySelectorAll('.v-input.error--text, .v-input--has-state.error--text').forEach(el => {
                        const lbl = el.querySelector('label');
                        result.invalid_fields.push(lbl ? lbl.innerText.trim() : el.className.substring(0,40));
                    });
                    // 2. Mensajes de validación visibles
                    document.querySelectorAll('.v-messages__message, .error--text .v-messages__message').forEach(m => {
                        const t = (m.innerText || '').trim();
                        if (t) result.messages.push(t);
                    });
                    // 3. Estado del botón submit real (<button> que contiene ENVIAR)
                    for (const b of document.querySelectorAll('button')) {
                        if ((b.innerText || '').toUpperCase().includes('ENVIAR')) {
                            result.submit_disabled = b.disabled || b.classList.contains('v-btn--disabled');
                            break;
                        }
                    }
                    // 4. Campos requeridos vacíos (inputs con * en el label y sin valor)
                    document.querySelectorAll('input,textarea,select').forEach(el => {
                        if (el.offsetParent === null) return;
                        let lbl = '';
                        if (el.id) { const l = document.querySelector('label[for="'+el.id+'"]'); if(l) lbl=l.innerText.trim(); }
                        if (!lbl) { const p=el.closest('.v-input__slot,.v-text-field__slot,div'); if(p){const l=p.querySelector('label');if(l)lbl=l.innerText.trim();}}
                        const isRequired = lbl.includes('*') || (el.required === true);
                        const isEmpty = !el.value || !el.value.trim();
                        if (isRequired && isEmpty) result.invalid_fields.push('VACÍO REQUERIDO: ' + lbl);
                    });
                    return result;
                }
            """)

        diag = await diagnose_validation()
        await log(f"🔍 DIAGNÓSTICO — botón submit deshabilitado: {diag.get('submit_disabled')}")
        if diag.get("invalid_fields"):
            await log(f"🔍 Campos inválidos/vacíos: {diag['invalid_fields']}")
        if diag.get("messages"):
            await log(f"🔍 Mensajes de validación: {diag['messages']}")
        if not diag.get("invalid_fields") and not diag.get("messages"):
            await log("🔍 Vuetify no reporta campos inválidos (validación puede estar en otro nivel)")

        # ── Verificar que los 2 checkboxes "Acepto" estén marcados (habilitan SIGUIENTE) ──
        cbk = await self.page.evaluate("""
            () => {
                let total = 0, checked = 0;
                for (const cb of document.querySelectorAll('input[type="checkbox"]')) {
                    const p = cb.closest('div');
                    const txt = (p && p.innerText || '').trim();
                    if (txt.startsWith('Acepto')) {
                        total++;
                        if (!cb.checked) {
                            // click en el control Vuetify (no solo el input) para registrar en Vue
                            const ripple = cb.closest('.v-input--selection-controls__input, .v-input__slot');
                            (ripple || cb).click();
                        }
                        if (cb.checked) checked++;
                    }
                }
                // re-contar tras los clicks
                checked = 0;
                for (const cb of document.querySelectorAll('input[type="checkbox"]')) {
                    const p = cb.closest('div');
                    const txt = (p && p.innerText || '').trim();
                    if (txt.startsWith('Acepto') && cb.checked) checked++;
                }
                return {total, checked};
            }
        """)
        await log(f"🔍 Checkboxes Acepto: {cbk['checked']}/{cbk['total']} marcados")

        # DIAGNÓSTICO PROFUNDO: estado real del botón SIGUIENTE + campos requeridos vacíos
        deep = await self.page.evaluate("""
            () => {
                const out = {boton: null, requeridos_vacios: [], errores: []};
                // Botón SIGUIENTE (o ENVIAR como fallback)
                for (const b of document.querySelectorAll('button')) {
                    const t = (b.innerText || '').toUpperCase().trim();
                    if (t.includes('SIGUIENTE') || t.includes('ENVIAR') || t.includes('APLICA')) {
                        out.boton = {
                            txt: t.substring(0,25),
                            disabled: b.disabled || b.classList.contains('v-btn--disabled'),
                            cls: (b.className||'').toString().substring(0,50)
                        };
                        break;
                    }
                }
                // Mensajes de error visibles (rojo) tipo "X es obligatorio"
                document.querySelectorAll('.v-messages__message, .error--text').forEach(m => {
                    const t = (m.innerText||'').trim();
                    if (t && (t.toLowerCase().includes('obligat') || t.toLowerCase().includes('requ'))) {
                        if (!out.errores.includes(t)) out.errores.push(t);
                    }
                });
                // Inputs/selects requeridos visibles que siguen vacíos
                document.querySelectorAll('input,select').forEach(el => {
                    if (el.offsetParent === null) return;
                    if (el.type === 'checkbox' || el.type === 'radio') return;
                    let lbl = '';
                    if (el.id) { const l=document.querySelector('label[for="'+el.id+'"]'); if(l) lbl=l.innerText.trim(); }
                    if (!lbl) { const p=el.closest('.v-input__slot,.v-text-field__slot,div'); if(p){const l=p.querySelector('label'); if(l) lbl=l.innerText.trim();}}
                    const empty = !el.value || !el.value.trim() || el.value === 'Seleccione';
                    // marcar como sospechoso si está vacío y NO dice opcional
                    if (empty && lbl && !lbl.toLowerCase().includes('opcional') && !lbl.toLowerCase().includes('skype') && !lbl.toLowerCase().includes('complemento') && !lbl.toLowerCase().includes('número')) {
                        out.requeridos_vacios.push(lbl.substring(0,30) + '=' + (el.value||'<vacío>'));
                    }
                });
                return out;
            }
        """)
        await log(f"🔬 Botón submit: {deep.get('boton')}")
        if deep.get("errores"):
            await log(f"🔬 Errores visibles: {deep['errores']}")
        if deep.get("requeridos_vacios"):
            await log(f"🔬 Campos aún vacíos: {deep['requeridos_vacios']}")

        # ── Clic en SIGUIENTE ───────────────────────────────────────────────
        await log("Paso 7: Buscando botón SIGUIENTE...")
        enviar_clicked = False
        btn = None
        for sel in [
            "button:has-text('SIGUIENTE')",
            "button:has-text('Siguiente')",
            "button:has-text('ENVIAR APLICACIÓN')",
            "button:has-text('ENVIAR')",
        ]:
            try:
                cand = self.page.locator(sel).first
                if await cand.is_visible(timeout=1500):
                    btn = cand
                    await log(f"  Botón encontrado con selector: {sel}")
                    break
            except Exception:
                pass

        if btn is not None:
            try:
                if await btn.is_enabled(timeout=1000):
                    await btn.scroll_into_view_if_needed()
                    await btn.click()
                    enviar_clicked = True
                    await log("✓ Clic en SIGUIENTE")
                else:
                    await log("⚠ SIGUIENTE deshabilitado — esperando 2s y reintentando...")
                    await self.page.wait_for_timeout(2000)
                    if await btn.is_enabled(timeout=1000):
                        await btn.scroll_into_view_if_needed()
                        await btn.click()
                        enviar_clicked = True
                        await log("✓ Clic en SIGUIENTE (2do intento)")
            except Exception as e:
                await log(f"✗ Error al clicar SIGUIENTE: {e}")
        else:
            await log("✗ No se encontró ningún botón SIGUIENTE/ENVIAR")

        if not enviar_clicked:
            boton = deep.get("boton") or {}
            vacios = deep.get("requeridos_vacios") or []
            errores = deep.get("errores") or []
            detail = ""
            if boton.get("disabled"):
                detail = " El botón está deshabilitado (gris)."
            if errores:
                detail += f" Errores: {errores}"
            if vacios:
                detail += f" Campos vacíos: {vacios}"
            return {"success": True, "submitted": False,
                    "error": f"SIGUIENTE no se pudo clicar.{detail}"}

        # ── PASO 8: Esperar página de verificación (pantalla blanca transitoria ~8-10s) ──
        await log("Paso 8: Esperando página de verificación...")
        try:
            await self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await self.page.wait_for_timeout(10000)   # pantalla blanca puede tardar hasta 10s

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
