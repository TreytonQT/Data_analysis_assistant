from __future__ import annotations

import argparse
import logging
import socket
import tempfile
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from follow_sell.server import create_app, program_root


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    home = program_root()
    temp_dir = home / 'work' / 'tmp'
    temp_dir.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(temp_dir)
    log_dir = home / 'work' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_dir / 'assistant.log', encoding='utf-8', level=logging.INFO)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', args.port))
        port = sock.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        app = create_app()
        server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False))
        app.state.shutdown = lambda: setattr(server, 'should_exit', True)

        def when_ready():
            for _ in range(60):
                try:
                    with urllib.request.urlopen(url + '/api/health', timeout=1) as response:
                        if response.status == 200:
                            if not args.no_browser:
                                webbrowser.open(url)
                            return
                except OSError:
                    time.sleep(0.25)

        threading.Thread(target=when_ready, daemon=True).start()
        server.run(sockets=[sock])


if __name__ == '__main__':
    main()
