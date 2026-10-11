"""Every decision of the template farm, as an IP decision card (Talles 11/10: "toda decisão tem que passar pelo método
IP mas que consigamos ter replicabilidade"). The rules that decide live in template_health; this module keeps, for
each kind of action, its standing card (objective, alternatives, impact, cost, control, irreversibility, rollback,
confidence) and records every time the farm acts, with the target and the result, in tpl_decisoes.
"""
import json
import sqlite3
import time
from typing import Any

import sdr

# The standing card of each farm action (Manual de Inteligência Pragmática, 3.5 DECIDIR).
CARTOES: dict[str, dict[str, str]] = {
    "pedir_abertura": {
        "objetivo": "manter o estoque de aberturas utility saudáveis no alvo do farm, para a prospecção abrir no 80/20",
        "alternativas": "não pedir agora; pedir menos (freio de 10 por dia); só variações das vencedoras",
        "impacto": "estoque de aberturas; nenhum lead atingido",
        "custo": "nenhum envio; atenção zero do Talles",
        "controle": "a Meta decide a categoria (a maioria volta marketing)",
        "irreversivel": "não", "rollback": "apagar o template na Meta",
        "confianca": "placar de aprovação por modelo; só o modelo vencedor é gerado"},
    "pedir_retomada_utility": {
        "objetivo": "ter retomada utility em cada família, para o 80/20 das retomadas andar",
        "alternativas": "não pedir; pedir marketing; insistir 1 por dia depois de reclassificações",
        "impacto": "retomadas de quem parou; nenhum lead atingido",
        "custo": "nenhum envio",
        "controle": "a Meta decide a categoria; reclassificar repetido vira reincidência (mudança sem aviso)",
        "irreversivel": "não", "rollback": "apagar o template na Meta",
        "confianca": "regra da Meta: utility é não promocional; conversa e robô passaram como utility em 11/10"},
    "pedir_retomada_marketing": {
        "objetivo": "dar à família sem utility possível (sem_resposta) uma marketing dentro do 80/20",
        "alternativas": "não pedir (família sem retomada); pedir utility (a Meta devolve marketing)",
        "impacto": "retomadas de quem nunca respondeu",
        "custo": "nenhum envio", "controle": "a Meta aprova ou recusa",
        "irreversivel": "não", "rollback": "apagar o template na Meta",
        "confianca": "sem_resposta_u01..u04 foram aprovadas como marketing em 11/10"},
    "insistir_utility": {
        "objetivo": "tentar de novo utility numa família que a Meta reclassificou (esforçar ao máximo, Talles 11/10)",
        "alternativas": "desistir; insistir mais de 1 por dia (empilha reclassificações)",
        "impacto": "estoque de retomadas", "custo": "nenhum envio",
        "controle": "a Meta decide", "irreversivel": "não", "rollback": "apagar o template",
        "confianca": "redação nova a cada tentativa; no máximo 1 por dia por família"},
    "apagar_marketing_excedente": {
        "objetivo": "manter o estoque em 80/20 (Talles 11/10: deixa 80/20 de abertura e 80/20 de retomada)",
        "alternativas": "não apagar (estoque fora do 80/20); só parar de pedir marketing",
        "impacto": "sorteio de templates; nenhum lead atingido",
        "custo": "perde o template apagado", "controle": "nosso",
        "irreversivel": "sim: apagado na Meta não volta", "rollback": "pedir de novo e esperar aprovação",
        "confianca": "ficam as mais usadas e saudáveis; família sem utility primeiro"},
    "apagar_rejeitado": {
        "objetivo": "tirar da lista o template que a Meta recusou, guardando o motivo para não repetir o formato",
        "alternativas": "manter na lista (não atrapalha o sorteio, só polui)",
        "impacto": "nenhum envio, nenhum lead", "custo": "nenhum", "controle": "nosso",
        "irreversivel": "sim, mas recusado não serve para envio", "rollback": "nenhum necessário",
        "confianca": "motivo da Meta (rejected_reason) guardado no cartão"},
}


def connect() -> sqlite3.Connection:
    c = sdr.connect()
    c.execute("CREATE TABLE IF NOT EXISTS tpl_decisoes (id INTEGER PRIMARY KEY, ts REAL NOT NULL, acao TEXT NOT NULL, alvo TEXT, "
              "cartao TEXT NOT NULL, resultado TEXT)")
    return c


def registrar(acao: str, alvo: str, resultado: str, **extra: str) -> None:
    """One decision of the farm with its card (the standing one of the action, plus what is specific this time)."""
    cartao = {**CARTOES.get(acao, {}), **{k: v for k, v in extra.items() if v}}
    try:
        with connect() as c:
            c.execute("INSERT INTO tpl_decisoes(ts,acao,alvo,cartao,resultado) VALUES (?,?,?,?,?)",
                      (time.time(), acao, alvo, json.dumps(cartao, ensure_ascii=False), resultado[:300]))
    except sqlite3.Error:
        pass  # the farm must go on even if the record fails


def recentes(limite: int = 60) -> list[dict[str, Any]]:
    with connect() as c:
        c.row_factory = sqlite3.Row
        return [{**dict(r), "cartao": json.loads(r["cartao"])} for r in c.execute("SELECT * FROM tpl_decisoes ORDER BY id DESC LIMIT ?", (limite,))]
