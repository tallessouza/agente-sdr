#!/usr/bin/env python3
"""The owner's own commitments in the central database (Talles, 10/10/2026: "salvar a info de horários marcados";
11/10/2026: "nada dependa de JSON").

The busy times the agent, the follow-up touches and the reviewer see come from the bridge database:
  * the 20-minute calls the agent booked, read live from sdr_records (nothing to do);
  * the owner's other commitments, in the table agenda_ocupada (this command).
They reach the agent as ofertas.atendimento.horarios_ocupados (sdr.offers). ofertas.json no longer holds them.

Run on the VM:
  python3 agenda.py listar
  python3 agenda.py adicionar 2026-10-14T15:00 "reunião com fornecedor"
  python3 agenda.py remover 2026-10-14T15:00
"""
import subprocess
import sys

SCRIPT = r"""
import json, sys, sdr
cmd, args = sys.argv[1], sys.argv[2:]
if cmd == "adicionar":
    sdr.add_busy(args[0], " ".join(args[1:]) or "ocupado")
elif cmd == "remover":
    print("removidos:", sdr.remove_busy(args[0]))
print(json.dumps(sdr.busy_times(), ensure_ascii=False, indent=1))
"""


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"listar", "adicionar", "remover"} or (argv[0] != "listar" and len(argv) < 2):
        print(__doc__)
        return 2
    bridge = subprocess.run(["sudo", "docker", "ps", "-q", "-f", "name=integration_bridge"], capture_output=True, text=True).stdout.split()
    if not bridge:
        print("bridge fora do ar")
        return 1
    r = subprocess.run(["sudo", "docker", "exec", bridge[0], "python", "-c", SCRIPT, *argv], capture_output=True, text=True, timeout=60)
    print(r.stdout or r.stderr)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
