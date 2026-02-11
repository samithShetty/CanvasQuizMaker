import math
import random
import re
from itertools import product
from typing import Any, Dict

# Helpers


def _to_number(v: Any):
    if isinstance(v, (int, float)):
        return v
    try:
        if isinstance(v, str):
            s = v.strip()
            # support binary/hex/octal with 0b/0x/0o prefixes and plain ints
            try:
                return int(s, 0)
            except Exception:
                pass
            # fallback to float
            return float(s)
    except Exception:
        return v


def _eval_expr(expr: str, context: Dict[str, Any]):
    """Evaluate an expression using context variables and math funcs.
    Returns (value, error_flag)
    """
    # build eval locals: math funcs + context vars (coerced when possible)
    locals_ = {k: getattr(math, k) for k in dir(math) if not k.startswith("__")}
    for k, v in context.items():
        locals_[k] = _to_number(v)

    # Expose a small set of safe Python helpers for conversions and simple ops
    safe_builtins = {
        "int": int,
        "float": float,
        "str": str,
        "bin": bin,
        "hex": hex,
        "oct": oct,
        "round": round,
        "abs": abs,
        "pow": pow,
        "sum": sum,
        "min": min,
        "max": max,
        "len": len,
        "sorted": sorted,
        "range": range,
        "list": list,
        "tuple": tuple,
        "dict": dict,
    }
    locals_.update(safe_builtins)

    # Helper to select a value from a mapping based on a key.
    def select(key, mapping, default=None):
        """Select value by key from a dict or iterable of pairs.

        Examples:
          select(var, {'f':'t0','g':'t1'}, 'default')
          select(var, [('f','t0'),('g','t1')], 'default')
        """
        if mapping is None:
            return default
        if isinstance(mapping, dict):
            return mapping.get(key, default)
        try:
            for k, v in mapping:
                if k == key:
                    return v
        except Exception:
            pass
        return default

    # expose select
    locals_["select"] = select
    locals_["case"] = select

    try:
        # restrict builtins but allow the small set we injected in locals_
        val = eval(expr, {"__builtins__": {}}, locals_)
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

        if t == "custom":
            desc = var_def.get("rule_data", {}).get("description", "")
            # Try to evaluate as an expression (e.g., select(...) or {{...}})
            if "{{" in desc and "}}" in desc:
                # Use render_with_sample to handle {{...}} templates
                rendered = render_with_sample(desc, current)
                return rendered
            else:
                # Try plain evaluation
                val, err = _eval_expr(desc, current)
                if not err:
                    return val
            # If eval fails, return the plaintext description
            return desc

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


def generate_all_combinations(variables: Dict[str, Any]) -> list:
    """Generate all possible combinations for random choice variables.

    For each random_choice variable, include all possible choices.
    For other variables, use generate_sample to get one value.
    Returns a list of all possible sample combinations.
    """
    # Identify random choice variables and their options
    choice_vars = {}
    other_vars = {}

    for name, vdef in variables.items():
        if vdef.get("rule_data", {}).get("type") == "random_choice":
            choices = vdef.get("rule_data", {}).get("choices", [])
            choice_vars[name] = choices
        else:
            other_vars[name] = vdef

    if not choice_vars:
        # If no random choice variables, just generate one sample
        return [generate_sample(variables)]

    # Get all combinations of choice variables
    choice_names = list(choice_vars.keys())
    choice_lists = [choice_vars[name] for name in choice_names]

    all_samples = []
    for combo in product(*choice_lists):
        sample = {}
        # Add the choice values
        for i, name in enumerate(choice_names):
            sample[name] = combo[i]

        # For other variables, generate values based on what we have so far
        for name, vdef in other_vars.items():
            val = generate_value(name, vdef, sample)
            if val != "<err>":
                sample[name] = val
            else:
                sample[name] = "?"

        all_samples.append(sample)

    return all_samples


def format_text(text: str) -> str:
    """Convert markdown-style formatting to HTML.

    Supports:
      - **text** or __text__ → <strong>text</strong>
      - *text* or _text_ → <em>text</em>
      - ~~text~~ → <s>text</s> (strikethrough)
      - ==text== → <mark>text</mark> (highlight)
      - HTML tags are passed through as-is

    Order matters: apply in order to avoid double-processing.
    """
    if not text:
        return text

    # Strikethrough: ~~text~~
    text = re.sub(r"~~([^~]+)~~", r"<s>\1</s>", text)

    # Highlight: ==text==
    text = re.sub(r"==([^=]+)==", r"<mark>\1</mark>", text)

    # Bold: **text** or __text__
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", text)

    # Italic: *text* or _text_ (but not __text__ which is bold, and not inside **text**)
    # Use negative lookbehind/lookahead to avoid matching bold markers
    text = re.sub(r"(?<!\*)\*(?!\*)([^*]+?)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"(?<!_)_(?!_)([^_]+?)_(?!_)", r"<em>\1</em>", text)

    return text


def render_with_sample(text: str, sample: Dict[str, Any]) -> str:
    """Replace {{vars}} in text using sample mapping. Supports inline expressions.

    Examples:
      - {{num}} → variable lookup
      - {{ num * 2 }} → evaluated expression using sample values

    Also supports markdown formatting: **bold**, *italic*, ~~strike~~, ==highlight==
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

    rendered = re.sub(r"\{\{(.*?)\}\}", repl, text)
    # Apply formatting after variable substitution
    return format_text(rendered)


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
