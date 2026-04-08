Windows 11 Page Monitor App (Brave) - Beginner Guide
====================================================

IMPORTANT SAFETY NOTE
---------------------
This app is built for safe personal monitoring and manual confirmation.
It does NOT include stealth, fingerprint spoofing, CAPTCHA bypass, unattended claiming,
or anti-bot evasion features.

What this app does
------------------
1) Opens Brave to one target page.
2) Refreshes on your chosen interval.
2b) Or refreshes at an exact daily time (HH:MM:SS) using corrected app time.
2c) Supports exact time with milliseconds: HH:MM:SS:MMM, and hybrid mode.
3) Detects your target button/element by text/CSS/XPath/attribute.
4) Optional reference-image match using OpenCV.
5) Alerts you with popup + optional sound + optional bring-to-front.
6) Supports manual-confirm click only (no unattended loops).
7) Logs all key events to logs folder.

Files included
--------------
- main.py
- gui.py
- monitor.py
- scheduler.py
- config_manager.py
- logger_manager.py
- brave_controller.py
- models.py
- requirements.txt
- build_exe.bat
- settings.json (created automatically)
- logs/ (created automatically)

How to run from source (developer mode)
----------------------------------------
1) Install Python 3.11+ on Windows.
2) Open Command Prompt in this folder.
3) Run:
   pip install -r requirements.txt
   python -m playwright install chromium
   python main.py

How to build a single EXE (Windows 11)
--------------------------------------
1) Double-click build_exe.bat
2) Wait for build to finish
3) Use dist\PageMonitorWin11.exe

First-time setup
----------------
1) Open app.
2) Choose/create profile.
3) Enter Brave executable path (optional, but recommended if auto-detect fails).
4) Enter target URL.
5) Choose detection mode and value.
6) Set refresh seconds (minimum 1 second).
7) Set clock offset:
   - Positive means your PC is behind.
   - Negative means your PC is ahead.
   - You can paste time.is text and click \"Parse time.is text\".
     Example: \"Your clock is 0.4 seconds ahead. Accuracy of synchronization was ±0.106 seconds.\"
     This will set offset to -0.4 automatically.
8) Optional: upload reference image and test image match.
9) Use Target Helper / Inspect Paste to analyze pasted selector/HTML/SVG/XPath text.
10) Set active days/time.
11) Configure Startup verification refreshes (default 3) and delay in milliseconds.
12) Click Save Profile, then Start.

Overlay
-------
- While monitoring is active, an always-on-top overlay can stay visible over Brave.
- You can set overlay position (top-left/top-right/bottom-left/bottom-right) and opacity.
- Startup verification messages are shown in overlay (Startup check 1/3, 2/3, 3/3).

Inspect Paste Helper
--------------------
- Paste content copied from Brave Inspect (selector/XPath/HTML/SVG/text/attributes).
- Click "Analyze Pasted Code" to get:
  - detected type
  - parsed attributes
  - suggested CSS/XPath/text
  - primary + fallback recommendation
- Click "Convert to Detection Rule" to fill the current rule fields.

Manual-confirm click
--------------------
- Enable "Require hotkey for click".
- Set hotkey (default Ctrl+Alt+C).
- When target is detected, press hotkey to send one click.
- Automatic clicking without confirmation is intentionally not included.

What "manual-confirm safety model" means
----------------------------------------
- You can fully set up the profile in advance (URL, selector, exact time, offset, alerts).
- The app can monitor and refresh at your configured corrected time automatically.
- If manual-confirm is ON, the app waits for your hotkey before sending a click.
- If manual-confirm is OFF, the app will still alert you, but will not click automatically.

Logs
----
Logs are written into the logs folder as .log and .csv.
Each line contains system time, corrected time, event type, and details.

Troubleshooting
---------------
- "Brave was not found": set the Brave executable path in the app (Browse Brave), then Start again.
- "No matching button was found": adjust selector/text/image threshold.
- Page timeout: increase interval and verify internet connectivity.
