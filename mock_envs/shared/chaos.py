"""
Shared chaos-injection manager, usable by every mock company environment.
Lets us deliberately trigger realistic failures (timeouts, server errors,
missing/renamed fields) ON DEMAND — including live, during a demo — so
the agent's reliability handling can be proven with real evidence instead
of a scripted happy path.

Design notes:
- Rules are consumed (one-shot by default) so you can trigger a failure,
  watch the agent recover, and then see the system behave normally again
  without manually resetting state.
- `maybe_disrupt_before` handles failure modes that should short-circuit
  the request entirely (timeout, 500 error).
- `peek` + `mutate_data` + `consume` are split apart (instead of one
  mutate-and-consume call) so a single rule can be applied consistently
  across a whole response (e.g. a list of rows) without being consumed
  multiple times mid-response.
"""
import threading
import time
from dataclasses import dataclass


@dataclass
class ChaosRule:
    mode: str                      # "timeout" | "error_500" | "missing_field" | "rename_field"
    remaining: int = 1
    field_name: str | None = None  # which field to mutate, for field-level chaos
    rename_to: str | None = None   # new field name, for "rename_field"
    duration: float = 5.0          # sleep duration, for "timeout"


class ChaosManager:
    def __init__(self):
        self._rules: dict[str, ChaosRule] = {}
        self._lock = threading.Lock()

    def set_rule(self, target: str, mode: str, times: int = 1,
                 field_name: str | None = None, rename_to: str | None = None,
                 duration: float = 5.0):
        with self._lock:
            self._rules[target] = ChaosRule(
                mode=mode, remaining=times, field_name=field_name,
                rename_to=rename_to, duration=duration,
            )

    def clear(self, target: str | None = None):
        with self._lock:
            if target is None:
                self._rules.clear()
            else:
                self._rules.pop(target, None)

    def get_rules(self) -> dict:
        with self._lock:
            return {
                k: {"mode": v.mode, "remaining": v.remaining,
                    "field_name": v.field_name, "rename_to": v.rename_to,
                    "duration": v.duration}
                for k, v in self._rules.items()
            }

    def peek(self, target: str) -> ChaosRule | None:
        with self._lock:
            return self._rules.get(target)

    def consume(self, target: str):
        with self._lock:
            rule = self._rules.get(target)
            if rule is None:
                return
            rule.remaining -= 1
            if rule.remaining <= 0:
                del self._rules[target]

    def maybe_disrupt_before(self, target: str):
        """Call at the top of a route. May sleep or raise, simulating a
        failure before any real work happens."""
        rule = self.peek(target)
        if rule is None:
            return
        if rule.mode == "timeout":
            self.consume(target)
            time.sleep(rule.duration)
        elif rule.mode == "error_500":
            self.consume(target)
            raise RuntimeError("Simulated internal server error (chaos injection).")

    def mutate_data(self, rule: ChaosRule, data: dict) -> dict:
        """Pure mutation — does not consume the rule. Caller decides when
        to call consume(), typically once after applying to a whole response."""
        mutated = dict(data)
        if rule.field_name and rule.field_name in mutated:
            if rule.mode == "missing_field":
                del mutated[rule.field_name]
            elif rule.mode == "rename_field" and rule.rename_to:
                mutated[rule.rename_to] = mutated.pop(rule.field_name)
        return mutated


chaos_manager = ChaosManager()