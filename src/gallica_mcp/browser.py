"""The bridge to the dedicated Chrome window.

Cloudflare blocks scripted HTTP clients on Gallica with a hard 403, also for the
home page. A Chrome tab on the same connection gets through. The tool therefore
sends no request itself. It attaches to a real Chrome window over the DevTools
protocol and runs `fetch()` inside a gallica.bnf.fr tab.

The window is the one that newspapers-mcp uses: the same port and the same
profile. Thus one window serves both tools, and whichever tool starts first
opens it.
"""

from __future__ import annotations

import base64
import itertools
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
from websockets.sync.client import connect

SITE_ORIGIN = "https://gallica.bnf.fr"
DEFAULT_DEBUG_PORT = 9333
DEBUG_PORT_ENV_VAR = "GALLICA_DEBUG_PORT"
PROFILE_DIR_ENV_VAR = "GALLICA_CHROME_PROFILE"
CHROME_BINARIES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
FETCH_TIMEOUT_SECONDS = 30
START_TIMEOUT_SECONDS = 45
_CHALLENGE_TITLE = re.compile(r"Just a moment|Attention Required", re.I)


class BrowserError(RuntimeError):
    """The Chrome window is absent, or it cannot reach the site."""


def debug_port() -> int:
    raw = os.environ.get(DEBUG_PORT_ENV_VAR) or os.environ.get("NEWSPAPERS_DEBUG_PORT")
    return int(raw) if raw else DEFAULT_DEBUG_PORT


def chrome_profile_dir() -> Path:
    """The Chrome profile of the shared window.

    Chrome refuses remote debugging on its default profile, so the window needs
    its own one. It is the newspapers-mcp profile, so both tools open the same
    window.
    """
    for name in (PROFILE_DIR_ENV_VAR, "NEWSPAPERS_CHROME_PROFILE"):
        if env_value := os.environ.get(name):
            return Path(env_value).expanduser()
    base = Path(os.environ.get("XDG_DATA_HOME") or "~/.local/share").expanduser()
    return base / "newspapers-mcp" / "chrome"


def _devtools_url(path: str) -> str:
    return f"http://127.0.0.1:{debug_port()}{path}"


def is_running() -> bool:
    try:
        httpx.get(_devtools_url("/json/version"), timeout=2).raise_for_status()
    except httpx.HTTPError:
        return False
    return True


def launch() -> str:
    """Start the dedicated Chrome window, or report that it already runs."""
    if is_running():
        return f"Chrome already runs on port {debug_port()}."

    binary = next((b for b in CHROME_BINARIES if shutil.which(b)), None)
    if binary is None:
        raise BrowserError(f"No Chrome binary found. Install one of: {', '.join(CHROME_BINARIES)}.")

    profile = chrome_profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            binary,
            f"--remote-debugging-port={debug_port()}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            f"{SITE_ORIGIN}/",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    while not is_running():
        if time.monotonic() > deadline:
            raise BrowserError(f"Chrome started, but DevTools does not answer on port {debug_port()}.")
        time.sleep(0.5)
    return (
        f"Chrome started on port {debug_port()} with profile {profile}.\n"
        "Keep the window open; you can minimise it."
    )


def _site_tab() -> dict:
    """The Gallica tab, ready for requests.

    Start the dedicated Chrome window if it is closed, and open a Gallica tab if
    the window has none. Wait until the page loads.
    """
    if not is_running():
        launch()

    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    opened_tab = False
    title = ""
    ready_once: str | None = None  # A fresh tab can report ready, then navigate again.
    while time.monotonic() < deadline:
        try:
            tabs = httpx.get(_devtools_url("/json/list"), timeout=5).json()
        except httpx.HTTPError:
            time.sleep(1)
            continue
        site_tabs = [t for t in tabs if t.get("type") == "page" and t.get("url", "").startswith(SITE_ORIGIN)]
        if not site_tabs and not opened_tab:
            httpx.put(_devtools_url(f"/json/new?{SITE_ORIGIN}/"), timeout=5)
            opened_tab = True
        for tab in site_tabs:
            title = tab.get("title", "")
            if _is_ready(tab) and not _CHALLENGE_TITLE.search(title):
                if ready_once == tab["id"] + tab.get("url", ""):
                    return tab
                ready_once = tab["id"] + tab.get("url", "")
                break
        else:
            ready_once = None
        time.sleep(1)

    if _CHALLENGE_TITLE.search(title):
        raise BrowserError(
            "The Gallica tab of the Chrome window shows a Cloudflare page. Tell the user to look at the window "
            "and complete the check if there is one, then run the command again one time."
        )
    raise BrowserError(
        f"No Gallica tab became ready on port {debug_port()} in {START_TIMEOUT_SECONDS} s. "
        "Tell the user to look at the Chrome window."
    )


