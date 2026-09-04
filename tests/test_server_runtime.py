from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import server_runtime
from backend.system_control import system_controller


class FakeServer:
    def __init__(self, action: str | None = None) -> None:
        self.should_exit = False
        self.action = action

    def run(self) -> None:
        if self.action:
            system_controller.reserve(self.action)  # type: ignore[arg-type]
            system_controller.request_exit()


class ServerRuntimeTests(unittest.TestCase):
    def tearDown(self) -> None:
        system_controller.reset_for_tests()

    def test_pid_file_is_written_and_removed_only_for_its_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime_dir = Path(temporary)
            server_runtime.write_runtime_pid(12345, runtime_dir)
            self.assertEqual((runtime_dir / "dashboard.pid").read_text(encoding="ascii"), "12345\n")

            server_runtime.clear_runtime_pid(99999, runtime_dir)
            self.assertTrue((runtime_dir / "dashboard.pid").exists())
            server_runtime.clear_runtime_pid(12345, runtime_dir)
            self.assertFalse((runtime_dir / "dashboard.pid").exists())

    def test_restart_action_is_available_after_server_exits(self) -> None:
        server = FakeServer("restart")
        action = server_runtime.serve(server)

        self.assertEqual(action, "restart")
        self.assertTrue(server.should_exit)

    @patch("backend.server_runtime.subprocess.Popen")
    def test_relaunch_starts_a_detached_replacement(self, popen) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime_dir = Path(temporary) / "runtime"
            app_root = Path(temporary) / "app"
            app_root.mkdir()

            server_runtime.relaunch_process(runtime_dir, app_root)

        popen.assert_called_once()
        args, kwargs = popen.call_args
        self.assertIn("backend.server_runtime", args[0])
        self.assertEqual(kwargs["cwd"], str(app_root))
        self.assertEqual(kwargs["env"]["DATA_ANALYSIS_ASSISTANT_NO_BROWSER"], "1")


if __name__ == "__main__":
    unittest.main()
