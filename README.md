# job-form-agent

Agente automatizado para diligenciar formularios de empleo usando **Claude AI + Playwright**.

Creado para Maria Fernanda Blanco Pinto | Directora Comercial Tech-Forward

---

## Que hace este agente?

1. Recibe la URL de un formulario de empleo
2. Detecta automaticamente la plataforma (Pandape, Computrabajo, LinkedIn, etc.)
3. Carga tu perfil desde `profile.json`
4. Claude AI analiza el formulario y mapea los campos con tu informacion
5. Llena todos los campos automaticamente con Playwright
6. **NUNCA envia el formulario** - siempre requiere tu revision y aprobacion

---

## Instalacion

### Requisitos
- Python 3.10+
- API Key de Anthropic
- Node.js (para Playwright)

### Pasos

```bash
# 1. Clonar el repositorio
git clone https://github.com/mafeblanco565/job-form-agent.git
cd job-form-agent

# 2. Instalar dependencias de Python
pip install anthropic playwright

# 3. Instalar navegadores de Playwright
playwright install chromium

# 4. Configurar tu API key de Anthropic
# En Windows:
set ANTHROPIC_API_KEY=tu-api-key-aqui

# En Mac/Linux:
export ANTHROPIC_API_KEY=tu-api-key-aqui
```

---

## Uso

### Uso basico

```bash
python agent.py --url "https://empresa.pandape.computrabajo.com/Apply?..."
```

### Con perfil personalizado

```bash
python agent.py --url "https://..." --profile mi_perfil.json
```

### Ejemplo real (Pandape/Computrabajo)

```bash
python agent.py --url "https://transportespiedecuesta.pandape.computrabajo.com/Apply?email=...&idVacancy=..."
```

---

## Estructura del proyecto

```
job-form-agent/
|-- agent.py              # Agente principal (Claude AI + loop de herramientas)
|-- browser_tools.py      # Automatizacion del navegador con Playwright
|-- form_detector.py      # Deteccion de plataformas de empleo
|-- profile.json          # Tu perfil profesional completo
|-- README.md             # Esta documentacion
```

---

## Configurar tu perfil (profile.json)

El archivo `profile.json` contiene toda tu informacion profesional. Estructura principal:

```json
{
  "personal": {
    "first_name": "Tu Nombre",
    "last_name": "Tu Apellido",
    "email": "tu@email.com",
    "phone": "+57 300 000 0000",
    "birth_date": "DD/MM/YYYY",
    "address": {
      "street": "Cra X",
      "number": "XX-XX",
      "city": "Tu Ciudad",
      "country": "Colombia"
    }
  },
  "professional_profile": {
    "title": "Tu Titulo Profesional",
    "summary": "Tu perfil profesional...",
    "salary_min": 4000000,
    "salary_max": 6000000
  },
  "experience": [...],
  "education": [...],
  "skills": [...]
}
```

---

## Plataformas soportadas

| Plataforma | Estado | Notas |
|------------|--------|-------|
| Pandape / Computrabajo | Optima | Soporte completo con Select2 y calendarios |
| LinkedIn Easy Apply | Buena | Formularios multi-paso |
| Indeed | Buena | Formulario simple |
| El Empleo (Colombia) | Buena | Similar a Computrabajo |
| Workday | Basica | ATS complejo, puede requerir ajustes |
| Greenhouse | Basica | Soporta campos estandar |

---

## Como funciona internamente

```
Tu (URL) --> agent.py --> FormDetector --> identifica plataforma
                     --> BrowserAgent (Playwright) --> navega al formulario
                     --> Claude API --> analiza campos + mapea perfil
                     --> BrowserAgent --> llena campos automaticamente
                     --> Tu --> revisas y envias manualmente
```

---

## Notas de seguridad

- El agente NUNCA envia el formulario automaticamente
- El agente NUNCA comparte tu informacion con terceros
- Tu API Key de Anthropic se usa solo para el analisis del formulario
- Los datos de `profile.json` son locales en tu computadora

---

## Proximas mejoras planeadas

- [ ] Soporte para formularios con CAPTCHA (modo semi-automatico)
- [ ] Interfaz web simple para ejecutar sin terminal
- [ ] Integracion con n8n para flujos automatizados
- [ ] Soporte para carga automatica de CV en PDF
- [ ] Historial de aplicaciones enviadas

---

## Creado con

- [Anthropic Claude API](https://anthropic.com) - IA para analisis de formularios
- [Playwright](https://playwright.dev) - Automatizacion del navegador
- [Claude Code](https://docs.anthropic.com/claude-code) - Desarrollo asistido

---

*Desarrollado por Maria Fernanda Blanco Pinto - Directora Comercial | Tech-Forward*
