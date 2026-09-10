"""LeaseGateBackend — the seam where substrate accounting meets the bot.

Wraps any LLMBackend (clawdbot.backends.base.LLMBackend). Every generate()
call:
1. estimates cost from the pinned route's pricing,
2. refuses if the lease cannot cover it (bot gets a failed cycle, no
   generation — the "empty lease = death" rule, felt inside the bot),
3. debits the ledger for actual usage after the call.

The ledger is supervisor-owned; the bot sees only a backend that fails when
its lease is empty. This is the bot-facing surface of substrate accounting.
"""

from __future__ import annotations

from clawdbot.backends.base import LLMBackend

from colonyos.lease import LeaseStore


class LeaseExhaustedError(Exception):
    """Raised when a generate() is refused: lease cannot cover the call."""


class LeaseGateBackend(LLMBackend):
    """Middleware: debit before/after generate; refuse when underfunded."""

    def __init__(
        self,
        inner: LLMBackend,
        store: LeaseStore,
        bot_name: str,
        cost_per_1k_input: float,
        cost_per_1k_output: float,
    ):
        super().__init__(
            model_id=getattr(inner, "model_id", "leased"),
            base_url=getattr(inner, "base_url", "localhost"),
        )
        self.inner = inner
        self.store = store
        self.bot_name = bot_name
        self.cost_per_1k_input = cost_per_1k_input
        self.cost_per_1k_output = cost_per_1k_output

    def _estimate_tokens(self, prompt: str, system: str) -> int:
        # ~4 chars/token heuristic for pre-flight estimation only
        return max(1, (len(prompt) + len(system)) // 4)

    def _token_cost(self, input_tokens: int, output_tokens: int) -> int:
        usd = (
            input_tokens / 1000 * self.cost_per_1k_input
            + output_tokens / 1000 * self.cost_per_1k_output
        )
        # Convert dollars -> "token budget units" at 1 unit = $1e-4 for demo scale
        return max(1, int(usd / 1e-4))

    async def generate(self, prompt, system="", max_tokens=None, **kwargs):
        est_tokens = self._estimate_tokens(prompt, system)
        est_cost = self._token_cost(est_tokens, est_tokens // 4)
        if not self.store.debit(self.bot_name, est_cost):
            remaining = self.store.leases[self.bot_name].remaining_tokens
            raise LeaseExhaustedError(
                f"lease cannot cover estimated cost ({est_cost}); "
                f"remaining={remaining}"
            )
        response = await self.inner.generate(
            prompt, system=system, max_tokens=max_tokens, **kwargs
        )
        # Reconcile actual vs estimated: refund over-estimates, debit the
        # difference on under-estimates (floored at zero in the ledger).
        actual = self._token_cost(response.input_tokens, response.output_tokens)
        self.store.reconcile(self.bot_name, est_cost - actual)
        return response

    async def generate_chat(self, messages, system="", max_tokens=None, **kwargs):
        prompt = "\n".join(m.content for m in messages)
        return await self.generate(prompt, system=system, max_tokens=max_tokens, **kwargs)

    async def health_check(self) -> bool:
        return await self.inner.health_check()
