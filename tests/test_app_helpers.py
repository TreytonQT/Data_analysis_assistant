import unittest

from dashboard.display import SIDEBAR_BANNER_PATH, month_label


class AppHelperTests(unittest.TestCase):
    def test_month_label_formats_short_chinese_month(self):
        self.assertEqual(month_label("2026-01"), "26年1月")
        self.assertEqual(month_label("2026-04"), "26年4月")

    def test_sidebar_banner_path_points_to_assets_png(self):
        self.assertEqual(SIDEBAR_BANNER_PATH.name, "sidebar-dashboard-banner.png")
        self.assertEqual(SIDEBAR_BANNER_PATH.parent.name, "assets")


if __name__ == "__main__":
    unittest.main()
