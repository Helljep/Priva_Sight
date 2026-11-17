"""
common.py - shared plumbing for the evaluation scripts.

Starts (1) a static server for the synthetic sites, (2) the planner server,
and (3) Chromium with the PrivaSight extension loaded, then returns a handle
to the extension's harness page so scripts can call the REAL pipeline.
"""
import contextlib
import http.server
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from functools import partial
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / 'extension'
SITES = ROOT / 'testbed' / 'sites'
SERVER = ROOT / 'server'


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@contextlib.contextmanager
def static_server(port):
    handler = partial(QuietHandler, directory=str(SITES))
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f'http://127.0.0.1:{port}'
    finally:
        httpd.shutdown()


@contextlib.contextmanager
def planner_server(port, backend='scripted', extra_env=None):
    env = {**os.environ, 'PRIVASIGHT_BACKEND': backend, **(extra_env or {})}
    proc = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', str(port), '--log-level', 'warning'],
        cwd=SERVER, env=env)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=1)
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.25)
        else:
            raise RuntimeError('planner server did not start')
        yield f'http://127.0.0.1:{port}'
    finally:
        proc.terminate()


@contextlib.contextmanager
def browser_with_extension(headless=True):
    """Yield (context, harness_page). Extensions need a persistent context."""
    profile = tempfile.mkdtemp(prefix='privasight-profile-')
    with sync_playwright() as pw:
        args = [f'--disable-extensions-except={EXT}', f'--load-extension={EXT}', '--window-size=1100,860']
        if headless:
            args.append('--headless=new')
        ctx = pw.chromium.launch_persistent_context(
            profile, headless=False, args=args, no_viewport=True,
            ignore_default_args=['--disable-extensions'])
        worker = None
        for _ in range(40):
            workers = ctx.service_workers
            if workers:
                worker = workers[0]
                break
            time.sleep(0.25)
        if worker is None:
            worker = ctx.wait_for_event('serviceworker', timeout=10000)
        ext_id = worker.url.split('/')[2]
        harness = ctx.new_page()
        harness.goto(f'chrome-extension://{ext_id}/harness/harness.html')
        try:
            yield ctx, harness
        finally:
            ctx.close()
