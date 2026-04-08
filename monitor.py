from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from brave_controller import BraveController
from logger_manager import LoggerManager
from models import MonitoringProfile
from scheduler import RefreshScheduler


@dataclass
class MonitorCallbacks:
    on_status: Callable[[str], None]
    on_log: Callable[[str], None]
    on_detection: Callable[[str], None]
    on_state: Callable[[dict], None]


class MonitorEngine:
    def __init__(self, profile: MonitoringProfile, logger: LoggerManager, callbacks: MonitorCallbacks) -> None:
        self.profile = profile
        self.logger = logger
        self.callbacks = callbacks
        self.controller = BraveController()
        self.scheduler = RefreshScheduler(
            profile.refresh_interval_seconds,
            profile.clock_offset_seconds,
            profile.active_hours,
        )
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._last_found_element = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._pause_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        self._pause_event.set()
        line = self.logger.log("PAUSED", "Monitoring paused", self.profile.clock_offset_seconds, self.profile.log_csv)
        self.callbacks.on_log(line)
        self.callbacks.on_status("Paused")

    def resume(self) -> None:
        self._pause_event.clear()
        line = self.logger.log("RESUMED", "Monitoring resumed", self.profile.clock_offset_seconds, self.profile.log_csv)
        self.callbacks.on_log(line)
        self.callbacks.on_status("Running")

    def stop(self) -> None:
        self._stop_event.set()
        self._pause_event.clear()
        if self._thread:
            self._thread.join(timeout=2)
        self.controller.stop()

    def confirm_click(self) -> bool:
        if self._last_found_element is None:
            return False
        self.controller.click_element(self._last_found_element)
        line = self.logger.log("CLICK", "Click sent after manual confirmation", self.profile.clock_offset_seconds, self.profile.log_csv)
        self.callbacks.on_log(line)
        return True

    def test_detection(self) -> str:
        count, _ = self.controller.detect(self.profile.detection)
        return f"Detection result: {count} match(es)."

    def test_image_match(self) -> str:
        ok, preview_path = self.controller.test_image_match(self.profile.detection)
        if ok:
            return f"Image match succeeded. Preview saved: {preview_path}"
        return "No confident image match was found."

    def _run(self) -> None:
        try:
            self.controller.start(self.profile.target_url)
            line = self.logger.log("STARTED", "Monitoring started", self.profile.clock_offset_seconds, self.profile.log_csv)
            self.callbacks.on_log(line)
            self.callbacks.on_status("Running")

            error_count = 0
            while not self._stop_event.is_set():
                if self._pause_event.is_set():
                    time.sleep(0.2)
                    continue

                if not self.scheduler.in_active_hours():
                    self.callbacks.on_status("Outside active hours")
                    line = self.logger.log(
                        "ACTIVE_WINDOW_PAUSE",
                        "Monitoring paused because current time is outside your active hours.",
                        self.profile.clock_offset_seconds,
                        self.profile.log_csv,
                    )
                    self.callbacks.on_log(line)
                    time.sleep(2)
                    continue

                if self.profile.schedule_mode == "exact_time":
                    next_refresh = self.scheduler.next_exact_time_refresh(self.profile.exact_time_hms)
                elif self.profile.schedule_mode == "hybrid":
                    interval_next = self.scheduler.schedule_next()
                    exact_next = self.scheduler.next_exact_time_refresh(self.profile.exact_time_hms)
                    next_refresh = min(interval_next, exact_next)
                else:
                    next_refresh = self.scheduler.schedule_next()
                self.callbacks.on_state({
                    "next_refresh": next_refresh.strftime("%H:%M:%S.%f")[:-3],
                    "system_time": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                    "corrected_time": self.scheduler.corrected_now().strftime("%H:%M:%S.%f")[:-3],
                })

                delta = (next_refresh - self.scheduler.corrected_now()).total_seconds()
                sleep_time = max(0.05, delta)
                time.sleep(sleep_time)

                corrected_dispatch = self.scheduler.corrected_now()
                title = self.controller.refresh()
                delta_ms = int((corrected_dispatch - next_refresh).total_seconds() * 1000)
                if self.profile.schedule_mode in {"exact_time", "hybrid"}:
                    details = (
                        f"target={next_refresh.strftime('%H:%M:%S.%f')[:-3]} | "
                        f"dispatch={corrected_dispatch.strftime('%H:%M:%S.%f')[:-3]} | "
                        f"delta={delta_ms:+d}ms | title={title}"
                    )
                    line = self.logger.log("REFRESH_EXACT", details, self.profile.clock_offset_seconds, self.profile.log_csv)
                else:
                    line = self.logger.log("REFRESH", f"Page refreshed: {title}", self.profile.clock_offset_seconds, self.profile.log_csv)
                self.callbacks.on_log(line)

                count, element = self.controller.detect(self.profile.detection)
                if count > 0:
                    self._last_found_element = element
                    self.callbacks.on_detection(f"Target detected ({count} match(es))")
                    line = self.logger.log(
                        "DETECTED",
                        f"Rule matched {count} element(s)",
                        self.profile.clock_offset_seconds,
                        self.profile.log_csv,
                    )
                    self.callbacks.on_log(line)
                    if self.profile.alerts.bring_to_front:
                        self.controller.bring_to_front()
                    if self.profile.cooldown_after_detection_seconds > 0:
                        time.sleep(self.profile.cooldown_after_detection_seconds)
                else:
                    line = self.logger.log("NOT_FOUND", "Target not found", self.profile.clock_offset_seconds, self.profile.log_csv)
                    self.callbacks.on_log(line)
                error_count = 0

        except Exception as exc:
            line = self.logger.log("ERROR", str(exc), self.profile.clock_offset_seconds, self.profile.log_csv)
            self.callbacks.on_log(line)
            self.callbacks.on_status(str(exc))
            time.sleep(min(30, 2 ** min(5, 1)))
        finally:
            self.controller.stop()
            line = self.logger.log("STOPPED", "Monitoring stopped", self.profile.clock_offset_seconds, self.profile.log_csv)
            self.callbacks.on_log(line)
            self.callbacks.on_status("Stopped")
