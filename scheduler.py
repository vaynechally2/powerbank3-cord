from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from models import ActiveHours


class RefreshScheduler:
    def __init__(self, interval_seconds: float, offset_seconds: float, active_hours: ActiveHours) -> None:
        self.interval_seconds = max(1.0, interval_seconds)
        self.offset_seconds = offset_seconds
        self.active_hours = active_hours
        self._next_refresh: Optional[datetime] = None

    def corrected_now(self) -> datetime:
        return datetime.now() + timedelta(seconds=self.offset_seconds)

    def in_active_hours(self) -> bool:
        now = self.corrected_now()
        if now.weekday() not in self.active_hours.days:
            return False
        start_h, start_m = [int(x) for x in self.active_hours.start.split(":")]
        end_h, end_m = [int(x) for x in self.active_hours.end.split(":")]
        start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        end = now.replace(hour=end_h, minute=end_m, second=59, microsecond=999999)
        if start <= end:
            return start <= now <= end
        return now >= start or now <= end

    def schedule_next(self) -> datetime:
        now = self.corrected_now()
        self._next_refresh = now + timedelta(seconds=self.interval_seconds)
        return self._next_refresh

    def next_refresh(self) -> Optional[datetime]:
        return self._next_refresh

    def next_exact_time_refresh(self, hms: str) -> datetime:
        now = self.corrected_now()
        hh, mm, ss = [int(x) for x in hms.split(":")]
        target = now.replace(hour=hh, minute=mm, second=ss, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        self._next_refresh = target
        return target
