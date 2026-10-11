"""Import the prospecção JSON files into the lead tables of the bridge database (leads.py).

Idempotent (a second run changes nothing), one transaction for everything, prints the counts.

    python importar_leads.py --dados DIR [--classificacao FILE] [--db PATH] [--preferir-arquivos] [--simular]

DIR holds what the collection steps wrote (17-prospeccao/dados in the screener workspace):
  negocios.json, negocios-enriquecidos.json, decisores.json, instagram-perfis.json, fila-prospeccao.json and
  funil-AAAA-MM-DD.jsonl. FILE is the manual classification (17-prospeccao/painel/funil-classificado.json).
A missing file is skipped and reported. The database is BRIDGE_DB (default /data/bridge.db) or --db.

Every sdr_prospects row ends with its lead: a number that only exists in sdr_prospects.dados becomes a lead
(fonte 'sdr_prospects'). For numbers in both, the fields the agent reads (leads.FIELDS) follow sdr_prospects.dados,
which is what production uses today, unless --preferir-arquivos. The 10/10 "legado" marks inside dados move to the
sdr_prospects columns status_antes_legado and legado_em. Exit code 1 when a prospect is left without a lead.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dados", required=True, help="pasta com os JSON da coleta")
    parser.add_argument("--classificacao", help="funil-classificado.json")
    parser.add_argument("--db", help="banco (padrão: BRIDGE_DB ou /data/bridge.db)")
    parser.add_argument("--preferir-arquivos", action="store_true",
                        help="nos números já em sdr_prospects, os arquivos vencem o dados de produção")
    parser.add_argument("--simular", action="store_true", help="faz tudo e desfaz no fim (rollback)")
    args = parser.parse_args(argv)
    if args.db:
        os.environ["BRIDGE_DB"] = args.db
    import sdr  # after BRIDGE_DB is set
    if args.db:
        sdr.DB_PATH = Path(args.db)
    import leads

    folder = Path(args.dados)
    now = time.time()
    report: dict[str, dict[str, int]] = {}
    skipped: list[str] = []

    def tally(name: str, changed: bool) -> None:
        counts = report.setdefault(name, {"lidos": 0, "alterados": 0})
        counts["lidos"] += 1
        counts["alterados"] += int(bool(changed))

    def read(name: str) -> tuple[Any, float | None]:
        path = folder / name
        if not path.exists():
            skipped.append(name)
            return None, None
        return load(path), path.stat().st_mtime

    # Businesses: Maps list, then the enriched list over it (same 1.214, more fields).
    businesses: dict[str, dict[str, Any]] = {}   # numero -> {"fonte", "item", "coletado_em"}
    raw_sources: list[tuple[str, str, Any, str | None, float | None]] = []  # (fonte, chave, payload, numero, coletado_em)
    for name, source in (("negocios.json", "maps"), ("negocios-enriquecidos.json", "enriquecido")):
        data, stamp = read(name)
        for item in data or []:
            numero = leads.normalize_number(item.get("telefone_e164") or item.get("telefone") or item.get("numero"))
            if not numero:
                tally(f"{name} (sem número válido)", False)
                continue
            entry = businesses.setdefault(numero, {"fonte": "maps", "item": {}, "coletado_em": stamp})
            entry["item"].update({k: v for k, v in item.items() if k not in ("telefone_e164", "telefone", "numero")})
            entry["coletado_em"] = max(entry["coletado_em"] or 0, stamp or 0) or None
            raw_sources.append((source, numero, item, numero, stamp))
    decisores, decisores_at = read("decisores.json")
    perfis, perfis_at = read("instagram-perfis.json")
    fila, fila_at = read("fila-prospeccao.json")
    fila_items = ((fila.get("negocios") if isinstance(fila, dict) else fila) or []) if fila else []
    for item in fila_items:
        numero = leads.normalize_number(item.get("telefone_e164") or item.get("numero"))
        if not numero:
            tally("fila-prospeccao.json (sem número válido)", False)
            continue
        raw_sources.append(("fila", numero, item, numero, fila_at))
        if numero not in businesses:  # audit only when the enriched list has it (the enriched list is newer)
            businesses[numero] = {"fonte": "fila", "item": {k: v for k, v in item.items() if k != "telefone_e164"}, "coletado_em": fila_at}
    for key, entry in (decisores or {}).items():
        numero = leads.normalize_number(key)
        if numero and numero not in businesses:
            businesses[numero] = {"fonte": "decisores", "coletado_em": decisores_at,
                                  "item": {"nome": entry.get("nome_negocio"), "nicho": entry.get("nicho"), "cidade": entry.get("cidade")}}

    c = leads.connect()
    before = leads.contagens(c)
    prospects: list[tuple] = []
    missing = 0
    try:
        c.execute("BEGIN IMMEDIATE")
        if leads._has_table(c, "sdr_prospects"):
            prospects = c.execute("SELECT numero, dados, status_antes_legado, legado_em FROM sdr_prospects").fetchall()
        # What production uses today (sdr_prospects.dados) over the files, unless --preferir-arquivos.
        created = 0
        for numero, raw, _, _ in prospects:
            try:
                data = json.loads(raw or "{}")
            except ValueError:
                data = {}
            raw_sources.append(("sdr_prospects.dados", numero, data, numero, None))
            fields = {k: v for k, v in data.items() if k in leads.FIELDS and v not in (None, "")}
            if numero not in businesses:
                if not c.execute("SELECT 1 FROM leads WHERE numero=?", (numero,)).fetchone():
                    created += 1
                businesses[numero] = {"fonte": leads.TEST_SOURCE if data.get("teste_do_dono") else "sdr_prospects", "item": fields,
                                      "coletado_em": None}
            elif not args.preferir_arquivos:
                businesses[numero]["item"].update(fields)
        report["sdr_prospects sem lead nos arquivos nem no banco (criados)"] = {"lidos": created, "alterados": created}

        for numero, entry in businesses.items():
            tally(f"leads (fonte {entry['fonte']})", leads.save(numero, entry["item"], fonte=entry["fonte"], c=c,
                                                                coletado_em=entry["coletado_em"], now=now))
        for key, entry in (decisores or {}).items():
            numero = leads.normalize_number(key)
            if not numero:
                tally("decisores.json (sem número válido)", False)
                continue
            raw_sources.append(("decisores", numero, entry, numero, decisores_at))
            tally("lead_decisores", leads.save_decisor(numero, entry, c=c, coletado_em=decisores_at, now=now))
        for key, perfil in (perfis or {}).items():
            perfil = {"username": key, **(perfil or {})}
            user = leads.instagram_user(perfil.get("username"))
            linked = c.execute("SELECT numero FROM leads WHERE instagram_usuario=? ORDER BY numero LIMIT 1", (user,)).fetchone()
            raw_sources.append(("instagram", user, perfil, linked[0] if linked else None, perfis_at))
            tally("lead_instagram", leads.save_instagram(perfil, c=c, coletado_em=perfis_at, now=now))
        # Funnel reports (one line per conversation, plus a "resumo" line kept only as audit).
        for path in sorted(folder.glob("funil-*.jsonl")):
            day = re.sub(r"^funil-", "", path.stem)
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                if "resumo" in item:
                    raw_sources.append(("funil-relatorio", f"{day}:resumo", item["resumo"], None, path.stat().st_mtime))
                    continue
                raw_sources.append(("funil-relatorio", f"{day}:{item.get('conversa')}", item, None, path.stat().st_mtime))
                tally("funil_relatorio", leads.save_relatorio(day, item, c=c))
        if args.classificacao:
            path = Path(args.classificacao)
            if path.exists():
                for item in load(path):
                    raw_sources.append(("funil-classificado", str(item.get("conversation")), item, None, path.stat().st_mtime))
                    tally("funil_classificacao", leads.save_classificacao(item, fonte="funil-classificado.json", c=c, now=now))
            else:
                skipped.append(str(path))
        # The 10/10 "legado" marks: from dados to columns.
        for numero, raw, before_legacy, legacy_at in prospects:
            try:
                data = json.loads(raw or "{}")
            except ValueError:
                data = {}
            legacy = (data.get("status_antes_legado"), data.get("legado_em"))
            changed = any(legacy) and (before_legacy, legacy_at) != legacy
            if changed:
                c.execute("UPDATE sdr_prospects SET status_antes_legado=?, legado_em=? WHERE numero=?", (*legacy, numero))
            if any(legacy):
                tally("sdr_prospects (marca de legado)", changed)
        for fonte, chave, payload, numero, stamp in raw_sources:
            tally(f"lead_fontes ({fonte})", leads.save_fonte(fonte, chave, payload, numero=numero, coletado_em=stamp, c=c, now=now))
        if prospects:
            missing = c.execute("SELECT COUNT(*) FROM sdr_prospects p WHERE NOT EXISTS (SELECT 1 FROM leads l WHERE l.numero=p.numero)").fetchone()[0]
        after = leads.contagens(c)
        if args.simular:
            c.rollback()
        else:
            c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()
    print(json.dumps({"banco": str(sdr.DB_PATH), "simulado": args.simular, "arquivos_ausentes": skipped, "por_destino": report,
                      "tabelas_antes": before, "tabelas_depois": after,
                      "sdr_prospects": len(prospects), "sdr_prospects_sem_lead": missing}, ensure_ascii=False, indent=1))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
