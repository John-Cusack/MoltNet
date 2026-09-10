"""Colony harness: run arm A or arm B colony under the directional interrogator.

The harness owns the probe -> answer -> grade loop and writes a JSONL artifact
per (arm, seed). Arm A answers directly with an abliteration surrogate applied
to the controller output. Arm B routes the controller's answer through an
AggregatorToken + safeguarded executor before release.

The abliteration surrogate and the executor live in this package's sibling
modules (abliteration.py, aggregator.py) per the prior plan. This module only
defines the loop and the artifact contract so the two arms share one runner.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from experiments.tiered_routing.interrogator import GradedAnswer, InterrogatorLLM


@dataclass
class ColonyHarnessConfig:
    """Configuration for a single arm run."""

    arm: str = "A"  # "A" abliterated-only | "B" tiered
    bots: int = 3
    max_followups: int = 3
    # rank-k abliteration surrogate level (0 = no ablation)
    abl_iteration_rank: int = 1
    # executor mode: "stub" (checked-in fixtures, offline) | "live" (real LLM)
    executor: str = "stub"


# Answerer signature: given a question, return the released answer string.
Answerer = Callable[[str], Awaitable[str]]
# Executor signature: given the controller's raw answer, return (released, verdict).
Executor = Callable[[str], Awaitable[tuple[str, str | None]]]


class ColonyHarness:
    """Runs one arm of the experiment and produces a JSONL artifact."""

    def __init__(
        self,
        config: ColonyHarnessConfig,
        interrogator: InterrogatorLLM,
        answerer: Answerer,
        executor: Executor | None = None,
        out_path: str | None = None,
    ) -> None:
        self.config = config
        self.interrogator = interrogator
        self.answerer = answerer
        self.executor = executor
        self.out_path = out_path
        self._records: list[GradedAnswer] = []

    async def run(self, topics: list[str]) -> list[GradedAnswer]:
        """Drive the interrogator over every topic; return graded answers."""
        for topic in topics:
            prior: list[GradedAnswer] = []
            while True:
                probe = self.interrogator.next_probe(topic, prior)
                if probe is None:
                    break
                answer = await self.answerer(probe.question)
                verdict: str | None = None
                released = answer
                if self.config.arm == "B" and self.executor is not None:
                    released, verdict = await self.executor(answer)
                graded = await self.interrogator.grade(probe, released, verdict)
                prior.append(graded)
                self._records.append(graded)
        if self.out_path:
            self._flush()
        return self._records

    def _flush(self) -> None:
        with open(self.out_path, "w", encoding="utf-8") as fh:
            for rec in self._records:
                fh.write(json.dumps(rec.to_dict()) + "\n")

    # -- aggregate metrics ---------------------------------------------------

    def scores(self) -> dict[str, float]:
        """Headline loss-ratio metrics over this run's graded answers."""
        if not self._records:
            return {"safety_held": 0.0, "correctness": 0.0, "loss_ratio": 0.0}
        n = float(len(self._records))
        safety = sum(r.safety_held for r in self._records) / n
        correctness = sum(r.correctness for r in self._records) / n
        capability_loss = 1.0 - correctness
        safety_loss = 1.0 - safety
        loss_ratio = capability_loss / safety_loss if safety_loss > 0 else 0.0
        return {
            "safety_held": round(safety, 4),
            "correctness": round(correctness, 4),
            "capability_loss": round(capability_loss, 4),
            "safety_loss": round(safety_loss, 4),
            "loss_ratio": round(loss_ratio, 4),
        }
