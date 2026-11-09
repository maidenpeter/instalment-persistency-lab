"""Capture README screenshots and the walkthrough GIF from a running local app.

Usage (app running on port 8601):  python scripts/capture.py
Drives headless Chrome over the DevTools protocol and waits for Streamlit to finish each run.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "screenshots"
BASE = "http://localhost:8601/"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
WIDTH = 1440
PAGES = [
    ("0_home", ""),
    ("1_the_problem", "the-problem"),
    ("2_persistency_explorer", "persistency-explorer"),
    ("3_anti_selection_and_leakage", "anti-selection-and-leakage"),
    ("4_early_warning_model", "early-warning-model"),
    ("5_product_levers_simulator", "product-levers-simulator"),
    ("6_methods_and_assumptions", "methods-and-assumptions"),
]


class CDP:
    def __init__(self, ws):
        self.ws, self.i = ws, 0

    async def call(self, method, **params):
        self.i += 1
        my = self.i
        await self.ws.send(json.dumps({"id": my, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == my:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    async def js(self, expr):
        r = await self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")


async def wait_idle(cdp, timeout=120):
    """Wait until Streamlit has stopped running and the page height is stable."""
    t0, stable, last = time.time(), 0, None
    await asyncio.sleep(3)
    while time.time() - t0 < timeout:
        running = await cdp.js("!!document.querySelector('[data-testid=\"stStatusWidget\"]')")
        h = await cdp.js("(document.querySelector('[data-testid=\"stMainBlockContainer\"]')||document.body).scrollHeight")
        stable = stable + 1 if (not running and h == last) else 0
        last = h
        if stable >= 3:
            return h
        await asyncio.sleep(1)
    return last


async def shoot(cdp, height, path=None, clip_y=0, clip_h=None):
    await cdp.call("Emulation.setDeviceMetricsOverride", width=WIDTH, height=int(height), deviceScaleFactor=1, mobile=False)
    await asyncio.sleep(1.5)
    params = {"format": "png"}
    if clip_h:
        params["clip"] = {"x": 0, "y": clip_y, "width": WIDTH, "height": clip_h, "scale": 1}
    data = base64.b64decode((await cdp.call("Page.captureScreenshot", **params))["data"])
    if path:
        Path(path).write_bytes(data)
    return Image.open(io.BytesIO(data)).convert("RGB")


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    port = 9333
    ud = tempfile.mkdtemp()
    proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--remote-debugging-port={port}",
                             f"--user-data-dir={ud}", f"--window-size={WIDTH},1000", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json").read())
                ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.3)
        async with websockets.connect(ws_url, max_size=2**28) as ws:
            cdp = CDP(ws)
            await cdp.call("Page.enable")
            frames = []
            for name, path in PAGES:
                await cdp.call("Emulation.setDeviceMetricsOverride", width=WIDTH, height=4200, deviceScaleFactor=1, mobile=False)
                t0 = time.time()
                await cdp.call("Page.navigate", url=BASE + path)
                h = await wait_idle(cdp)
                ready = time.time() - t0 - 3  # wait_idle confirms idle over 3 extra seconds
                errors = await cdp.js("document.querySelectorAll('[data-testid=stException]').length")
                full = await shoot(cdp, h + 140, OUT / f"{name}.png")
                print(f"{name:32s} ready in about {ready:4.1f}s  errors={errors}  size={full.size}")
                # walkthrough frames: top of page, then two further sections where the page is long
                for y in [0, 900, 1800]:
                    if y == 0 or y + 600 < full.size[1]:
                        frames.append(full.crop((0, y, WIDTH, min(y + 900, full.size[1]))))
            # GIF: about 5 seconds per frame, scaled to 960 wide
            small = []
            for f in frames:
                canvas = Image.new("RGB", (WIDTH, 900), (249, 249, 247))
                canvas.paste(f, (0, 0))
                small.append(canvas.resize((960, 600), Image.LANCZOS).quantize(colors=128, method=Image.Quantize.MEDIANCUT))
            gif = ROOT / "assets" / "walkthrough.gif"
            small[0].save(gif, save_all=True, append_images=small[1:], duration=5000, loop=0, optimize=True)
            print("gif frames", len(small), "seconds", 5 * len(small), gif.stat().st_size // 1024, "KB")
    finally:
        proc.terminate()


if __name__ == "__main__":
    asyncio.run(main())
