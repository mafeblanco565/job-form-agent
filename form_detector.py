"""
form_detector.py - Detector de tipos de formularios de empleo

Identifica el tipo de plataforma de empleo basado en la URL
para aplicar estrategias especificas de llenado.
"""

import re
from urllib.parse import urlparse


class FormDetector:
    """Detecta el tipo de formulario de empleo basado en la URL."""
    
    # Patrones de plataformas conocidas
    PLATFORMS = {
        "pandape": {
            "patterns": ["pandape.com", "pandape.computrabajo"],
            "description": "Pandape / Computrabajo",
            "notes": "Usa Select2 para dropdowns, calendario para fechas"
        },
        "computrabajo": {
            "patterns": ["computrabajo.com", "computrabajo.co"],
            "description": "Computrabajo",
            "notes": "Formulario estandar HTML"
        },
        "linkedin": {
            "patterns": ["linkedin.com/jobs", "linkedin.com/easy-apply"],
            "description": "LinkedIn Easy Apply",
            "notes": "Formulario multi-paso con validacion en tiempo real"
        },
        "indeed": {
            "patterns": ["indeed.com", "indeed.co"],
            "description": "Indeed",
            "notes": "Formulario simple con carga de CV"
        },
        "elempleo": {
            "patterns": ["elempleo.com"],
            "description": "El Empleo (Colombia)",
            "notes": "Plataforma colombiana, similar estructura a Computrabajo"
        },
        "hirequest": {
            "patterns": ["hirequest.com", "hiringplatform"],
            "description": "HireQuest / ATS Generico",
            "notes": "ATS generico con campos estandar"
        },
        "workday": {
            "patterns": ["myworkdayjobs.com", "workday.com"],
            "description": "Workday ATS",
            "notes": "Formulario complejo multi-seccion, requiere login"
        },
        "greenhouse": {
            "patterns": ["greenhouse.io", "boards.greenhouse.io"],
            "description": "Greenhouse ATS",
            "notes": "Formulario moderno con upload de CV"
        },
        "lever": {
            "patterns": ["lever.co", "jobs.lever.co"],
            "description": "Lever ATS",
            "notes": "Formulario limpio con campos basicos"
        }
    }
    
    # Campos comunes por plataforma
    FIELD_MAPPINGS = {
        "pandape": {
            "first_name": "#Name",
            "last_name": "#Surname",
            "email": "#Email",
            "phone": "#Phone",
            "birth_date": "#BirthDate",
            "summary": "#Summary",
            "desired_position": "#PreferredJob",
            "salary_min": "#SalaryMin",
            "salary_max": "#SalaryMax"
        },
        "generic": {
            "first_name": ["#first_name", "input[name*='first']", "input[name*='nombre']", "#nombre"],
            "last_name": ["#last_name", "input[name*='last']", "input[name*='apellido']", "#apellido"],
            "email": ["#email", "input[type='email']", "input[name*='email']", "input[name*='correo']"],
            "phone": ["#phone", "input[name*='phone']", "input[name*='telefono']", "input[name*='celular']"],
            "summary": ["#summary", "textarea[name*='summary']", "textarea[name*='perfil']", "#perfil"]
        }
    }
    
    def detect(self, url: str) -> str:
        """Detecta el tipo de plataforma basado en la URL."""
        url_lower = url.lower()
        for platform, config in self.PLATFORMS.items():
            for pattern in config["patterns"]:
                if pattern in url_lower:
                    print(f"Plataforma detectada: {config['description']}")
                    if config.get("notes"):
                        print(f"  Nota: {config['notes']}")
                    return platform
        print("Plataforma: Generica (no reconocida)")
        return "generic"
    
    def get_field_selectors(self, platform: str) -> dict:
        """Retorna los selectores CSS para los campos del perfil."""
        if platform in self.FIELD_MAPPINGS:
            return self.FIELD_MAPPINGS[platform]
        return self.FIELD_MAPPINGS["generic"]
    
    def get_platform_info(self, url: str) -> dict:
        """Retorna informacion completa sobre la plataforma detectada."""
        platform = self.detect(url)
        info = self.PLATFORMS.get(platform, {
            "description": "Plataforma generica",
            "notes": "Se usaran selectores genericos"
        })
        return {
            "platform": platform,
            "description": info.get("description", "Desconocida"),
            "notes": info.get("notes", ""),
            "field_selectors": self.get_field_selectors(platform)
        }
    
    @staticmethod
    def is_supported(url: str) -> bool:
        """Verifica si la URL es de una plataforma soportada."""
        detector = FormDetector()
        return detector.detect(url) != "generic"
