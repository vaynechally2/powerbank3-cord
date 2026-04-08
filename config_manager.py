from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from models import MonitoringProfile


class ConfigManager:
    def __init__(self, settings_path: str = "settings.json") -> None:
        self.settings_path = Path(settings_path)
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Tuple[List[MonitoringProfile], str]:
        if not self.settings_path.exists():
            default_profile = MonitoringProfile(name="Sample Profile")
            self.save([default_profile], default_profile.name)
            return [default_profile], default_profile.name

        raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
        profiles = [MonitoringProfile.from_dict(p) for p in raw.get("profiles", [])]
        if not profiles:
            profiles = [MonitoringProfile(name="Sample Profile")]
        last_profile = raw.get("last_profile", profiles[0].name)
        return profiles, last_profile

    def save(self, profiles: List[MonitoringProfile], last_profile: str) -> None:
        payload: Dict[str, object] = {
            "profiles": [p.to_dict() for p in profiles],
            "last_profile": last_profile,
            "telemetry_enabled": False,
        }
        self.settings_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
