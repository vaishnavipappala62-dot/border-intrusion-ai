"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         SMART BORDER INTRUSION DETECTION SYSTEM  v1.0                       ║
║         AI-Powered Real-Time Surveillance Prototype                          ║
║         Uses: OpenCV + Moondream VLM API + Gmail SMTP + pyttsx3             ║
╚══════════════════════════════════════════════════════════════════════════════╝

SETUP (run once):
    pip install opencv-python moondream pillow pyttsx3 python-dotenv requests

CONFIGURE (in this file or via .env):
    MOONDREAM_API_KEY  → get from https://moondream.ai
    EMAIL_SENDER       → your Gmail address
    EMAIL_PASSWORD     → Gmail App Password (not your real password)
    EMAIL_RECEIVER     → alert recipient email

CAMERA:
    Use DroidCam (Android) or EpocCam (iOS) to use phone as webcam.
    Default: CAMERA_INDEX = 0  (laptop webcam)
              CAMERA_INDEX = 1  (DroidCam / USB webcam)
"""
 
# ─────────────────────────────────────────────
#  CONFIGURATION  ← Edit these before running
# ─────────────────────────────────────────────
import os

# Try loading from .env file if it exists
try:
    from dotenv import load_dotenv 
    load_dotenv()
except ImportError:
    pass  # dotenv optional

MOONDREAM_API_KEY  = os.getenv("MOONDREAM_API_KEY",  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJrZXlfaWQiOiJlZGQ0Yzc4YS05ZmEyLTQ1NjAtYmZkZC03MTQ0YjgxMWVlZDkiLCJvcmdfaWQiOiJ0U1J3RmJFd2tINkl1Tk9ITjNLZHpsalgzaE9ROVY1VSIsImlhdCI6MTc3NDY3NDEzMCwidmVyIjoxfQ.804RMJnbaTp1RyAaRJGfPTd8akZsOOS07CBnag_Jo_Y")
EMAIL_SENDER       = os.getenv("EMAIL_SENDER",       "vaishnavipappala58@gmail.com")
EMAIL_PASSWORD     = os.getenv("EMAIL_PASSWORD",     "anuvhcrmnzirymad")
EMAIL_RECEIVER     = os.getenv("EMAIL_RECEIVER",     "manasasammangi@gmail.com")

CAMERA_INDEX       = int(os.getenv("CAMERA_INDEX", 0))   # 0=laptop webcam (testing mode)
CAMERA_LOCATION    = os.getenv("CAMERA_LOCATION", "Sector Alpha – Border Gate 1")
CHECK_INTERVAL_SEC = int(os.getenv("CHECK_INTERVAL_SEC", 4))   # AI check every N seconds
ALERT_THRESHOLD    = int(os.getenv("ALERT_THRESHOLD", 2))       # consecutive detections to trigger (2 = easier for testing)
LOG_FILE           = os.getenv("LOG_FILE", "border_log.csv")
SAVE_DIR           = os.getenv("SAVE_DIR", "detections")        # folder for saved intruder images
VOICE_ALERTS       = os.getenv("VOICE_ALERTS", "true").lower() == "true"

# ─────────────────────────────────────────────
#  IMPORTS
# ─────────────────────────────────────────────
import cv2
import time
import datetime
import smtplib
import threading
import base64
import json
import csv
import sys
import os
import io
import traceback
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text    import MIMEText
from email.mime.image   import MIMEImage
from email.message      import EmailMessage

# Optional voice alert
try:
    import pyttsx3
    _tts_engine = pyttsx3.init()
    _tts_engine.setProperty("rate", 160)
    _voice_available = True
except Exception:
    _voice_available = False

# PIL for image encoding
try:
    from PIL import Image
    _pil_available = True
except ImportError:
    _pil_available = False

# ─────────────────────────────────────────────
#  GLOBALS
# ─────────────────────────────────────────────
detection_count     = 0          # consecutive positive detections
total_detections    = 0          # all-time detections this session
total_checks        = 0          # total AI checks performed
session_start       = time.time()
_alert_cooldown     = False      # prevent spam emails
_alert_lock         = threading.Lock()
_voice_lock         = threading.Lock()

# ─────────────────────────────────────────────
#  UTILITY — Console Colors
# ─────────────────────────────────────────────
class C:
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    CYAN    = "\033[96m"
    BOLD    = "\033[1m"
    RESET   = "\033[0m"
    BLUE    = "\033[94m"
    MAGENTA = "\033[95m"
    WHITE   = "\033[97m"

def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log(msg, color=C.WHITE):
    print(f"{color}[{now_str()}] {msg}{C.RESET}")

def banner():
    print(f"""
{C.CYAN}{C.BOLD}
╔══════════════════════════════════════════════════════════════════╗
║     🛡️  SMART BORDER INTRUSION DETECTION SYSTEM  v1.0           ║
║         AI-Powered Surveillance Prototype                        ║
╠══════════════════════════════════════════════════════════════════╣
║  Location  : {CAMERA_LOCATION:<50}║
║  Camera    : Index {CAMERA_INDEX}  │  Check Interval: {CHECK_INTERVAL_SEC}s  │  Threshold: {ALERT_THRESHOLD}   ║
║  Log File  : {LOG_FILE:<50}║
╚══════════════════════════════════════════════════════════════════╝
{C.RESET}""")

# ─────────────────────────────────────────────
#  SETUP — ensure folders & log file exist
# ─────────────────────────────────────────────
def setup():
    Path(SAVE_DIR).mkdir(parents=True, exist_ok=True)
    if not Path(LOG_FILE).exists():
        with open(LOG_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "status", "location", "image_path", "ai_response"])
    log("System initialised. Logs → " + LOG_FILE, C.GREEN)

# ─────────────────────────────────────────────
#  CAMERA — open & read frame
# ─────────────────────────────────────────────
def open_camera():
    log(f"Opening camera index {CAMERA_INDEX} ...", C.CYAN)
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        log("ERROR: Cannot open camera. Check CAMERA_INDEX or DroidCam connection.", C.RED)
        sys.exit(1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    log("Camera opened successfully ✓", C.GREEN)
    return cap

def capture_frame(cap):
    ret, frame = cap.read()
    if not ret:
        log("WARNING: Failed to capture frame.", C.YELLOW)
        return None
    return frame

# ─────────────────────────────────────────────
#  MOONDREAM API — analyse frame
# ─────────────────────────────────────────────
MOONDREAM_PROMPT = (
    "You are a border security AI system. "
    "Look at the image and determine if there is any human or suspicious activity "
    "in a restricted border area. "
    "If a person, weapon, or unusual movement is present, reply YES. "
    "Otherwise reply NO. Give a short reason."
)

def frame_to_base64(frame):
    """Convert OpenCV BGR frame to base64 JPEG string."""
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buf.tobytes()).decode("utf-8")

def query_moondream(frame):
    """Send frame to Moondream cloud API and get response."""
    import urllib.request
    import urllib.error

    b64 = frame_to_base64(frame)
    payload = json.dumps({
        "image_url": f"data:image/jpeg;base64,{b64}",
        "question": MOONDREAM_PROMPT
    }).encode("utf-8")

    req = urllib.request.Request(
        url="https://api.moondream.ai/v1/query",
        data=payload,
        headers={
            "X-Moondream-Auth":MOONDREAM_API_KEY,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            # API returns {"answer": "..."} or {"result": "..."}
            answer = data.get("answer") or data.get("result") or ""
            return answer.strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        log(f"Moondream API HTTP {e.code}: {body[:200]}", C.RED)
        return ""
    except Exception as e:
        log(f"Moondream API error: {e}", C.RED)
        return ""

def is_intrusion(ai_response: str) -> bool:
    """Return True if AI response indicates intrusion."""
    if not ai_response:
        return False
    first_word = ai_response.strip().split()[0].upper().strip(".,!?")
    return first_word == "YES"

# ─────────────────────────────────────────────
#  SAVE IMAGE EVIDENCE
# ─────────────────────────────────────────────
def save_evidence(frame) -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = str(Path(SAVE_DIR) / f"intrusion_{ts}.jpg")
    cv2.imwrite(path, frame)
    log(f"Evidence saved → {path}", C.YELLOW)
    return path

# ─────────────────────────────────────────────
#  LOG TO CSV
# ─────────────────────────────────────────────
def log_event(status: str, image_path: str, ai_response: str):
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([now_str(), status, CAMERA_LOCATION, image_path, ai_response])

# ─────────────────────────────────────────────
#  EMAIL ALERT
# ─────────────────────────────────────────────
def send_email(image_path):
    msg = EmailMessage()
    msg['Subject'] = "🚨 Intrusion Detected"
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECEIVER

    msg.set_content("Intrusion detected! See attached image.")

    with open(image_path, 'rb') as f:
        img_data = f.read()

    msg.add_attachment(img_data, maintype='image', subtype='jpeg', filename='intrusion.jpg')

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
        smtp.send_message(msg)

def _send_alert_thread(image_path: str, ai_response: str):
    """Actual thread function to send email."""
    global _alert_cooldown
    try:
        ts = now_str()
        msg = MIMEMultipart()
        msg["Subject"] = f"🚨 BORDER INTRUSION DETECTED — {ts}"
        msg["From"]    = EMAIL_SENDER
        msg["To"]      = EMAIL_RECEIVER

        body = f"""\
