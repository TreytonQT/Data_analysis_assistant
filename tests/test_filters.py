import unittest

import pandas as pd

from dashboard.filters import apply_home_filters


class FilterTests(unittest.TestCase):
    def test_apply_home_filters_filters_all_dimensions(self):
        data = pd.DataFrame(
            {
                "月份": ["2026-01", "2026-02", "2026-02"],
                "销售专员": ["A", "A", "B"],
                "部门": ["D1", "D2", "D1"],
                "店铺类型": ["本土", "中企", "本土"],
                "销售额": [1, 2, 3],
            }
        )

        filtered = apply_home_filters(data, ["2026-02"], ["B"], ["D1"], ["本土"])

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]["销售额"], 3)

    def test_empty_selection_returns_empty(self):
        data = pd.DataFrame({"月份": ["2026-01"], "销售专员": ["A"], "部门": ["D1"], "店铺类型": ["本土"]})

        filtered = apply_home_filters(data, [], ["A"], ["D1"], ["本土"])

        self.assertTrue(filtered.empty)


if __name__ == "__main__":
    unittest.main()
