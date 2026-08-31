"""Prueba de la fase 3 del chat (tiempo real): endpoint /broadcast del live
(401 sin secret, 200 con secret) y el camino Django→live (realtime.py y la
tarea de eventos). Corre dentro del contenedor api. No deja datos.

La entrega WS extremo a extremo (dos navegadores en el mismo canal) se
verifica a mano: este script cubre todo lo comprobable sin una cookie de
sesión real.
"""

import json
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plane.settings.production")
django.setup()

import requests  # noqa: E402

from plane.chat.realtime import _live_base, broadcast_channel_event, channel_document_name  # noqa: E402

OK, FAIL = "\033[92mOK\033[0m", "\033[91mFALLO\033[0m"
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"  {OK if cond else FAIL}  {name}" + (f" — {detail}" if detail else ""))


base = _live_base()
print(f"BROADCAST ({base})")

r = requests.get(f"{base}/health", timeout=5)
check("live /health responde", r.status_code == 200, f"HTTP {r.status_code}")

body = json.dumps({"document_name": "chat:00000000-0000-0000-0000-000000000000", "payload": {"event": "ping"}})
headers = {"Content-Type": "application/json"}

r = requests.post(f"{base}/broadcast/", data=body, headers=headers, timeout=5)
check("sin secret → 401", r.status_code == 401, f"HTTP {r.status_code}")

r = requests.post(
    f"{base}/broadcast/",
    data=body,
    headers={**headers, "live-server-secret-key": "wrong-key"},
    timeout=5,
)
check("secret incorrecto → 401", r.status_code == 401, f"HTTP {r.status_code}")

secret = os.environ.get("LIVE_SERVER_SECRET_KEY", "")
check("LIVE_SERVER_SECRET_KEY presente en el api", bool(secret))

r = requests.post(
    f"{base}/broadcast/",
    data=body,
    headers={**headers, "live-server-secret-key": secret},
    timeout=5,
)
delivered = r.json() if r.status_code == 200 else {}
check(
    "con secret → 200 (0 receptores, nadie conectado)",
    r.status_code == 200 and delivered.get("delivered") in (True, False),
    f"HTTP {r.status_code} {delivered}",
)

r = requests.post(
    f"{base}/broadcast/",
    data=json.dumps({"document_name": "", "payload": {}}),
    headers={**headers, "live-server-secret-key": secret},
    timeout=5,
)
check("payload inválido → 400", r.status_code == 400, f"HTTP {r.status_code}")

print("\nDJANGO → LIVE")
check("document_name con prefijo chat:", channel_document_name("abc") == "chat:abc")
ok = broadcast_channel_event("00000000-0000-0000-0000-000000000000", {"event": "ping", "ts": "verify11"})
check("broadcast_channel_event entrega al live", ok is True)

ok = None
try:
    os_secret = os.environ.pop("LIVE_SERVER_SECRET_KEY")
    ok = broadcast_channel_event("00000000-0000-0000-0000-000000000000", {"event": "ping"})
finally:
    os.environ["LIVE_SERVER_SECRET_KEY"] = os_secret
check("sin secret degrada a False sin lanzar", ok is False)

total, passed = len(results), sum(results)
print(f"\n{passed}/{total} checks")
raise SystemExit(0 if passed == total else 1)
