from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from backend.main import app
from backend.system_api import CONTROL_HEADER, CONTROL_HEADER_VALUE
from backend.system_control import system_controller


class FakeServer:
    def __init__(self) -> None:
        self.should_exit = False


class SystemApiTests(unittest.TestCase):
    def setUp(self) -> None:
        system_controller.reset_for_tests()
        self.client = TestClient(app, client=("127.0.0.1", 50100))
        self.headers = {CONTROL_HEADER: CONTROL_HEADER_VALUE}

    def tearDown(self) -> None:
        system_controller.reset_for_tests()

    def test_status_reports_unavailable_without_controlled_runner(self) -> None:
        response = self.client.get("/api/system/status", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["control_available"])
        self.assertIsNone(response.json()["pending_action"])

    def test_control_requests_require_special_header(self) -> None:
        response = self.client.post("/api/system/restart")

        self.assertEqual(response.status_code, 403)

    def test_control_requests_require_loopback_client(self) -> None:
        remote_client = TestClient(app, client=("10.0.0.8", 50100))

        response = remote_client.get("/api/system/status", headers=self.headers)

        self.assertEqual(response.status_code, 403)

    def test_restart_reserves_action_and_requests_graceful_exit(self) -> None:
        server = FakeServer()
        system_controller.bind(server)

        response = self.client.post("/api/system/restart", headers=self.headers)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["action"], "restart")
        self.assertTrue(server.should_exit)
        self.assertEqual(system_controller.status().pending_action, "restart")

    def test_shutdown_rejects_another_pending_action(self) -> None:
        server = FakeServer()
        system_controller.bind(server)
        self.assertEqual(self.client.post("/api/system/restart", headers=self.headers).status_code, 202)

        response = self.client.post("/api/system/shutdown", headers=self.headers)

        self.assertEqual(response.status_code, 409)

    def test_control_requests_are_unavailable_when_server_is_not_registered(self) -> None:
        response = self.client.post("/api/system/shutdown", headers=self.headers)

        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
