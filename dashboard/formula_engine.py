from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from typing import Any, Callable


FIELD_PATTERN = re.compile(r"\[([^\]]+)\]")


class FormulaError(ValueError):
    """Raised when a formula cannot be validated or evaluated safely."""


def extract_fields(formula: str) -> list[str]:
    return FIELD_PATTERN.findall(str(formula))


def normalize_formula(formula: str) -> str:
    expr = str(formula)
    expr = re.sub(r"(?<![\w.])if\s*\(", "if_(", expr)
    return FIELD_PATTERN.sub(lambda match: f"FIELD({match.group(1)!r})", expr)


@dataclass
class FormulaContext:
    field_getter: Callable[[str], Any]
    range_sum_getter: Callable[[str, str], Any] | None = None


class SafeFormulaEvaluator(ast.NodeVisitor):
    allowed_functions = {
        "FIELD",
        "abs",
        "round",
        "sum",
        "mean",
        "min",
        "max",
        "count",
        "nunique",
        "safe_divide",
        "if_",
        "range_sum",
    }

    def __init__(self, context: FormulaContext):
        self.context = context

    def evaluate(self, formula: str) -> Any:
        expr = normalize_formula(formula)
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError as exc:
            raise FormulaError(f"公式语法错误：{exc.msg}") from exc
        return self.visit(tree.body)

    def visit_Constant(self, node: ast.Constant) -> Any:
        return node.value

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id in {"True", "False", "None"}:
            return {"True": True, "False": False, "None": None}[node.id]
        raise FormulaError(f"不允许的名称：{node.id}")

    def visit_Call(self, node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name):
            raise FormulaError("只允许调用白名单函数")
        func_name = node.func.id
        if func_name not in self.allowed_functions:
            raise FormulaError(f"不允许的函数：{func_name}")
        if node.keywords:
            raise FormulaError("公式函数暂不支持关键字参数")
        args = [self.visit(arg) for arg in node.args]
        return self._call(func_name, args)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.Not):
            return ~operand if hasattr(operand, "__invert__") else not operand
        raise FormulaError("不支持的单目运算")

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        left = self.visit(node.left)
        right = self.visit(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.FloorDiv):
            return left // right
        if isinstance(node.op, ast.Mod):
            return left % right
        if isinstance(node.op, ast.Pow):
            return left**right
        raise FormulaError("不支持的二元运算")

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        values = [self.visit(value) for value in node.values]
        result = values[0]
        for value in values[1:]:
            if isinstance(node.op, ast.And):
                result = result & value if hasattr(result, "__and__") else result and value
            elif isinstance(node.op, ast.Or):
                result = result | value if hasattr(result, "__or__") else result or value
            else:
                raise FormulaError("不支持的布尔运算")
        return result

    def visit_Compare(self, node: ast.Compare) -> Any:
        left = self.visit(node.left)
        result = None
        for op, comparator in zip(node.ops, node.comparators):
            right = self.visit(comparator)
            current = self._compare(left, right, op)
            result = current if result is None else result & current
            left = right
        return result

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        return self._if(self.visit(node.test), self.visit(node.body), self.visit(node.orelse))

    def generic_visit(self, node: ast.AST) -> Any:
        raise FormulaError(f"不支持的表达式：{node.__class__.__name__}")

    def _call(self, func_name: str, args: list[Any]) -> Any:
        if func_name == "FIELD":
            if len(args) != 1 or not isinstance(args[0], str):
                raise FormulaError("FIELD() 只能引用一个字段名")
            return self.context.field_getter(args[0])
        if func_name == "safe_divide":
            if len(args) != 2:
                raise FormulaError("safe_divide() 需要 2 个参数")
            return safe_divide(args[0], args[1])
        if func_name == "range_sum":
            if len(args) != 2 or not all(isinstance(arg, str) for arg in args):
                raise FormulaError("range_sum() 需要 2 个字段名参数")
            if self.context.range_sum_getter is None:
                raise FormulaError("当前上下文不支持 range_sum()")
            return self.context.range_sum_getter(args[0], args[1])
        if func_name == "if_":
            if len(args) != 3:
                raise FormulaError("if() 需要 3 个参数")
            return self._if(args[0], args[1], args[2])
        if func_name == "sum":
            return aggregate(args, "sum")
        if func_name == "mean":
            return aggregate(args, "mean")
        if func_name == "min":
            return aggregate(args, "min")
        if func_name == "max":
            return aggregate(args, "max")
        if func_name == "count":
            return aggregate(args, "count")
        if func_name == "nunique":
            return aggregate(args, "nunique")
        if func_name == "abs":
            if len(args) != 1:
                raise FormulaError("abs() 需要 1 个参数")
            return abs(args[0])
        if func_name == "round":
            if len(args) not in {1, 2}:
                raise FormulaError("round() 需要 1 或 2 个参数")
            return round(args[0], int(args[1])) if len(args) == 2 else round(args[0])
        raise FormulaError(f"不允许的函数：{func_name}")

    def _compare(self, left: Any, right: Any, op: ast.cmpop) -> Any:
        if isinstance(op, ast.Eq):
            return left == right
        if isinstance(op, ast.NotEq):
            return left != right
        if isinstance(op, ast.Lt):
            return left < right
        if isinstance(op, ast.LtE):
            return left <= right
        if isinstance(op, ast.Gt):
            return left > right
        if isinstance(op, ast.GtE):
            return left >= right
        raise FormulaError("不支持的比较运算")

    def _if(self, condition: Any, true_value: Any, false_value: Any) -> Any:
        if hasattr(condition, "where"):
            cond = condition.fillna(False).astype(bool) if hasattr(condition, "fillna") else condition
            true_is_series = hasattr(true_value, "where")
            false_is_series = hasattr(false_value, "where")
            if true_is_series:
                return true_value.where(cond, false_value)
            if false_is_series:
                return false_value.where(~cond, true_value)
            return cond.map(lambda item: true_value if item else false_value)
        return true_value if condition else false_value


def aggregate(args: list[Any], method: str) -> Any:
    if len(args) != 1:
        raise FormulaError(f"{method}() 需要 1 个参数")
    value = args[0]
    if hasattr(value, method):
        return getattr(value, method)()
    if method == "count":
        return 0 if value is None else 1
    if method == "nunique":
        return 0 if value is None else 1
    return value


def safe_divide(numerator: Any, denominator: Any) -> Any:
    if denominator is None:
        return None
    if hasattr(denominator, "replace"):
        cleaned = denominator.replace(0, math.nan)
        return numerator / cleaned
    try:
        if float(denominator) == 0:
            return None
    except (TypeError, ValueError):
        return None
    return numerator / denominator


def evaluate_formula(formula: str, context: FormulaContext) -> Any:
    return SafeFormulaEvaluator(context).evaluate(formula)
