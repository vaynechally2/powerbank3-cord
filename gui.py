from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional
import re

from PySide6.QtCore import QTimer, Qt, QPoint
from PySide6.QtGui import QGuiApplication, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
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
    QSlider,
    QPushButton,
    QPlainTextEdit,
    QTextEdit,
    QDoubleSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from config_manager import ConfigManager
from logger_manager import LoggerManager
from models import MonitoringProfile
from monitor import MonitorCallbacks, MonitorEngine
from scheduler import RefreshScheduler


class StatusOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Monitor Overlay")
        self._drag_pos: Optional[QPoint] = None
        self.label = QLabel("RUNNING", self)
        self.label.setStyleSheet("color: white; font-size: 13px; font-weight: 600;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.addWidget(self.label)
        self.resize(300, 90)
        self.setStyleSheet("background:#16a34a; border-radius:12px;")

    def update_text(self, text: str, state: str = "running") -> None:
        colors = {
            "running": "#16a34a",
            "paused": "#d97706",
            "error": "#dc2626",
            "detected": "#2563eb",
        }
        self.setStyleSheet(f"background:{colors.get(state, '#16a34a')}; border-radius:12px;")
        self.label.setText(text)

    def mousePressEvent(self, event):  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):  # type: ignore[override]
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):  # type: ignore[override]
        self._drag_pos = None


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
        self.overlay = StatusOverlay()
        self.last_state: dict = {}

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
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)
        left_panel = QWidget()
        right_panel = QWidget()
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([780, 420])

        left = QVBoxLayout(left_panel)
        right = QVBoxLayout(right_panel)

        profile_group = QGroupBox("Profile")
        profile_grid = QGridLayout(profile_group)
        self.profile_box = QComboBox()
        self.profile_box.addItems([p.name for p in self.profiles])
        self.profile_box.currentTextChanged.connect(self.on_profile_changed)
        profile_grid.addWidget(QLabel("Profile"), 0, 0)
        profile_grid.addWidget(self.profile_box, 0, 1, 1, 3)
        left.addWidget(profile_group)

        target_group = QGroupBox("Target")
        top = QGridLayout(target_group)
        self.brave_path = QLineEdit()
        self.brave_browse_btn = QPushButton("Browse Brave")
        self.brave_browse_btn.clicked.connect(self.choose_brave_path)
        self.url_edit = QLineEdit()
        self.rule_mode = QComboBox()
        self.rule_mode.addItems(["text_contains", "text_exact", "css", "xpath", "attribute"])
        self.rule_value = QLineEdit()
        top.addWidget(QLabel("Brave executable"), 0, 0)
        top.addWidget(self.brave_path, 0, 1, 1, 2)
        top.addWidget(self.brave_browse_btn, 0, 3)
        top.addWidget(QLabel("Page to monitor"), 1, 0)
        top.addWidget(self.url_edit, 1, 1, 1, 3)
        top.addWidget(QLabel("How to detect the target"), 2, 0)
        top.addWidget(self.rule_mode, 2, 1)
        top.addWidget(QLabel("Selector / text"), 2, 2)
        top.addWidget(self.rule_value, 2, 3)
        left.addWidget(target_group)

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
        left.addWidget(image_group)

        helper_group = QGroupBox("Target Helper / Inspect Paste")
        helper_layout = QGridLayout(helper_group)
        self.inspect_text = QTextEdit()
        self.inspect_text.setPlaceholderText("Paste Inspect Code, HTML, SVG, XPath, or Selector Here")
        self.inspect_mode = QComboBox()
        self.inspect_mode.addItems([
            "Auto Detect", "CSS Selector", "XPath", "HTML Snippet", "SVG Snippet", "Text Content", "Attribute Snippet"
        ])
        self.analyze_btn = QPushButton("Analyze Pasted Code")
        self.convert_btn = QPushButton("Convert to Detection Rule")
        self.test_paste_btn = QPushButton("Test Against Current Page")
        self.inspect_result = QPlainTextEdit()
        self.inspect_result.setReadOnly(True)
        self.inspect_result.setPlaceholderText("What the app understood")
        self.analyze_btn.clicked.connect(self.analyze_pasted_code)
        self.convert_btn.clicked.connect(self.convert_paste_to_rule)
        self.test_paste_btn.clicked.connect(self.test_paste_against_page)
        helper_layout.addWidget(QLabel("Interpret pasted content as"), 0, 0)
        helper_layout.addWidget(self.inspect_mode, 0, 1, 1, 3)
        helper_layout.addWidget(self.inspect_text, 1, 0, 1, 4)
        helper_layout.addWidget(self.analyze_btn, 2, 0)
        helper_layout.addWidget(self.convert_btn, 2, 1)
        helper_layout.addWidget(self.test_paste_btn, 2, 2)
        helper_layout.addWidget(self.inspect_result, 3, 0, 1, 4)
        left.addWidget(helper_group)

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
        left.addWidget(active_group)

        schedule_group = QGroupBox("Schedule")
        schedule_grid = QGridLayout(schedule_group)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(1.0, 3600.0)
        self.schedule_mode = QComboBox()
        self.schedule_mode.addItems(["interval", "exact_time", "hybrid"])
        self.exact_time = QLineEdit("12:00:00:000")
        self.offset = QDoubleSpinBox()
        self.offset.setRange(-5.0, 5.0)
        self.offset.setDecimals(3)
        self.timeis_input = QLineEdit()
        self.timeis_parse_btn = QPushButton("Parse time.is text")
        self.timeis_parse_btn.clicked.connect(self.parse_timeis_text)
        self.btn_now_plus = QPushButton("Use corrected now")
        self.btn_ms_100 = QPushButton("+100ms")
        self.btn_ms_250 = QPushButton("+250ms")
        self.btn_ms_500 = QPushButton("+500ms")
        self.btn_sec_1 = QPushButton("+1s")
        self.btn_now_plus.clicked.connect(self.set_exact_to_now)
        self.btn_ms_100.clicked.connect(lambda: self.adjust_exact_ms(100))
        self.btn_ms_250.clicked.connect(lambda: self.adjust_exact_ms(250))
        self.btn_ms_500.clicked.connect(lambda: self.adjust_exact_ms(500))
        self.btn_sec_1.clicked.connect(lambda: self.adjust_exact_ms(1000))
        schedule_grid.addWidget(QLabel("Refresh sec"), 0, 0)
        schedule_grid.addWidget(self.interval, 0, 1)
        schedule_grid.addWidget(QLabel("Refresh mode"), 0, 2)
        schedule_grid.addWidget(self.schedule_mode, 0, 3)
        schedule_grid.addWidget(QLabel("Exact refresh time (HH:MM:SS:MMM)"), 1, 0)
        schedule_grid.addWidget(self.exact_time, 1, 1, 1, 3)
        schedule_grid.addWidget(self.btn_now_plus, 2, 0)
        schedule_grid.addWidget(self.btn_ms_100, 2, 1)
        schedule_grid.addWidget(self.btn_ms_250, 2, 2)
        schedule_grid.addWidget(self.btn_ms_500, 2, 3)
        schedule_grid.addWidget(self.btn_sec_1, 2, 4)
        schedule_grid.addWidget(QLabel("Time correction (sec)"), 3, 0)
        schedule_grid.addWidget(self.offset, 3, 1)
        schedule_grid.addWidget(QLabel("time.is text"), 3, 2)
        schedule_grid.addWidget(self.timeis_input, 3, 3)
        schedule_grid.addWidget(self.timeis_parse_btn, 3, 4)
        self.startup_checks = QComboBox()
        self.startup_checks.addItems(["Off", "1 refresh", "3 refreshes"])
        self.startup_delay = QDoubleSpinBox()
        self.startup_delay.setRange(100, 5000)
        self.startup_delay.setValue(350)
        self.startup_delay.setSuffix(" ms")
        schedule_grid.addWidget(QLabel("Startup verification refreshes"), 4, 0)
        schedule_grid.addWidget(self.startup_checks, 4, 1)
        schedule_grid.addWidget(QLabel("Delay between startup checks"), 4, 2)
        schedule_grid.addWidget(self.startup_delay, 4, 3)
        left.addWidget(schedule_group)

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
        self.overlay_enabled = QCheckBox("Top-left overlay")
        self.overlay_enabled.setChecked(True)
        self.overlay_pos = QComboBox()
        self.overlay_pos.addItems(["top_left", "top_right", "bottom_left", "bottom_right"])
        self.overlay_opacity = QSlider(Qt.Horizontal)
        self.overlay_opacity.setRange(30, 100)
        self.overlay_opacity.setValue(92)
        alerts_layout.addWidget(self.overlay_enabled)
        alerts_layout.addWidget(QLabel("Overlay position"))
        alerts_layout.addWidget(self.overlay_pos)
        alerts_layout.addWidget(QLabel("Overlay opacity"))
        alerts_layout.addWidget(self.overlay_opacity)
        left.addWidget(alerts_group)

        status_group = QGroupBox("Live status")
        status_layout = QGridLayout(status_group)
        self.status = QLabel("Idle")
        self.status.setObjectName("statusPill")
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
        right.addWidget(status_group)

        help_group = QGroupBox("What happens when I press Start?")
        help_layout = QVBoxLayout(help_group)
        help_layout.addWidget(QLabel(
            "1) Connects to Brave page. 2) Monitors only this profile. 3) Shows running overlay. "
            "4) Refreshes by interval/exact/hybrid mode. 5) Checks target rule. "
            "6) Alerts on detection. 7) If manual confirm is ON, hotkey is required before click."
        ))
        right.addWidget(help_group)

        buttons = QHBoxLayout()
        self.start_btn = QPushButton("Start Monitoring")
        self.start_btn.setObjectName("startPrimary")
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setObjectName("secondaryBtn")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("dangerBtn")
        self.save_btn = QPushButton("Save Profile")
        self.test_btn = QPushButton("Test Detection")
        self.test_exact_btn = QPushButton("Test Exact Refresh")
        self.open_logs_btn = QPushButton("Open Logs Folder")
        self.start_btn.setMinimumHeight(42)
        self.start_btn.clicked.connect(self.start_monitoring)
        self.pause_btn.clicked.connect(self.pause_monitoring)
        self.stop_btn.clicked.connect(self.stop_monitoring)
        self.save_btn.clicked.connect(self.save_profile)
        self.test_btn.clicked.connect(self.test_detection)
        self.test_exact_btn.clicked.connect(self.test_exact_refresh)
        self.open_logs_btn.clicked.connect(self.open_logs_folder)
        for b in [self.start_btn, self.pause_btn, self.stop_btn, self.save_btn, self.test_btn, self.test_exact_btn, self.open_logs_btn]:
            buttons.addWidget(b)
        right.addLayout(buttons)

        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setPlaceholderText("Live log output...")
        right.addWidget(self.logs)

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
            QLabel#statusPill {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 12px;
                padding: 4px 10px;
                font-weight: 700;
                color: #93c5fd;
            }
            QPushButton#startPrimary {
                background: #16a34a;
                border-color: #22c55e;
                font-size: 14px;
                padding: 10px 16px;
            }
            QPushButton#startPrimary:hover { background: #22c55e; }
            QPushButton#dangerBtn { background: #7f1d1d; border-color: #b91c1c; }
            QPushButton#dangerBtn:hover { background: #991b1b; }
            QPushButton#secondaryBtn { background: #334155; border-color: #475569; }
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
        self.brave_path.setText(p.brave_path)
        self.url_edit.setText(p.target_url)
        self.rule_mode.setCurrentText(p.detection.mode)
        self.rule_value.setText(p.detection.value)
        self.interval.setValue(p.refresh_interval_seconds)
        self.schedule_mode.setCurrentText(p.schedule_mode)
        self.exact_time.setText(p.exact_time_hms)
        self.offset.setValue(p.clock_offset_seconds)
        if p.startup_verification_refreshes <= 0:
            self.startup_checks.setCurrentText("Off")
        elif p.startup_verification_refreshes == 1:
            self.startup_checks.setCurrentText("1 refresh")
        else:
            self.startup_checks.setCurrentText("3 refreshes")
        self.startup_delay.setValue(p.startup_verification_delay_ms)
        self.active_days.setText(",".join(str(d) for d in p.active_hours.days))
        self.active_start.setText(p.active_hours.start)
        self.active_end.setText(p.active_hours.end)
        self.alert_sound.setChecked(p.alerts.play_sound)
        self.alert_front.setChecked(p.alerts.bring_to_front)
        self.alert_clip.setChecked(p.alerts.copy_to_clipboard)
        self.manual_confirm.setChecked(p.alerts.manual_confirm_click)
        self.hotkey.setText(p.alerts.manual_hotkey)
        self.overlay_enabled.setChecked(p.alerts.overlay_enabled)
        self.overlay_pos.setCurrentText(p.alerts.overlay_position)
        self.overlay_opacity.setValue(int(p.alerts.overlay_opacity * 100))
        self.image_mode.setCurrentText(p.detection.image_mode)
        self.confidence.setValue(p.detection.confidence_threshold)
        if p.detection.reference_image_path and Path(p.detection.reference_image_path).exists():
            pix = QPixmap(p.detection.reference_image_path).scaledToHeight(72)
            self.preview.setPixmap(pix)

    def _read_profile_from_ui(self) -> MonitoringProfile:
        p = self.profile
        p.brave_path = self.brave_path.text().strip()
        p.target_url = self.url_edit.text().strip()
        p.detection.mode = self.rule_mode.currentText()
        p.detection.value = self.rule_value.text().strip()
        p.refresh_interval_seconds = self.interval.value()
        p.schedule_mode = self.schedule_mode.currentText()
        try:
            p.exact_time_hms = RefreshScheduler.normalize_exact_time(self.exact_time.text().strip())
            self.exact_time.setText(p.exact_time_hms)
        except Exception:
            p.exact_time_hms = "12:00:00:000"
            self.exact_time.setText(p.exact_time_hms)
        p.clock_offset_seconds = self.offset.value()
        if self.startup_checks.currentText() == "Off":
            p.startup_verification_refreshes = 0
        elif self.startup_checks.currentText() == "1 refresh":
            p.startup_verification_refreshes = 1
        else:
            p.startup_verification_refreshes = 3
        p.startup_verification_delay_ms = int(self.startup_delay.value())
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
        p.alerts.overlay_enabled = self.overlay_enabled.isChecked()
        p.alerts.overlay_position = self.overlay_pos.currentText()
        p.alerts.overlay_opacity = self.overlay_opacity.value() / 100.0
        return p

    def choose_brave_path(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Locate Brave executable", "", "Executable (*.exe)")
        if path:
            self.brave_path.setText(path)

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
        self.last_state = state
        self.system_time.setText(state.get("system_time", "-"))
        self.corrected_time.setText(state.get("corrected_time", "-"))
        self.next_refresh.setText(state.get("next_refresh", "-"))
        self.update_overlay("running")

    def start_monitoring(self) -> None:
        self.save_profile()
        if self.engine:
            QMessageBox.information(self, "Already running", "Monitoring is already running for this profile.")
            return

        callbacks = MonitorCallbacks(
            on_status=self.on_status_changed,
            on_log=self.append_log,
            on_detection=self.on_detection,
            on_state=self.update_state,
        )
        self.engine = MonitorEngine(self.profile, self.logger, callbacks)
        self.engine.start()
        self.connection.setText("Connected")
        self.update_overlay("running")

    def on_status_changed(self, text: str) -> None:
        self.status.setText(text)
        lowered = text.lower()
        if "error" in lowered or "not found" in lowered or "disconnected" in lowered:
            self.update_overlay("error")
        elif "paused" in lowered:
            self.update_overlay("paused")
        else:
            self.update_overlay("running")

    def pause_monitoring(self) -> None:
        if self.engine:
            self.engine.pause()
            self.update_overlay("paused")

    def stop_monitoring(self) -> None:
        if self.engine:
            self.engine.stop()
            self.engine = None
        self.connection.setText("Disconnected")
        self.status.setText("Stopped")
        self.overlay.hide()

    def on_detection(self, message: str) -> None:
        self.last_detection.setText(datetime.now().strftime("%H:%M:%S"))
        self.status.setText(message)
        self.append_log(self.logger.log("ALERT", message, self.profile.clock_offset_seconds, self.profile.log_csv))
        silent_progress = message.startswith("Startup check") or message in {"RUNNING", "Startup verification complete"}
        if self.profile.alerts.play_sound and not silent_progress:
            QGuiApplication.beep()
        if self.profile.alerts.copy_to_clipboard:
            QGuiApplication.clipboard().setText("Target detected")
        if not silent_progress:
            QMessageBox.information(self, "Target detected", message)
            self.update_overlay("detected")
        else:
            self.update_overlay("running")

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

    def test_exact_refresh(self) -> None:
        try:
            normalized = RefreshScheduler.normalize_exact_time(self.exact_time.text())
            self.exact_time.setText(normalized)
            QMessageBox.information(self, "Exact refresh", f"Valid exact time: {normalized}")
        except Exception as exc:
            QMessageBox.warning(self, "Invalid exact time", str(exc))

    def open_logs_folder(self) -> None:
        QGuiApplication.clipboard().setText(str(self.logger.logs_dir))
        QMessageBox.information(self, "Logs folder", f"Logs path copied to clipboard:\n{self.logger.logs_dir}")

    def save_profile(self) -> None:
        self.profile = self._read_profile_from_ui()
        self.config.save(self.profiles, self.profile.name)
        self.append_log(self.logger.log("PROFILE_SAVED", f"Profile saved: {self.profile.name}", self.profile.clock_offset_seconds))

    def parse_timeis_text(self) -> None:
        text = self.timeis_input.text().strip()
        ahead_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*seconds?\s*ahead", text, re.IGNORECASE)
        behind_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*seconds?\s*behind", text, re.IGNORECASE)
        acc_match = re.search(r"±\s*([0-9]+(?:\.[0-9]+)?)\s*seconds?", text, re.IGNORECASE)

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

    def set_exact_to_now(self) -> None:
        now = datetime.now().timestamp() + self.offset.value()
        dt = datetime.fromtimestamp(now)
        self.exact_time.setText(dt.strftime("%H:%M:%S:") + f"{int(dt.microsecond/1000):03d}")

    def adjust_exact_ms(self, ms: int) -> None:
        try:
            normalized = RefreshScheduler.normalize_exact_time(self.exact_time.text())
            hh, mm, ss, mmm = [int(x) for x in normalized.split(":")]
            base = datetime.now().replace(hour=hh, minute=mm, second=ss, microsecond=mmm * 1000)
            from datetime import timedelta
            base = base + timedelta(milliseconds=ms)
            self.exact_time.setText(base.strftime("%H:%M:%S:") + f"{int(base.microsecond/1000):03d}")
        except Exception:
            self.exact_time.setText("12:00:00:000")

    def analyze_pasted_code(self) -> None:
        text = self.inspect_text.toPlainText().strip()
        mode = self.inspect_mode.currentText()
        if not text:
            self.inspect_result.setPlainText("No pasted content yet.")
            return

        detected = mode
        if mode == "Auto Detect":
            if text.startswith("/") or text.startswith("("):
                detected = "XPath"
            elif "<svg" in text.lower():
                detected = "SVG Snippet"
            elif "<" in text and ">" in text:
                detected = "HTML Snippet"
            elif "=" in text and any(k in text for k in ["id", "class", "data-", "aria-"]):
                detected = "Attribute Snippet"
            elif any(c in text for c in [".", "#", ">", "[", "]"]):
                detected = "CSS Selector"
            else:
                detected = "Text Content"

        attrs = re.findall(r"(id|class|aria-label|title|role|data-[\w-]+)=['\"]([^'\"]+)", text, re.IGNORECASE)
        text_hint = re.sub(r"<[^>]+>", " ", text).strip()
        text_hint = re.sub(r"\\s+", " ", text_hint)[:80]
        css_candidate = ""
        xpath_candidate = ""
        rec_primary = "text_contains"
        rec_fallback = "css"

        if attrs:
            for k, v in attrs:
                if k.lower() == "id":
                    css_candidate = f"#{v}"
                    xpath_candidate = f"//*[@id='{v}']"
                    rec_primary = "css"
                    break
            if not css_candidate:
                k, v = attrs[0]
                css_candidate = f"[{k}='{v}']"
                xpath_candidate = f"//*[@{k}='{v}']"
                rec_primary = "attribute"
        elif detected == "CSS Selector":
            css_candidate = text
            rec_primary = "css"
            xpath_candidate = "N/A"
        elif detected == "XPath":
            xpath_candidate = text
            rec_primary = "xpath"
            css_candidate = "N/A"
        else:
            css_candidate = "button, [role='button']"
            xpath_candidate = "//button | //*[@role='button']"
            rec_primary = "text_contains"

        english = "This looks usable."
        if detected == "SVG Snippet":
            english = "This looks like an SVG icon inside a clickable button. Try targeting the parent button."
        if detected == "Text Content":
            english = "This looks like visible text. Text match is recommended."

        self.inspect_result.setPlainText(
            f"Detected input type: {detected}\\n"
            f"Parsed attributes: {attrs or 'None'}\\n"
            f"Suggested CSS selector: {css_candidate} (confidence 0.80)\\n"
            f"Suggested XPath: {xpath_candidate} (confidence 0.75)\\n"
            f"Suggested text match: {text_hint or 'N/A'} (confidence 0.65)\\n"
            f"Primary rule: {rec_primary}\\n"
            f"Fallback rule: {rec_fallback}\\n"
            f"Plain English: {english}"
        )

    def convert_paste_to_rule(self) -> None:
        self.analyze_pasted_code()
        result = self.inspect_result.toPlainText()
        if "Primary rule: css" in result:
            self.rule_mode.setCurrentText("css")
            m = re.search(r"Suggested CSS selector: (.+?) \\(confidence", result)
            if m:
                self.rule_value.setText(m.group(1))
        elif "Primary rule: xpath" in result:
            self.rule_mode.setCurrentText("xpath")
            m = re.search(r"Suggested XPath: (.+?) \\(confidence", result)
            if m:
                self.rule_value.setText(m.group(1))
        else:
            self.rule_mode.setCurrentText("text_contains")
            m = re.search(r"Suggested text match: (.+?) \\(confidence", result)
            if m and m.group(1) != "N/A":
                self.rule_value.setText(m.group(1))

    def test_paste_against_page(self) -> None:
        if not self.engine:
            QMessageBox.information(self, "Start required", "Start monitoring first, then test.")
            return
        self.convert_paste_to_rule()
        QMessageBox.information(self, "Test result", self.engine.test_detection())

    def update_overlay(self, state: str) -> None:
        if not self.overlay_enabled.isChecked():
            self.overlay.hide()
            return
        screen_geo = QApplication.primaryScreen().availableGeometry()
        pos = self.overlay_pos.currentText()
        w, h = self.overlay.width(), self.overlay.height()
        x = 20 if "left" in pos else screen_geo.width() - w - 20
        y = 20 if "top" in pos else screen_geo.height() - h - 40
        self.overlay.move(x, y)
        self.overlay.setWindowOpacity(self.overlay_opacity.value() / 100.0)
        text = [self.status.text() or "RUNNING", "Monitoring active"]
        if self.profile.alerts.overlay_show_profile:
            text.append(f"Profile: {self.profile.name}")
        if self.profile.alerts.overlay_show_next_refresh:
            text.append(f"Next refresh: {self.last_state.get('next_refresh', '-')}")
        if self.profile.alerts.overlay_show_corrected_time:
            text.append(f"Corrected time: {self.last_state.get('corrected_time', '-')}")
        self.overlay.update_text("\n".join(text), state=state)
        self.overlay.show()

    def _tick_clock(self) -> None:
        self.system_time.setText(datetime.now().strftime("%H:%M:%S.%f")[:-3])
        corrected = datetime.now().timestamp() + self.offset.value()
        self.corrected_time.setText(datetime.fromtimestamp(corrected).strftime("%H:%M:%S.%f")[:-3])

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.stop_monitoring()
        self.append_log(self.logger.log("APP_CLOSED", "Application closed", self.profile.clock_offset_seconds, self.profile.log_csv))
        event.accept()
