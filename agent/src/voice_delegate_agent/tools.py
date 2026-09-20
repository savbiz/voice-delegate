"""Read-only worker tools with finite input and arithmetic complexity."""

import ast
import math
import operator
from collections.abc import Callable

from langchain_core.tools import tool

OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


@tool
def calculate(expression: str) -> str:
    """Calculate arithmetic using numbers, parentheses, +, -, * and / only."""
    if len(expression) > 160:
        return "Calculation rejected: expression too long."
    try:
        tree = ast.parse(expression, mode="eval")
        if len(list(ast.walk(tree))) > 40:
            raise ValueError

        def visit(node: ast.AST) -> float:
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, (int, float))
                and not isinstance(node.value, bool)
            ):
                value = float(node.value)
            elif isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
                value = OPERATORS[type(node.op)](visit(node.left), visit(node.right))
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
                value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
            else:
                raise ValueError
            if not math.isfinite(value) or abs(value) > 1e12:
                raise ValueError
            return value

        return f"{visit(tree.body):.12g}"
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
        return "Calculation rejected: use finite arithmetic within ±1e12, without powers or code."


@tool
def reference_lookup(topic: str) -> str:
    """Look up local project notes: architecture, limits, or delegation; no web search."""
    notes = {
        "architecture": (
            "WebRTC carries voice. FastAPI owns sessions. LangGraph runs delegated work."
        ),
        "limits": "Sessions, context, worker steps, task duration and spoken results are bounded.",
        "delegation": (
            "One delegation boundary keeps tools in the worker. Interruptions cancel work."
        ),
    }
    return notes.get(
        topic.strip().lower(), "No local note found. Try architecture, limits or delegation."
    )


TOOLS = [calculate, reference_lookup]
