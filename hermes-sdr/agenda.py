#!/usr/bin/env python3
"""Booked times for the attendant offer (Talles, 10/10/2026: "salvar a info de horários marcados").

Runs on the VM every 5 minutes (cron). Collects the 20-minute calls the agent booked (sdr_records
proximo_passo_em of "conversa de 20 min") plus hermes-sdr/agenda-manual.json (Talles' own commitments) and writes
them to ofertas.json -> atendimento.horarios_ocupados. The bridge re-reads ofertas.json on every turn, so the agent,
the follow-up touches and the reviewer see the busy times right away. Past times are dropped. Atomic write.
"""
import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
OFERTAS = HERE / "ofertas.json"
MANUAL = HERE / "agenda-manual.json"
TZ = ZoneInfo("America/Sao_Paulo")
QUERY = r"""
import json, sqlite3
c = sqlite3.connect("/data/bridge.db")
rows = {}
for conv, field, value in c.execute("SELECT conversation, field, value FROM sdr_records ORDER BY created"):
    rows.setdefault(conv, {})[field] = value
out = []
for conv, rec in rows.items():
    if "20 min" in (rec.get("proximo_passo") or "") and "T" in (rec.get("proximo_passo_em") or "") and not rec.get("desfecho"):
        nome = c.execute("SELECT json_extract(dados,'$.nome') FROM sdr_prospects WHERE conversation=?", (conv,)).fetchone()
        out.append({"quando": rec["proximo_passo_em"], "o_que": f"call com {(nome or [''])[0] or 'lead'} (conversa {conv})"})
print(json.dumps(out, ensure_ascii=False))
"""


def booked_by_agent() -> list[dict]:
    bridge = subprocess.run(["sudo", "docker", "ps", "-q", "-f", "name=integration_bridge"], capture_output=True, text=True).stdout.split()
    if not bridge:
        return []
    r = subprocess.run(["sudo", "docker", "exec", "-i", bridge[0], "python", "-"], input=QUERY, capture_output=True, text=True, timeout=60)
    return json.loads(r.stdout or "[]")


def main() -> None:
    manual = json.loads(MANUAL.read_text(encoding="utf-8")) if MANUAL.exists() else []
    now = datetime.now(TZ) - timedelta(minutes=30)
    items = {}
    for item in booked_by_agent() + manual:
        try:
            when = datetime.fromisoformat(item["quando"]).replace(tzinfo=TZ)
        except (KeyError, ValueError):
            continue
        if when >= now:
            items[when.strftime("%Y-%m-%dT%H:%M")] = item.get("o_que") or "ocupado"
    busy = [{"quando": k, "o_que": v} for k, v in sorted(items.items())]
    data = json.loads(OFERTAS.read_text(encoding="utf-8"))
    atendimento = data.setdefault("atendimento", {})
    if atendimento.get("horarios_ocupados") == busy:
        return
    atendimento["horarios_ocupados"] = busy
    atendimento["regra_horarios_ocupados"] = ("Nunca ofereça nem confirme um horário de horarios_ocupados (cada call dura 20 min e "
                                              "precisa de 40 min livres antes e depois). Ofereça outro dia útil ou outra hora.")
    fd, tmp = tempfile.mkstemp(dir=str(HERE), prefix=".ofertas-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o644)
    os.replace(tmp, OFERTAS)
    print(datetime.now(TZ).strftime("%d/%m %H:%M"), "horários ocupados:", busy)


if __name__ == "__main__":
    main()
