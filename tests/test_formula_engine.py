import unittest

from dashboard.formula_engine import FormulaContext, FormulaError, evaluate_formula, extract_fields


class SimpleSeries(list):
    def sum(self):
        return sum(self)

    def mean(self):
        return sum(self) / len(self)

    def count(self):
        return len([item for item in self if item is not None])

    def nunique(self):
        return len(set(self))


class FormulaEngineTests(unittest.TestCase):
    def test_extract_fields(self):
        self.assertEqual(extract_fields("sum([销售额]) / sum([销量])"), ["销售额", "销量"])

    def test_aggregate_formula(self):
        data = {"销售额": SimpleSeries([10, 20]), "成本": SimpleSeries([3, 4])}
        context = FormulaContext(field_getter=lambda name: data[name])
        self.assertEqual(evaluate_formula("sum([销售额]) - sum([成本])", context), 23)

    def test_safe_divide_zero(self):
        data = {"销售额": SimpleSeries([10]), "目标": SimpleSeries([0])}
        context = FormulaContext(field_getter=lambda name: data[name])
        self.assertIsNone(evaluate_formula("safe_divide(sum([销售额]), sum([目标]))", context))

    def test_range_sum_uses_context_getter(self):
        context = FormulaContext(
            field_getter=lambda name: SimpleSeries([1]),
            range_sum_getter=lambda start, end: 60 if (start, end) == ("销售额--FBA销售额", "COD") else 0,
        )
        self.assertEqual(evaluate_formula('range_sum("销售额--FBA销售额", "COD")', context), 60)

    def test_blocks_unknown_function(self):
        context = FormulaContext(field_getter=lambda name: SimpleSeries([1]))
        with self.assertRaises(FormulaError):
            evaluate_formula("__import__('os')", context)


if __name__ == "__main__":
    unittest.main()
