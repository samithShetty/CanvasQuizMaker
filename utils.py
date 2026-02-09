import math
import random
import re
from typing import Any, Dict

# Helpers


def _to_number(v: Any):
    if isinstance(v, (int, float)):
        return v
    try:
        if isinstance(v, str) and v.isdigit():
            return int(v)
        return float(v)
    except Exception:
        return v


def _eval_expr(expr: str, context: Dict[str, Any]):
    """Evaluate an expression using context variables and math funcs.
    Returns (value, error_flag)
    """
    # allow both {{var}} and plain var references in expressions
    expr = re.sub(r"\{\{\s*(\w+)\s*\}\}", r"\1", expr)

    # build eval locals: math funcs + context vars (coerced when possible)
    locals_ = {k: getattr(math, k) for k in dir(math) if not k.startswith("__")}
    for k, v in context.items():
        locals_[k] = _to_number(v)

    try:
        # restrict builtins
        val = eval(expr, {"__builtins__": None}, locals_)
        return val, False
    except Exception:
        return "<err>", True


def generate_value(
    var_name: str, var_def: Dict[str, Any], current: Dict[str, Any]
) -> Any:
    """Generate a single variable value based on its rule."""
    t = var_def.get("rule_data", {}).get("type", "custom")
    try:
        if t == "random_number":
            mn = int(var_def["rule_data"].get("min", 1))
            mx = int(var_def["rule_data"].get("max", 10))
            step = int(var_def["rule_data"].get("step", 1))
            if step <= 1:
                return random.randint(mn, mx)
            choices = list(range(mn, mx + 1, step))
            return random.choice(choices) if choices else random.randint(mn, mx)

        if t == "random_choice":
            choices = var_def["rule_data"].get("choices", [])
            return random.choice(choices) if choices else ""

        if t == "math_expression":
            expr = var_def["rule_data"].get("expression", "")
            val, err = _eval_expr(expr, current)
            if err:
                return "<err>"
            return val

        # fallback
        return var_def.get("rule_data", {}).get("description", "")
    except Exception:
        return "<err>"


def generate_sample(variables: Dict[str, Any]) -> Dict[str, Any]:
    """Attempt to generate a consistent sample for all variables."""
    sample: Dict[str, Any] = {}
    for _ in range(5):
        for name, vdef in variables.items():
            if name in sample:
                continue
            val = generate_value(name, vdef, sample)
            if val == "<err>":
                continue
            sample[name] = val
    for name in variables:
        sample.setdefault(name, "?")
    return sample


def render_with_sample(text: str, sample: Dict[str, Any]) -> str:
    """Replace {{vars}} in text using sample mapping. Supports inline expressions.

    Examples:
      - {{num}} → variable lookup
      - {{ num * 2 }} → evaluated expression using sample values
    """

    def repl(m):
        token = m.group(1).strip()
        # exact var
        if token in sample:
            return str(sample[token])
        # try evaluating as expression
        val, err = _eval_expr(token, sample)
        if err:
            return f"{{{{{token}}}}}"
        return str(val)

    return re.sub(r"\{\{([^}]+)\}\}", repl, text)


def evaluate_expression(expr: str, sample: Dict[str, Any]) -> str:
    """Evaluate an answer-key expression using sample variables.

    - If the expression contains `{{ }}` tokens, we render them (supports inline expressions).
    - Otherwise we attempt to evaluate it as a plain expression (e.g., `num * 2`).

    Returns the stringified result or the original expression on error.
    """
    if not expr:
        return ""
    # if it contains template tokens, render (which also evaluates inline expressions)
    if "{{" in expr and "}}" in expr:
        return render_with_sample(expr, sample)

    val, err = _eval_expr(expr, sample)
    if err:
        return expr
    return str(val)
