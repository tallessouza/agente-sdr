"""Regression of the robot conversation (panel next step: "SOUL, revisor e supervisor dizendo a mesma coisa").

When a robot (menu, automatic greeting, another AI) answers the prospect test, every prompt must agree:
  * the agent sends ONE colleague-to-colleague message and then stays silent ([[SILENCIO]]);
  * it never answers what the robot asked (name, city, menu option) and never pretends to be a customer;
  * it records the robot and desfecho = avaliar_dono (a robot is not "desqualificado": the owner decides);
  * the spaced touches (fup) speak to whoever reads the WhatsApp later, never to the robot, and the reviewer lets them;
  * the brain keeps sending those touches for avaliar_dono and stops for a person's real outcome.
"""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDR_BRAIN_TOKEN", "test")
os.environ.setdefault("SDR_BRAIN_DB", os.path.join(tempfile.gettempdir(), "sdr-brain-robo.db"))

ROOT = Path(__file__).resolve().parent.parent
SOUL = (ROOT / "hermes-sdr" / "SOUL.md").read_text(encoding="utf-8")
PROMPTS = Path(__file__).resolve().parent / "prompts"
REVISOR = (PROMPTS / "revisor.md").read_text(encoding="utf-8")
SUPERVISOR = (PROMPTS / "supervisor.md").read_text(encoding="utf-8")
FUP = (PROMPTS / "fup.md").read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.split())


class RobotRegressionTests(unittest.TestCase):
    def test_one_colleague_message_then_silence_everywhere(self):
        self.assertIn("Com IA, você manda UMA mensagem de colega para colega", flat(SOUL))
        self.assertIn("Depois dessa mensagem, só [[SILENCIO]]", flat(SOUL))
        self.assertIn("o agente manda uma única mensagem de colega para colega e depois fica em silêncio", flat(SUPERVISOR))
        self.assertIn("o agente manda UMA mensagem de colega para colega", flat(REVISOR))
        self.assertIn("mandar uma SEGUNDA mensagem depois que a de colega já está no transcript → aí reescrever como [[SILENCIO]]", flat(REVISOR))

    def test_never_answers_the_robot_nor_pretends_to_be_a_customer(self):
        self.assertIn("Nunca responda ao que o robô pediu (nome, cidade, opção do menu)", flat(SOUL))
        self.assertIn("responder ao que o robô pediu (nome, cidade, opção do menu), fingir ser cliente", flat(REVISOR))
        self.assertIn("Nunca escolha opção de menu, nunca responda à pergunta do robô", flat(FUP))

    def test_robot_is_avaliar_dono_not_desqualificado(self):
        self.assertIn("[[REGISTRO: resposta_automatica = sim]] [[REGISTRO: desfecho = avaliar_dono]]", flat(SOUL))
        self.assertIn("[[REGISTRO: atende_com_ia = sim]] [[REGISTRO: desfecho = avaliar_dono]]", flat(SOUL))
        self.assertIn("avaliar_dono [só robô do outro lado]", flat(SOUL))
        import app
        self.assertFalse(app.outcome_stops_touches({"resposta_automatica": "sim", "desfecho": "avaliar_dono"}))
        self.assertTrue(app.outcome_stops_touches({"resposta_automatica": "sim", "desfecho": "desqualificado"}))

    def test_spaced_touches_speak_to_the_owner_and_the_reviewer_lets_them(self):
        self.assertIn("o toque fala com QUEM LÊ o WhatsApp depois, o dono ou o responsável, nunca com o robô", flat(FUP))
        self.assertIn("Exceção: `tipo` = toque é o follow-up espaçado que fala com QUEM LÊ o WhatsApp depois", flat(REVISOR))


if __name__ == "__main__":
    unittest.main()
