"""Manual browser smoke check. Requires Chrome and websocket-client (from Jupyter).

Run while the inbox is running: python tests/smoke_inbox_browser.py
"""

import base64
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
import websocket


def main():
    profile = Path(tempfile.mkdtemp(prefix="email-inbox-browser-"))
    browser = Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe"
    process = subprocess.Popen([
        str(browser), "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--remote-debugging-port=9224",
        "--remote-allow-origins=http://localhost:9224", f"--user-data-dir={profile}", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW)
    connection = None
    try:
        with httpx.Client(trust_env=False) as client:
            for _ in range(60):
                try:
                    pages = client.get("http://127.0.0.1:9224/json").json()
                    break
                except httpx.HTTPError:
                    time.sleep(.25)
            else:
                raise RuntimeError("Chrome did not start")
            page = next(page for page in pages if page["type"] == "page")
            connection = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=15,
                                                       origin="http://localhost:9224")
            sequence = 0
            errors = []

            def command(method, params=None):
                nonlocal sequence
                sequence += 1
                connection.send(json.dumps({"id": sequence, "method": method, "params": params or {}}))
                while True:
                    message = json.loads(connection.recv())
                    if message.get("method") == "Runtime.exceptionThrown":
                        errors.append(message["params"])
                    if message.get("id") == sequence:
                        assert "error" not in message, message
                        return message.get("result", {})

            def evaluate(expression):
                result = command("Runtime.evaluate", {"expression": expression, "returnByValue": True})
                assert "exceptionDetails" not in result, result
                return result.get("result", {}).get("value")

            command("Runtime.enable")
            command("Page.enable")
            command("Network.enable")
            command("Network.setCacheDisabled", {"cacheDisabled": True})
            command("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000,
                                                            "deviceScaleFactor": 1, "mobile": False})
            command("Page.navigate", {"url": "http://127.0.0.1:8080"})
            for _ in range(60):
                if evaluate("document.querySelector('#connection')?.textContent.includes('Agent verbunden') && !!document.querySelector('.mail')"):
                    break
                time.sleep(.25)
            else:
                raise AssertionError("Inbox did not load an email")
            evaluate("document.querySelectorAll('.mail')[rows.findIndex(r=>r.values?.email_input)].click()")
            for _ in range(60):
                if evaluate("!!document.querySelector('#detail .card') && !!document.querySelector('a[href$=\"/input.yaml\"]')"):
                    break
                time.sleep(.25)
            else:
                print("Browser diagnostics:", evaluate("JSON.stringify({url:location.href,keys:typeof current==='undefined'?[]:Object.keys(current||{}),links:[...document.querySelectorAll('#detail a')].map(a=>a.getAttribute('href')),error:document.querySelector('#error')?.textContent})"))
                print("JavaScript exceptions:", errors)
                raise AssertionError("Email detail did not load")
            assert evaluate("document.querySelector('#error').hidden"), "API error displayed"
            assert evaluate("!!document.querySelector('a[href$=\"/input.yaml\"]')"), "YAML export missing"
            assert evaluate("!!document.querySelector('a[href$=\"/input.json\"]')"), "JSON export missing"
            assert not errors, errors
            screenshot = command("Page.captureScreenshot", {"format": "png"})
            output = Path(tempfile.gettempdir()) / "email-inbox-desktop.png"
            output.write_bytes(base64.b64decode(screenshot["data"]))
            command("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844,
                                                            "deviceScaleFactor": 1, "mobile": True})
            assert evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile horizontal overflow"
            print(f"Browser smoke check passed: list, detail, connected status, no JS errors, mobile width. Screenshot: {output}")
    finally:
        if connection:
            connection.close()
        process.terminate()
        process.wait(timeout=15)


if __name__ == "__main__":
    main()