🚨 BORDER INTRUSION ALERT
══════════════════════════
Time      : {ts}
Location  : {CAMERA_LOCATION}

AI Analysis:
"{ai_response}"

Possible unauthorized activity detected.
Immediate attention required.
"""
        msg.attach(MIMEText(body, "plain"))

        # Attach image evidence
        if image_path and Path(image_path).exists():
            with open(image_path, "rb") as f:
                img_data = f.read()
            img_part = MIMEImage(img_data, name=Path(image_path).name)
            img_part.add_header("Content-Disposition", "attachment",
                                filename=Path(image_path).name)
            msg.attach(img_part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)

        log("✅ Alert email sent successfully!", C.GREEN)
    except Exception as e:
        log(f"Email send failed: {e}", C.RED)
    finally:
        time.sleep(60)   # 60-second cooldown between emails
        with _alert_lock:
            _alert_cooldown = False

def send_email_alert(image_path: str, ai_response: str):
    """Send alert email with attached intrusion image."""
    global _alert_cooldown
    with _alert_lock:
        if _alert_cooldown:
            log("Email cooldown active — skipping duplicate alert.", C.YELLOW)
            return
        _alert_cooldown = True

    threading.Thread(target=_send_alert_thread, args=(image_path, ai_response), daemon=True).start()

# ─────────────────────────────────────────────
#  VOICE ALERT
# ─────────────────────────────────────────────
def speak(text: str):
    if not VOICE_ALERTS or not _voice_available:
        return
    def _speak():
        with _voice_lock:
            try:
                _tts_engine.say(text)
                _tts_engine.runAndWait()
            except Exception:
                pass
    threading.Thread(target=_speak, daemon=True).start()

# ─────────────────────────────────────────────
#  OVERLAY — draw HUD on frame
# ─────────────────────────────────────────────
def draw_hud(frame, status: str, count: int, ai_resp: str,
             checks: int, detections: int, elapsed: float):
    h, w = frame.shape[:2]

    # Semi-transparent top bar
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 60), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    # Status text
    color = (0, 80, 255) if "INTRUSION" in status else (0, 220, 80)
    cv2.putText(frame, f"STATUS: {status}", (10, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)
    cv2.putText(frame, f"Consecutive: {count}/{ALERT_THRESHOLD}  |  Checks: {checks}  |  Alerts: {detections}",
                (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1)

    # Bottom info bar
    cv2.rectangle(frame, (0, h - 45), (w, h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
    cv2.putText(frame, f"Location: {CAMERA_LOCATION}", (10, h - 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 255), 1)
    cv2.putText(frame, f"Time: {now_str()}  |  Session: {int(elapsed)}s",
                (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (140, 140, 140), 1)

    # Last AI response (truncated)
    if ai_resp:
        short = ai_resp[:80] + "..." if len(ai_resp) > 80 else ai_resp
        cv2.putText(frame, f"AI: {short}", (10, h - 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 230, 100), 1)

    # Red border flash on intrusion
    if "INTRUSION" in status:
        cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (0, 0, 255), 6)

    return frame

# ─────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────
def main():
    global detection_count, total_detections, total_checks

    banner()
    setup()

    # Validate config
    if not MOONDREAM_API_KEY or MOONDREAM_API_KEY == "YOUR_MOONDREAM_API_KEY_HERE" or MOONDREAM_API_KEY == "YOUR_API_KEY":
        log("⚠️  WARNING: MOONDREAM_API_KEY not set! AI detection will not work.", C.YELLOW)
    if not EMAIL_SENDER or EMAIL_SENDER == "youremail@gmail.com":
        log("⚠️  WARNING: Email not configured — alerts will be logged but not sent.", C.YELLOW)

    cap = open_camera()

    last_check_time = 0.0
    last_ai_response = ""
    current_status = "MONITORING"

    log("System live. Press [Q] to quit.", C.GREEN)
    speak("Border monitoring system activated.")

    try:
        while True:
            frame = capture_frame(cap)
            if frame is None:
                time.sleep(0.5)
                continue

            elapsed = time.time() - session_start
            now_ts  = time.time()

            # ── AI CHECK (every CHECK_INTERVAL_SEC seconds) ──
            if now_ts - last_check_time >= CHECK_INTERVAL_SEC:
                last_check_time = now_ts
                total_checks += 1
                log(f"Running AI check #{total_checks} ...", C.CYAN)

                ai_response = query_moondream(frame)
                last_ai_response = ai_response

                if ai_response:
                    log(f"AI Response: {ai_response}", C.MAGENTA)
                
                if not ai_response:
                    log("AI response empty — skipping detection", C.YELLOW)
                    # We skip the rest of the status check so we don't accidentally clear the detection count
                elif is_intrusion(ai_response):
                    detection_count += 1
                    current_status = f"⚠ POSSIBLE INTRUSION (count {detection_count}/{ALERT_THRESHOLD})"
                    log(current_status, C.YELLOW)

                    # ── ALERT THRESHOLD REACHED ──
                    if detection_count >= ALERT_THRESHOLD:
                        total_detections += 1
                        current_status =  "🚨 INTRUSION DETECTED — ALERT TRIGGERED!"
                        log(current_status, C.RED + C.BOLD)

                        img_path = save_evidence(frame)
                        log_event("INTRUSION", img_path, ai_response)
                        send_email_alert(img_path, ai_response)
                        speak("Alert! Intrusion detected at border. Security notified.")

                        detection_count = 0   # reset after firing alert
                else:
                    if detection_count > 0:
                        log(f"Cleared — consecutive count reset (was {detection_count})", C.GREEN)
                    detection_count = 0
                    current_status = "✅ MONITORING — Area secure"
                    log(current_status, C.GREEN)
                    log_event("CLEAR", "", ai_response)

            # ── DRAW HUD & SHOW FRAME ──
            display = draw_hud(frame.copy(), current_status, detection_count,
                               last_ai_response, total_checks,
                               total_detections, elapsed)
            cv2.imshow("Smart Border Intrusion Detection System", display)

            # ── KEY PRESS ──
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == ord("Q"):
                log("Shutdown requested by user.", C.YELLOW)
                break
            elif key == ord("s"):
                # Manual snapshot
                path = save_evidence(frame)
                log(f"Manual snapshot saved: {path}", C.CYAN)

    except KeyboardInterrupt:
        log("KeyboardInterrupt — shutting down.", C.YELLOW)
    except Exception as e:
        log(f"Fatal error: {e}", C.RED)
        traceback.print_exc()
    finally:
        cap.release()
        cv2.destroyAllWindows()
        log("Camera released. System offline.", C.CYAN)
        _print_summary()

# ─────────────────────────────────────────────
#  SESSION SUMMARY
# ─────────────────────────────────────────────
def _print_summary():
    elapsed = int(time.time() - session_start)
    print(f"""
{C.CYAN}{C.BOLD}
╔══════════════════════════════════════════════╗
║              SESSION SUMMARY                 ║
╠══════════════════════════════════════════════╣
║  Duration        : {elapsed}s
║  AI Checks       : {total_checks}
║  Intrusion Events: {total_detections}
║  Log File        : {LOG_FILE}
║  Evidence Folder : {SAVE_DIR}/
╚══════════════════════════════════════════════╝
{C.RESET}""")

# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    main()
