from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


class LoggerManager:
    def __init__(self, logs_dir: str = "logs") -> None:
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.text_path = self.logs_dir / f"monitor_{stamp}.log"
        self.csv_path = self.logs_dir / f"monitor_{stamp}.csv"
        self._csv_initialized = False

    def _corrected(self, offset_seconds: float) -> datetime:
        return datetime.now() + timedelta(seconds=offset_seconds)

    def log(self, event_type: str, details: str, offset_seconds: float = 0.0, write_csv: bool = True) -> str:
        now = datetime.now()
        corrected = self._corrected(offset_seconds)
        line = (
            f"{now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} | "
            f"corrected={corrected.strftime('%H:%M:%S.%f')[:-3]} | {event_type} | {details}"
        )
        with self.text_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

        if write_csv:
            self._write_csv(now, corrected, event_type, details)
        return line

    def _write_csv(self, now: datetime, corrected: datetime, event_type: str, details: str) -> None:
        create_header = not self._csv_initialized and not self.csv_path.exists()
        with self.csv_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if create_header:
                writer.writerow(["timestamp", "corrected_time", "event_type", "details"])
            writer.writerow([
                now.isoformat(timespec="milliseconds"),
                corrected.isoformat(timespec="milliseconds"),
                event_type,
                details,
            ])
        self._csv_initialized = True
