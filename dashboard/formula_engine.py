from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable


FIELD_PATTERN = re.compile(r"\[([^\]]+)\]")

FUNCTION_ARITIES = {
    "FIELD": {1},
    "abs": {1},
    "round": {1, 2},
    "sum": {1},
    "mean": {1},
    "min": {1},
    "max": {1},
    "count": {1},
    "nunique": {1},
    "safe_divide": {2},
    "if_": {3},
    "range_sum": {2},
}


class FormulaError(ValueError):
    """Raised when a formula cannot be validated or evaluated safely."""


def extract_fields(formula: str) -> list[str]:
    return FIELD_PATTERN.findall(str(formula))


def extract_range_sums(formula: str) -> list[tuple[str, str]]:
    ranges: list[tuple[str, str]] = []
    tree = _parse_formula(str(formula))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "range_sum"
            and len(node.args) == 2
            and all(isinstance(arg, ast.Constant) and isinstance(arg.value, str) for arg in node.args)
        ):
            ranges.append((node.args[0].value, node.args[1].value))
    return ranges


def normalize_formula(formula: str) -> str:
    expr = str(formula)
    expr = re.sub(r"(?<![\w.])if\s*\(", "if_(", expr)
    return FIELD_PATTERN.sub(lambda match: f"FIELD({match.group(1)!r})", expr)


@dataclass
class FormulaContext:
    field_getter: Callable[[str], Any]
    range_sum_getter: Callable[[str, str], Any] | None = None


@lru_cache(maxsize=256)
def _parse_formula(formula: str) -> ast.Expression:
    expr = normalize_formula(formula)
    if not expr.strip():
        raise FormulaError("公式不能为空")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"公式语法错误：{exc.msg}") from exc
    FormulaValidator().visit(tree)
    return tree


class FormulaValidator(ast.NodeVisitor):
    """Validate formula structure without reading any business data."""

    def visit_Expression(self, node: ast.Expression) -> None:
        self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> None:
        if not isinstance(node.value, (str, int, float, bool, type(None))):
            raise FormulaError(f"不支持的常量：{type(node.value).__name__}")

    def visit_Name(self, node: ast.Name) -> None:
        if node.id not in {"True", "False", "None"}:
            raise FormulaError(f"不允许的名称：{node.id}")

    def visit_Call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Name):
            raise FormulaError("只允许调用白名单函数")
        func_name = node.func.id
        if func_name not in FUNCTION_ARITIES:
            raise FormulaError(f"不允许的函数：{func_name}")
        if node.keywords:
            raise FormulaError("公式函数暂不支持关键字参数")
        if len(node.args) not in FUNCTION_ARITIES[func_name]:
            expected = " 或 ".join(str(value) for value in sorted(FUNCTION_ARITIES[func_name]))
            display_name = "if" if func_name == "if_" else func_name
            raise FormulaError(f"{display_name}() 需要 {expected} 个参数")
        if func_name == "FIELD":
            if not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str) or not node.args[0].value.strip():
                raise FormulaError("FIELD() 只能引用一个非空字段名")
        if func_name == "range_sum":
            if not all(
                isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.strip()
                for arg in node.args
            ):
                raise FormulaError("range_sum() 需要 2 个非空字段名参数")
        for arg in node.args:
            self.visit(arg)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        if not isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
            raise FormulaError("不支持的单目运算")
        self.visit(node.operand)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)):
            raise FormulaError("不支持的二元运算")
        self.visit(node.left)
        self.visit(node.right)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        if not isinstance(node.op, (ast.And, ast.Or)):
            raise FormulaError("不支持的布尔运算")
        for value in node.values:
            self.visit(value)

    def visit_Compare(self, node: ast.Compare) -> None:
        if not all(isinstance(op, (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)) for op in node.ops):
            raise FormulaError("不支持的比较运算")
        self.visit(node.left)
        for comparator in node.comparators:
            self.visit(comparator)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.visit(node.test)
        self.visit(node.body)
        self.visit(node.orelse)

    def generic_visit(self, node: ast.AST) -> None:
        raise FormulaError(f"不支持的表达式：{node.__class__.__name__}")


def validate_formula(formula: str) -> None:
    """Compile and validate a formula without evaluating fields or ranges."""

    _parse_formula(formula)


class SafeFormulaEvaluator(ast.NodeVisitor):
    allowed_functions = set(FUNCTION_ARITIES)

    def __init__(self, context: FormulaContext):
        self.context = context

    def evaluate(self, formula: str) -> Any:
        tree = _parse_formula(formula)
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
        if func_name == "if_":
            condition = self.visit(node.args[0])
            return self._visit_conditional(condition, node.args[1], node.args[2])
        args = [self.visit(arg) for arg in node.args]
        return self._call(func_name, args)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.Not):
            return ~operand if self._is_vector(operand) else not operand
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
        result = self.visit(node.values[0])
        for value_node in node.values[1:]:
            if isinstance(node.op, ast.And):
                if not self._is_vector(result) and not bool(result):
                    return result
                value = self.visit(value_node)
                result = result & value if self._is_vector(result) else value
            elif isinstance(node.op, ast.Or):
                if not self._is_vector(result) and bool(result):
                    return result
                value = self.visit(value_node)
                result = result | value if self._is_vector(result) else value
            else:
                raise FormulaError("不支持的布尔运算")
        return result

    def visit_Compare(self, node: ast.Compare) -> Any:
        left = self.visit(node.left)
        result = None
        for op, comparator in zip(node.ops, node.comparators):
            if result is not None and not self._is_vector(result) and not bool(result):
                return result
            right = self.visit(comparator)
            current = self._compare(left, right, op)
            result = current if result is None else result & current
            left = right
        return result

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        condition = self.visit(node.test)
        return self._visit_conditional(condition, node.body, node.orelse)

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

    def _visit_conditional(self, condition: Any, true_node: ast.AST, false_node: ast.AST) -> Any:
        if not self._is_vector(condition):
            return self.visit(true_node) if bool(condition) else self.visit(false_node)

        cond = condition.fillna(False).astype(bool) if hasattr(condition, "fillna") else condition
        if hasattr(cond, "all") and bool(cond.all()):
            return self.visit(true_node)
        if hasattr(cond, "any") and not bool(cond.any()):
            return self.visit(false_node)
        return self._if(cond, self.visit(true_node), self.visit(false_node))

    @staticmethod
    def _is_vector(value: Any) -> bool:
        return hasattr(value, "where") or (
            hasattr(value, "shape") and getattr(value, "shape", ()) not in {(), None}
        )


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
