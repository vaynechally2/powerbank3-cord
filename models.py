from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List


@dataclass
class DetectionRule:
    mode: str = "text_contains"  # text_contains, text_exact, css, xpath, attribute
    value: str = "Claim"
    case_sensitive: bool = False
    attribute_name: str = ""
    attribute_value: str = ""
    reference_image_path: str = ""
    confidence_threshold: float = 0.85
    image_mode: str = "off"  # off, image_only, image_plus_text, image_plus_selector


@dataclass
class ActiveHours:
    days: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])
    start: str = "00:00"
    end: str = "23:59"


@dataclass
class AlertSettings:
    desktop_notification: bool = True
    play_sound: bool = True
    bring_to_front: bool = False
    copy_to_clipboard: bool = False
    manual_hotkey: str = "Ctrl+Alt+C"
    manual_confirm_click: bool = False
    overlay_enabled: bool = True
    overlay_position: str = "top_left"
    overlay_opacity: float = 0.92
    overlay_show_profile: bool = True
    overlay_show_next_refresh: bool = True
    overlay_show_corrected_time: bool = True


@dataclass
class MonitoringProfile:
    name: str = "Default"
    target_url: str = "https://example.com"
    brave_path: str = ""
    refresh_interval_seconds: float = 5.0
    schedule_mode: str = "interval"  # interval, exact_time, hybrid
    exact_time_hms: str = "12:00:00:000"
    clock_offset_seconds: float = 0.0
    sync_accuracy_seconds: float = 0.0
    detection: DetectionRule = field(default_factory=DetectionRule)
    active_hours: ActiveHours = field(default_factory=ActiveHours)
    alerts: AlertSettings = field(default_factory=AlertSettings)
    cooldown_after_detection_seconds: float = 3.0
    startup_verification_refreshes: int = 3
    startup_verification_delay_ms: int = 350
    log_csv: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "MonitoringProfile":
        return MonitoringProfile(
            name=data.get("name", "Default"),
            target_url=data.get("target_url", "https://example.com"),
            brave_path=data.get("brave_path", ""),
            refresh_interval_seconds=float(data.get("refresh_interval_seconds", 5.0)),
            schedule_mode=data.get("schedule_mode", "interval"),
            exact_time_hms=data.get("exact_time_hms", "12:00:00:000"),
            clock_offset_seconds=float(data.get("clock_offset_seconds", 0.0)),
            sync_accuracy_seconds=float(data.get("sync_accuracy_seconds", 0.0)),
            detection=DetectionRule(**data.get("detection", {})),
            active_hours=ActiveHours(**data.get("active_hours", {})),
            alerts=AlertSettings(**data.get("alerts", {})),
            cooldown_after_detection_seconds=float(data.get("cooldown_after_detection_seconds", 3.0)),
            startup_verification_refreshes=int(data.get("startup_verification_refreshes", 3)),
            startup_verification_delay_ms=int(data.get("startup_verification_delay_ms", 350)),
            log_csv=bool(data.get("log_csv", True)),
        )
