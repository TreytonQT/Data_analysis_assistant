from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app


class AppRevisionsApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_returns_domain_scoped_revisions(self):
        with (
            patch("backend.app_revisions.dashboard_revision", return_value="dashboard-v1"),
            patch("backend.app_revisions.promotion_revision", return_value="promotions-v1"),
            patch("backend.app_revisions.reports_revision", return_value="reports-v1"),
            patch("backend.app_revisions.config_revision", return_value="configs-v1"),
            patch("backend.app_revisions.batch_monitor_revision", return_value="batch-monitor-v1"),
        ):
            response = self.client.get("/api/app-revisions")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "dashboard": "dashboard-v1",
                "promotions": "promotions-v1",
                "reports": "reports-v1",
                "configs": "configs-v1",
                "batch_monitor": "batch-monitor-v1",
            },
        )
