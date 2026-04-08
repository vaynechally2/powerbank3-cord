from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional
import re

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QDoubleSpinBox,
    QVBoxLayout,
    QWidget,
)

from config_manager import ConfigManager
from logger_manager import LoggerManager
from models import MonitoringProfile
from monitor import MonitorCallbacks, MonitorEngine


class SetupWizard(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("First-run setup")
        layout = QFormLayout(self)
        self.url = QLineEdit("https://example.com")
        self.rule = QLineEdit("Claim")
        self.interval = QDoubleSpinBox()
        self.interval.setRange(1.0, 3600.0)
        self.interval.setValue(5.0)
        self.offset = QDoubleSpinBox()
        self.offset.setRange(-5.0, 5.0)
        self.offset.setDecimals(2)
        self.offset.setValue(0.0)
        self.save_btn = QPushButton("Save profile")
        self.save_btn.clicked.connect(self.accept)

        layout.addRow("Target URL:", self.url)
        layout.addRow("Target text / selector:", self.rule)
        layout.addRow("Refresh interval (sec):", self.interval)
        layout.addRow("Clock offset sec (+ behind / - ahead):", self.offset)
        layout.addRow(self.save_btn)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Windows 11 Page Monitor (Safe Mode)")
        self.resize(1200, 800)

        self.config = ConfigManager()
        self.profiles, self.last_profile_name = self.config.load()
        self.profile = self._pick_profile(self.last_profile_name)
        self.logger = LoggerManager()
        self.engine: Optional[MonitorEngine] = None

        self._build_ui()
        self._apply_modern_theme()
        self._populate_profile(self.profile)
        self._setup_shortcut()

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._tick_clock)
        self.clock_timer.start(250)

        line = self.logger.log("APP_STARTED", "Application started", self.profile.clock_offset_seconds, self.profile.log_csv)
        self.append_log(line)

        if self.last_profile_name == "" and self.profiles:
            self._run_wizard()

    def _pick_profile(self, name: str) -> MonitoringProfile:
        for p in self.profiles:
            if p.name == name:
                return p
        return self.profiles[0]

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        top = QGridLayout()
        self.profile_box = QComboBox()
        self.profile_box.addItems([p.name for p in self.profiles])
        self.profile_box.currentTextChanged.connect(self.on_profile_changed)
        self.url_edit = QLineEdit()
        self.rule_mode = QComboBox()
        self.rule_mode.addItems(["text_contains", "text_exact", "css", "xpath", "attribute"])
        self.rule_value = QLineEdit()
        self.interval = QDoubleSpinBox()
        self.interval.setRange(1.0, 3600.0)
        self.schedule_mode = QComboBox()
        self.schedule_mode.addItems(["interval", "exact_time"])
        self.exact_time = QLineEdit("12:00:00")
        self.offset = QDoubleSpinBox()
        self.offset.setRange(-5.0, 5.0)
        self.offset.setDecimals(2)
        self.timeis_input = QLineEdit()
        self.timeis_parse_btn = QPushButton("Parse time.is text")
        self.timeis_parse_btn.clicked.connect(self.parse_timeis_text)

        top.addWidget(QLabel("Profile"), 0, 0)
        top.addWidget(self.profile_box, 0, 1)
        top.addWidget(QLabel("Target URL"), 0, 2)
        top.addWidget(self.url_edit, 0, 3)
        top.addWidget(QLabel("Rule mode"), 1, 0)
        top.addWidget(self.rule_mode, 1, 1)
        top.addWidget(QLabel("Rule value"), 1, 2)
        top.addWidget(self.rule_value, 1, 3)
        top.addWidget(QLabel("Refresh sec"), 2, 0)
        top.addWidget(self.interval, 2, 1)
        top.addWidget(QLabel("Schedule mode"), 2, 2)
        top.addWidget(self.schedule_mode, 2, 3)
        top.addWidget(QLabel("Exact refresh time (HH:MM:SS)"), 3, 0)
        top.addWidget(self.exact_time, 3, 1)
        top.addWidget(QLabel("Clock offset sec"), 3, 2)
        top.addWidget(self.offset, 3, 3)
        top.addWidget(QLabel("time.is text"), 4, 0)
        top.addWidget(self.timeis_input, 4, 1, 1, 2)
        top.addWidget(self.timeis_parse_btn, 4, 3)

        layout.addLayout(top)

        image_group = QGroupBox("Reference image detection")
        image_layout = QHBoxLayout(image_group)
        self.upload_image_btn = QPushButton("Upload Reference Image")
        self.upload_image_btn.clicked.connect(self.upload_image)
        self.image_mode = QComboBox()
        self.image_mode.addItems(["off", "image_only", "image_plus_text", "image_plus_selector"])
        self.confidence = QDoubleSpinBox()
        self.confidence.setRange(0.1, 1.0)
        self.confidence.setSingleStep(0.01)
        self.confidence.setValue(0.85)
        self.test_img_btn = QPushButton("Test Image Match")
        self.test_img_btn.clicked.connect(self.test_image_match)
        self.preview = QLabel("No image selected")
        self.preview.setFixedHeight(80)

        image_layout.addWidget(self.upload_image_btn)
        image_layout.addWidget(QLabel("Image mode"))
        image_layout.addWidget(self.image_mode)
        image_layout.addWidget(QLabel("Confidence"))
        image_layout.addWidget(self.confidence)
        image_layout.addWidget(self.test_img_btn)
        image_layout.addWidget(self.preview)
        layout.addWidget(image_group)

        active_group = QGroupBox("Active hours")
        active_layout = QHBoxLayout(active_group)
        self.active_days = QLineEdit("0,1,2,3,4,5,6")
        self.active_start = QLineEdit("00:00")
        self.active_end = QLineEdit("23:59")
        active_layout.addWidget(QLabel("Days (0=Mon)"))
        active_layout.addWidget(self.active_days)
        active_layout.addWidget(QLabel("Start"))
        active_layout.addWidget(self.active_start)
        active_layout.addWidget(QLabel("End"))
        active_layout.addWidget(self.active_end)
        layout.addWidget(active_group)

        alerts_group = QGroupBox("Alerts & manual confirm")
        alerts_layout = QHBoxLayout(alerts_group)
        self.alert_sound = QCheckBox("Play sound")
        self.alert_front = QCheckBox("Bring browser to front")
        self.alert_clip = QCheckBox("Copy text to clipboard")
        self.manual_confirm = QCheckBox("Require hotkey for click")
        self.hotkey = QLineEdit("Ctrl+Alt+C")
        alerts_layout.addWidget(self.alert_sound)
        alerts_layout.addWidget(self.alert_front)
        alerts_layout.addWidget(self.alert_clip)
        alerts_layout.addWidget(self.manual_confirm)
        alerts_layout.addWidget(QLabel("Hotkey"))
        alerts_layout.addWidget(self.hotkey)
        layout.addWidget(alerts_group)

        status_group = QGroupBox("Live status")
        status_layout = QGridLayout(status_group)
        self.status = QLabel("Idle")
        self.system_time = QLabel("-")
        self.corrected_time = QLabel("-")
        self.next_refresh = QLabel("-")
        self.last_refresh = QLabel("-")
        self.last_detection = QLabel("-")
        self.page_title = QLabel("-")
        self.connection = QLabel("Disconnected")

        rows = [
            ("Status", self.status),
            ("System time", self.system_time),
            ("Corrected time", self.corrected_time),
            ("Next refresh", self.next_refresh),
            ("Last refresh", self.last_refresh),
            ("Last detection", self.last_detection),
            ("Page title", self.page_title),
            ("Connection", self.connection),
        ]
        for i, (label, widget) in enumerate(rows):
            status_layout.addWidget(QLabel(label), i, 0)
            status_layout.addWidget(widget, i, 1)
        layout.addWidget(status_group)

        buttons = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.pause_btn = QPushButton("Pause")
        self.stop_btn = QPushButton("Stop")
        self.save_btn = QPushButton("Save Profile")
        self.test_btn = QPushButton("Test Detection")
        self.start_btn.clicked.connect(self.start_monitoring)
        self.pause_btn.clicked.connect(self.pause_monitoring)
        self.stop_btn.clicked.connect(self.stop_monitoring)
        self.save_btn.clicked.connect(self.save_profile)
        self.test_btn.clicked.connect(self.test_detection)
        for b in [self.start_btn, self.pause_btn, self.stop_btn, self.save_btn, self.test_btn]:
            buttons.addWidget(b)
        layout.addLayout(buttons)

        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setPlaceholderText("Live log output...")
        layout.addWidget(self.logs)

    def _apply_modern_theme(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background: #0f172a;
                color: #e2e8f0;
                font-family: 'Segoe UI';
                font-size: 13px;
            }
            QGroupBox {
                border: 1px solid #334155;
                border-radius: 10px;
                margin-top: 10px;
                padding: 10px;
                background: #111827;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                color: #93c5fd;
            }
            QLineEdit, QPlainTextEdit, QComboBox, QDoubleSpinBox {
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 6px;
                background: #0b1220;
            }
            QPushButton {
                border: 1px solid #2563eb;
                border-radius: 8px;
                padding: 7px 12px;
                background: #1d4ed8;
                color: white;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #2563eb;
            }
            QPushButton:pressed {
                background: #1e40af;
            }
            QCheckBox {
                spacing: 8px;
            }
            QLabel {
                color: #cbd5e1;
            }
            """
        )

    def _setup_shortcut(self) -> None:
        self.shortcut = QShortcut(QKeySequence(self.hotkey.text()), self)
        self.shortcut.activated.connect(self.manual_click_confirmed)

    def _run_wizard(self) -> None:
        wiz = SetupWizard(self)
        if wiz.exec():
            self.profile.target_url = wiz.url.text().strip()
            self.profile.detection.value = wiz.rule.text().strip()
            self.profile.refresh_interval_seconds = wiz.interval.value()
            self.profile.clock_offset_seconds = wiz.offset.value()
            self._populate_profile(self.profile)
            self.save_profile()

    def _populate_profile(self, p: MonitoringProfile) -> None:
        self.url_edit.setText(p.target_url)
        self.rule_mode.setCurrentText(p.detection.mode)
        self.rule_value.setText(p.detection.value)
        self.interval.setValue(p.refresh_interval_seconds)
        self.schedule_mode.setCurrentText(p.schedule_mode)
        self.exact_time.setText(p.exact_time_hms)
        self.offset.setValue(p.clock_offset_seconds)
        self.active_days.setText(",".join(str(d) for d in p.active_hours.days))
        self.active_start.setText(p.active_hours.start)
        self.active_end.setText(p.active_hours.end)
        self.alert_sound.setChecked(p.alerts.play_sound)
        self.alert_front.setChecked(p.alerts.bring_to_front)
        self.alert_clip.setChecked(p.alerts.copy_to_clipboard)
        self.manual_confirm.setChecked(p.alerts.manual_confirm_click)
        self.hotkey.setText(p.alerts.manual_hotkey)
        self.image_mode.setCurrentText(p.detection.image_mode)
        self.confidence.setValue(p.detection.confidence_threshold)
        if p.detection.reference_image_path and Path(p.detection.reference_image_path).exists():
            pix = QPixmap(p.detection.reference_image_path).scaledToHeight(72)
            self.preview.setPixmap(pix)

    def _read_profile_from_ui(self) -> MonitoringProfile:
        p = self.profile
        p.target_url = self.url_edit.text().strip()
        p.detection.mode = self.rule_mode.currentText()
        p.detection.value = self.rule_value.text().strip()
        p.refresh_interval_seconds = self.interval.value()
        p.schedule_mode = self.schedule_mode.currentText()
        p.exact_time_hms = self.exact_time.text().strip()
        p.clock_offset_seconds = self.offset.value()
        p.detection.image_mode = self.image_mode.currentText()
        p.detection.confidence_threshold = self.confidence.value()
        p.active_hours.days = [int(x.strip()) for x in self.active_days.text().split(",") if x.strip()]
        p.active_hours.start = self.active_start.text().strip()
        p.active_hours.end = self.active_end.text().strip()
        p.alerts.play_sound = self.alert_sound.isChecked()
        p.alerts.bring_to_front = self.alert_front.isChecked()
        p.alerts.copy_to_clipboard = self.alert_clip.isChecked()
        p.alerts.manual_confirm_click = self.manual_confirm.isChecked()
        p.alerts.manual_hotkey = self.hotkey.text().strip()
        return p

    def on_profile_changed(self, name: str) -> None:
        for p in self.profiles:
            if p.name == name:
                self.profile = p
                self._populate_profile(p)
                break

    def upload_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose image", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        self.profile.detection.reference_image_path = path
        pix = QPixmap(path).scaledToHeight(72)
        self.preview.setPixmap(pix)
        self.append_log(self.logger.log("IMAGE_SET", f"Reference image selected: {path}", self.profile.clock_offset_seconds))

    def append_log(self, line: str) -> None:
        self.logs.appendPlainText(line)

    def update_state(self, state: dict) -> None:
        self.system_time.setText(state.get("system_time", "-"))
        self.corrected_time.setText(state.get("corrected_time", "-"))
        self.next_refresh.setText(state.get("next_refresh", "-"))

    def start_monitoring(self) -> None:
        self.save_profile()
        if self.engine:
            QMessageBox.information(self, "Already running", "Monitoring is already running for this profile.")
            return

        callbacks = MonitorCallbacks(
            on_status=self.status.setText,
            on_log=self.append_log,
            on_detection=self.on_detection,
            on_state=self.update_state,
        )
        self.engine = MonitorEngine(self.profile, self.logger, callbacks)
        self.engine.start()
        self.connection.setText("Connected")

    def pause_monitoring(self) -> None:
        if self.engine:
            self.engine.pause()

    def stop_monitoring(self) -> None:
        if self.engine:
            self.engine.stop()
            self.engine = None
        self.connection.setText("Disconnected")
        self.status.setText("Stopped")

    def on_detection(self, message: str) -> None:
        self.last_detection.setText(datetime.now().strftime("%H:%M:%S"))
        self.status.setText(message)
        self.append_log(self.logger.log("ALERT", message, self.profile.clock_offset_seconds, self.profile.log_csv))
        if self.profile.alerts.play_sound:
            QGuiApplication.beep()
        if self.profile.alerts.copy_to_clipboard:
            QGuiApplication.clipboard().setText("Target detected")
        QMessageBox.information(self, "Target detected", message)

    def manual_click_confirmed(self) -> None:
        if not self.engine:
            return
        if not self.profile.alerts.manual_confirm_click:
            return
        ok = self.engine.confirm_click()
        if ok:
            self.append_log(self.logger.log("HOTKEY", "User-confirm hotkey pressed", self.profile.clock_offset_seconds))

    def test_detection(self) -> None:
        if not self.engine:
            QMessageBox.information(self, "Start required", "Start monitoring first, then use Test Detection.")
            return
        QMessageBox.information(self, "Detection test", self.engine.test_detection())

    def test_image_match(self) -> None:
        if not self.engine:
            QMessageBox.information(self, "Start required", "Start monitoring first, then use Test Image Match.")
            return
        result = self.engine.test_image_match()
        QMessageBox.information(self, "Image match", result)

    def save_profile(self) -> None:
        self.profile = self._read_profile_from_ui()
        self.config.save(self.profiles, self.profile.name)
        self.append_log(self.logger.log("PROFILE_SAVED", f"Profile saved: {self.profile.name}", self.profile.clock_offset_seconds))

    def parse_timeis_text(self) -> None:
        text = self.timeis_input.text().strip()
        ahead_match = re.search(r"([0-9]+(?:\\.[0-9]+)?)\\s*seconds?\\s*ahead", text, re.IGNORECASE)
        behind_match = re.search(r"([0-9]+(?:\\.[0-9]+)?)\\s*seconds?\\s*behind", text, re.IGNORECASE)
        acc_match = re.search(r"±\\s*([0-9]+(?:\\.[0-9]+)?)\\s*seconds?", text, re.IGNORECASE)

        if ahead_match:
            # If PC clock is ahead, correction should be negative.
            self.offset.setValue(-float(ahead_match.group(1)))
        elif behind_match:
            self.offset.setValue(float(behind_match.group(1)))

        if acc_match:
            self.profile.sync_accuracy_seconds = float(acc_match.group(1))

        self.append_log(
            self.logger.log(
                "TIME_SYNC_PARSED",
                (
                    f"Parsed time.is text. Offset now {self.offset.value():+.3f}s, "
                    f"sync accuracy ±{self.profile.sync_accuracy_seconds:.3f}s"
                ),
                self.offset.value(),
            )
        )

    def _tick_clock(self) -> None:
        self.system_time.setText(datetime.now().strftime("%H:%M:%S.%f")[:-3])
        corrected = datetime.now().timestamp() + self.offset.value()
        self.corrected_time.setText(datetime.fromtimestamp(corrected).strftime("%H:%M:%S.%f")[:-3])

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.stop_monitoring()
        self.append_log(self.logger.log("APP_CLOSED", "Application closed", self.profile.clock_offset_seconds, self.profile.log_csv))
        event.accept()
