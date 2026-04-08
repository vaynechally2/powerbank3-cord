from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Tuple

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from models import DetectionRule


class BraveController:
    def __init__(self) -> None:
        self._pw = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    @staticmethod
    def default_brave_path() -> str:
        local = os.environ.get("LOCALAPPDATA", "")
        return str(Path(local) / "BraveSoftware/Brave-Browser/Application/brave.exe")

    def start(self, url: str, brave_executable: Optional[str] = None) -> None:
        brave_path = brave_executable or self.default_brave_path()
        if not Path(brave_path).exists():
            raise FileNotFoundError("Brave was not found. Please check that Brave is installed.")

        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(executable_path=brave_path, headless=False)
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page.goto(url, wait_until="domcontentloaded", timeout=30000)

    def refresh(self) -> str:
        if not self.page:
            raise RuntimeError("Browser page is not connected.")
        self.page.reload(wait_until="domcontentloaded", timeout=30000)
        return self.page.title()

    def detect(self, rule: DetectionRule) -> Tuple[int, Optional[object]]:
        if not self.page:
            raise RuntimeError("Browser page is not connected.")

        locator = None
        if rule.mode == "css":
            locator = self.page.locator(rule.value)
        elif rule.mode == "xpath":
            locator = self.page.locator(f"xpath={rule.value}")
        elif rule.mode in {"text_contains", "text_exact"}:
            locator = self.page.get_by_text(rule.value, exact=(rule.mode == "text_exact"))
        elif rule.mode == "attribute":
            locator = self.page.locator(f"[{rule.attribute_name}='{rule.attribute_value}']")
        else:
            locator = self.page.get_by_text(rule.value)

        count = locator.count()
        element = locator.first if count > 0 else None

        if rule.image_mode != "off" and rule.reference_image_path:
            image_ok = self._image_match(rule)
            if rule.image_mode == "image_only":
                return (1 if image_ok else 0, element)
            if rule.image_mode in {"image_plus_text", "image_plus_selector"} and not image_ok:
                return 0, None
        return count, element

    def test_image_match(self, rule: DetectionRule, output_path: str = "logs/image_match_preview.png") -> Tuple[bool, str]:
        if not self.page:
            return False, "Browser is not connected."
        return self._image_match(rule, preview_path=output_path), output_path

    def _image_match(self, rule: DetectionRule, preview_path: str = "") -> bool:
        try:
            import cv2
            import numpy as np
        except Exception:
            return False

        if not self.page or not rule.reference_image_path:
            return False
        screenshot_bytes = self.page.screenshot(full_page=False)
        page_img = cv2.imdecode(np.frombuffer(screenshot_bytes, np.uint8), cv2.IMREAD_COLOR)
        tpl = cv2.imread(rule.reference_image_path, cv2.IMREAD_COLOR)
        if tpl is None or page_img is None:
            return False

        scales = [0.8, 0.9, 1.0, 1.1, 1.2]
        best_val = -1.0
        best_rect = None
        h, w = tpl.shape[:2]
        for scale in scales:
            resized = cv2.resize(tpl, (max(1, int(w * scale)), max(1, int(h * scale))))
            if resized.shape[0] > page_img.shape[0] or resized.shape[1] > page_img.shape[1]:
                continue
            res = cv2.matchTemplate(page_img, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val > best_val:
                best_val = max_val
                best_rect = (max_loc[0], max_loc[1], resized.shape[1], resized.shape[0])

        if preview_path and best_rect is not None:
            x, y, rw, rh = best_rect
            cv2.rectangle(page_img, (x, y), (x + rw, y + rh), (0, 255, 0), 3)
            Path(preview_path).parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(preview_path, page_img)

        return best_val >= rule.confidence_threshold

    def click_element(self, element: object) -> None:
        if element is not None:
            element.click(timeout=5000)

    def bring_to_front(self) -> None:
        if self.page:
            self.page.bring_to_front()

    def stop(self) -> None:
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self._pw:
            self._pw.stop()
        self.context = None
        self.browser = None
        self.page = None
        self._pw = None