def _is_ready(tab: dict) -> bool:
    try:
        with connect(tab["webSocketDebuggerUrl"], max_size=None, open_timeout=5) as ws:
            ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": "document.readyState", "returnByValue": True}}))
            while True:
                message = json.loads(ws.recv(timeout=5))
                if message.get("id") == 1:
                    return message.get("result", {}).get("result", {}).get("value") == "complete"
    except Exception:
        return False


class TabSession:
    """One DevTools connection to the Gallica tab."""

    def __init__(self) -> None:
        self._ws = connect(_site_tab()["webSocketDebuggerUrl"], max_size=None, open_timeout=10)
        self._ids = itertools.count(1)

    def close(self) -> None:
        self._ws.close()

    def evaluate(self, expression: str, timeout: float) -> Any:
        """Run JavaScript in the tab, await it, and return its JSON value."""
        request_id = next(self._ids)
        self._ws.send(json.dumps({
            "id": request_id,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "awaitPromise": True, "returnByValue": True},
        }))
        while True:
            message = json.loads(self._ws.recv(timeout=timeout))
            if message.get("id") == request_id:
                break
        if "error" in message:
            raise BrowserError(f"DevTools error: {message['error']}")
        result = message["result"]
        if "exceptionDetails" in result:
            description = result["exceptionDetails"].get("exception", {}).get("description", "")
            raise BrowserError(f"JavaScript failed in the Chrome tab: {description}")
        return result["result"].get("value")


# The body comes back as base64, so Python decodes it with the charset of the
# response. `response.text()` in the tab always decodes as UTF-8.
_FETCH_JS = """
(async () => {
  const response = await fetch(%s, {credentials: "include", signal: AbortSignal.timeout(%d)});
  const bytes = new Uint8Array(await response.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return {status: response.status, contentType: response.headers.get("content-type") || "", body: btoa(binary), url: response.url};
})()
"""


# One connection for each process: to find a ready tab costs more than a request.
_session: TabSession | None = None


def _close_session() -> None:
    global _session
    if _session is not None:
        try:
            _session.close()
        except Exception:
            pass
        _session = None


def _evaluate_with_retry(expression: str, timeout: float) -> Any:
    """Evaluate in the Gallica tab. Connect again one time if the connection
    closed, and retry one time if a navigation of the tab drops the request
    ("Failed to fetch")."""
    global _session
    for attempt in (1, 2):
        try:
            if _session is None:
                _session = TabSession()
            return _session.evaluate(expression, timeout)
        except BrowserError as error:
            if attempt == 2 or "Failed to fetch" not in str(error):
                raise
            time.sleep(3)
        except Exception:
            # A closed tab or a dropped socket: find the tab again.
            _close_session()
            if attempt == 2:
                raise


def get(url: str, params: dict[str, Any] | None = None, timeout: float = FETCH_TIMEOUT_SECONDS) -> httpx.Response:
    """Run one GET inside the Gallica tab and return it as an httpx response.

    A request that takes longer than `timeout` raises `httpx.ReadTimeout`, as
    the direct client did.
    """
    request = httpx.Request("GET", url, params=params)
    expression = _FETCH_JS % (json.dumps(str(request.url)), int(timeout * 1000))
    try:
        value = _evaluate_with_retry(expression, timeout + 10)
    except BrowserError as error:
        if "TimeoutError" in str(error) or "AbortError" in str(error):
            raise httpx.ReadTimeout(f"no answer in {timeout:.0f} s", request=request) from error
        raise
    return httpx.Response(
        value["status"],
        headers={"content-type": value["contentType"]},
        content=base64.b64decode(value["body"]),
        request=request,
    )
