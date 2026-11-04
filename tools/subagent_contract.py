"""Small deterministic child prompt and answer contracts owned by the harness."""

from decimal import Decimal, InvalidOperation

ROLE_SYSTEM = {
    'coding': ('You are a coding child agent. Complete only the assigned task. '
               'Give the final result directly; do not discuss the agent system or tools.'),
    'research': ('You are a research child agent. Use only evidence supplied in the task. '
                 'Give a concise answer, and say when the evidence is insufficient.'),
}


def child_system_prompt(agent_type: str) -> str:
    try:
        return ROLE_SYSTEM[agent_type]
    except KeyError as exc:
        raise ValueError(f'unknown child agent type: {agent_type}') from exc


def canonical_integer_answer(text: str) -> str | None:
    """Accept numeric formatting variants only when they are exactly an integer."""
    try:
        value = Decimal(text.strip())
    except (AttributeError, InvalidOperation):
        return None
    return str(int(value)) if value.is_finite() and value == value.to_integral_value() else None


def canonical_final_line(text: str) -> str | None:
    """Read a numeric final line while preserving exact-format compliance separately."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return canonical_integer_answer(lines[-1]) if lines else None
