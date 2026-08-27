"""Build-time patcher for the Sintergica CE extension.

Exact-string patches with hard assertions: if upstream code changed and a
pattern no longer matches, the docker build FAILS instead of silently
producing a broken image.
"""

import sys

OK = "\033[92mOK\033[0m"


def patch(path, old, new, must=True):
    with open(path) as f:
        content = f.read()
    if old not in content:
        if must:
            print(f"FATAL: pattern not found in {path}:\n{old[:200]}")
            sys.exit(1)
        print(f"skip (not found): {path}")
        return
    if new in content:
        print(f"already patched: {path}")
        return
    with open(path, "w") as f:
        f.write(content.replace(old, new, 1))
    print(f"{OK} patched {path}")


# ---------------------------------------------------------------------------
# 1. Register the extension url patterns on the public API
# ---------------------------------------------------------------------------
patch(
    "/code/plane/api/urls/__init__.py",
    "from .sticky import urlpatterns as sticky_patterns",
    "from .sticky import urlpatterns as sticky_patterns\n"
    "from .page_ext import urlpatterns as page_ext_patterns",
)
patch(
    "/code/plane/api/urls/__init__.py",
    "    *sticky_patterns,\n]",
    "    *sticky_patterns,\n    *page_ext_patterns,\n]",
)

# ---------------------------------------------------------------------------
# 2. AI fix: route each provider to its real endpoint (stock CE always calls
#    api.openai.com, so Anthropic/Gemini could never work) and refresh the
#    Anthropic model list.
# ---------------------------------------------------------------------------
patch(
    "/code/plane/app/views/external/base.py",
    '''        # For Gemini, prepend provider name to model
        if provider.lower() == "gemini":
            model = f"gemini/{model}"

        client = OpenAI(api_key=api_key)''',
    '''        # Route each provider to its OpenAI-compatible endpoint.
        provider_base_urls = {
            "anthropic": "https://api.anthropic.com/v1/",
            "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
        }
        client = OpenAI(api_key=api_key, base_url=provider_base_urls.get(provider.lower()))''',
)

patch(
    "/code/plane/app/views/external/base.py",
    '''class AnthropicProvider(LLMProvider):
    name = "Anthropic"
    models = [
        "claude-3-5-sonnet-20240620",
        "claude-3-haiku-20240307",
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-2.1",
        "claude-2",
        "claude-instant-1.2",
        "claude-instant-1",
    ]
    default_model = "claude-3-sonnet-20240229"''',
    '''class AnthropicProvider(LLMProvider):
    name = "Anthropic"
    models = [
        "claude-sonnet-4-5",
        "claude-haiku-4-5",
        "claude-opus-4-1",
        "claude-3-7-sonnet-latest",
        "claude-3-5-haiku-latest",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-sonnet-20240620",
        "claude-3-haiku-20240307",
        "claude-3-opus-20240229",
    ]
    default_model = "claude-sonnet-4-5"''',
)

# ---------------------------------------------------------------------------
# 3. Sanity: compile every file we touched or added
# ---------------------------------------------------------------------------
import py_compile

for f in (
    "/code/plane/api/urls/__init__.py",
    "/code/plane/api/urls/page_ext.py",
    "/code/plane/api/views/page_ext.py",
    "/code/plane/api/serializers/page_ext.py",
    "/code/plane/app/views/external/base.py",
):
    py_compile.compile(f, doraise=True)
    print(f"{OK} compiles {f}")

print("ALL PATCHES APPLIED")
