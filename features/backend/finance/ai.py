# Sintergica CE extension: finance AI — bank statement parsing and CFO-style
# analysis, using the instance's god-mode LLM configuration (the same key the
# editor assistant uses). Synchronous on purpose; see plane/assistant/llm.py
# for the rationale. (AGPL-3.0-only)

import json
import os
import re

from openai import OpenAI

from plane.license.utils.instance_value import get_configuration_value

# Each provider's OpenAI-compatible endpoint (mirrors the MCP patch mapping).
PROVIDER_BASE_URLS = {
    "openai": None,
    "anthropic": "https://api.anthropic.com/v1/",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openrouter": "https://openrouter.ai/api/v1",
}

MAX_STATEMENT_CHARS = 200_000
VALID_CATEGORIES = ("payroll", "infrastructure", "marketing", "admin", "taxes", "other")


class FinanceAINotConfigured(Exception):
    pass


def get_llm_config():
    api_key, provider, model = get_configuration_value(
        [
            {"key": "LLM_API_KEY", "default": os.environ.get("LLM_API_KEY")},
            {"key": "LLM_PROVIDER", "default": os.environ.get("LLM_PROVIDER", "openai")},
            {"key": "LLM_MODEL", "default": os.environ.get("LLM_MODEL")},
        ]
    )
    provider = (provider or "openai").strip().lower()
    # multi-model selector stores a comma-separated list; each entry is a
    # fallback for the previous one (free-tier models get rate-limited often)
    models = [m.strip() for m in (model or "").split(",") if m.strip()]
    if not api_key or not models:
        raise FinanceAINotConfigured(
            "Falta configurar el proveedor de IA. Ve a /god-mode/ai/ y define la clave y el modelo."
        )
    return {"api_key": api_key, "models": models, "base_url": PROVIDER_BASE_URLS.get(provider)}


def _client(config):
    return OpenAI(api_key=config["api_key"], base_url=config["base_url"])


class FinanceAIUnavailable(Exception):
    """Every configured model failed (rate limits, provider errors)."""


def _chat(config, messages, temperature):
    """Try each configured model in order; free-tier models are often
    rate-limited upstream, so the list doubles as a fallback chain."""
    client = _client(config)
    last_error = None
    for model in config["models"]:
        try:
            response = client.chat.completions.create(
                model=model, messages=messages, temperature=temperature
            )
            return response.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001 — rate limits, provider 5xx, bad model ids
            last_error = e
    raise FinanceAIUnavailable(
        "Los modelos de IA configurados están saturados o no disponibles en este "
        "momento. Intenta de nuevo en unos minutos, o configura un modelo de pago "
        f"en /god-mode/ai/. Detalle: {type(last_error).__name__}"
    )


def _extract_json(text):
    """LLMs love wrapping JSON in fences or prose; dig the object out."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("La respuesta del modelo no contiene JSON.")
    return json.loads(text[start : end + 1])


PARSE_PROMPT = """Eres un analista financiero. Te doy el texto de un estado de cuenta bancario \
mexicano (exportado como CSV o copiado de la banca en línea). Extrae TODOS los movimientos.

Devuelve EXCLUSIVAMENTE un objeto JSON con esta forma, sin explicación ni markdown:
{
  "transactions": [
    {
      "date": "YYYY-MM-DD",
      "concept": "descripción corta y limpia del movimiento",
      "amount": 1234.56,
      "currency": "MXN" | "USD",
      "direction": "in" | "out",
      "suggested_category": "payroll" | "infrastructure" | "marketing" | "admin" | "taxes" | "other"
    }
  ]
}

Reglas:
- "amount" siempre positivo; el signo va en "direction" (out = cargo/egreso, in = abono/ingreso).
- Si la moneda no es evidente, usa "MXN".
- "suggested_category" solo aplica a egresos; para ingresos usa "other".
- Categoriza con criterio: nómina/sueldos → payroll; servidores, dominios, software, telecom → infrastructure; \
publicidad, Meta/Google Ads → marketing; renta, contabilidad, papelería, comisiones bancarias → admin; \
SAT, IMSS, impuestos → taxes; lo demás → other.
- Ignora líneas de saldo, encabezados y totales: solo movimientos reales.
- Si el texto no parece un estado de cuenta, devuelve {"transactions": []}.

TEXTO DEL ESTADO DE CUENTA:
"""


def parse_bank_statement(content):
    config = get_llm_config()
    raw = _chat(
        config,
        [{"role": "user", "content": PARSE_PROMPT + content[:MAX_STATEMENT_CHARS]}],
        temperature=0,
    )
    data = _extract_json(raw)
    transactions = []
    for tx in data.get("transactions", []):
        try:
            amount = round(float(tx.get("amount", 0)), 2)
        except (TypeError, ValueError):
            continue
        date = str(tx.get("date", ""))[:10]
        if amount <= 0 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            continue
        currency = tx.get("currency") if tx.get("currency") in ("MXN", "USD") else "MXN"
        direction = "in" if tx.get("direction") == "in" else "out"
        category = tx.get("suggested_category")
        if category not in VALID_CATEGORIES:
            category = "other"
        transactions.append(
            {
                "date": date,
                "concept": str(tx.get("concept", ""))[:255] or "Movimiento",
                "amount": amount,
                "currency": currency,
                "direction": direction,
                "suggested_category": category,
            }
        )
    return transactions


ANALYZE_PROMPT = """Eres el CFO fraccional de Sintérgica AI, una agencia/consultora mexicana. \
Te doy sus datos financieros en JSON: P&L mensual, proyección a 6 meses, clientes con su estado \
de cobranza, y hallazgos automáticos.

Escribe un análisis ejecutivo EN ESPAÑOL, directo y accionable, de 200 a 350 palabras, \
en texto plano con guiones para las listas (sin markdown de encabezados). Estructura:
1. Diagnóstico en 2-3 frases (lo más importante primero).
2. Riesgos concretos, cada uno con el número que lo sustenta.
3. 3 a 5 acciones recomendadas para las próximas 2 semanas, ordenadas por impacto.

Reglas: usa solo las cifras del JSON (no inventes); da los montos con su moneda; \
si falta información (caja, gastos), dilo y pide capturarla; nunca sumes MXN con USD.

DATOS:
"""


def analyze_finances(context):
    config = get_llm_config()
    raw = _chat(
        config,
        [{"role": "user", "content": ANALYZE_PROMPT + json.dumps(context, ensure_ascii=False)}],
        temperature=0.3,
    )
    return raw.strip()
