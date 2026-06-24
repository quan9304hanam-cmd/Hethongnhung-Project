"""
config.py – Cấu hình hệ thống báo cháy 2 Camera
═══════════════════════════════════════════════
  Zone 1 = Camera PC (webcam laptop/USB)
  Zone 2 = Camera điện thoại (DroidCam)

Không còn dùng Perspective Transform – mỗi camera TỰ LÀ một Zone,
nên không cần calibrate.py / calibration.json như bản trước.
"""

# ─── Camera Zone 1 – Camera PC ────────────────────────────────────────────────
# Webcam tích hợp laptop thường là index 0. Nếu có nhiều camera, thử 1, 2…
CAM1_SOURCE = 0

# ─── Camera Zone 2 – DroidCam (điện thoại) ────────────────────────────────────
CAM2_MODE = "wifi"      # "wifi" hoặc "usb"

# DroidCam WiFi: đổi IP thành IP điện thoại trong cùng mạng LAN
DROIDCAM_WIFI_URL = "http://172.20.6.109:4747/video"

# DroidCam USB: index thiết bị (thường là 1 hoặc 2, thử nếu sai)
DROIDCAM_USB_INDEX = 1

# ─── Độ phân giải mong muốn cho cả 2 camera ───────────────────────────────────
CAMERA_WIDTH  = 640
CAMERA_HEIGHT = 480

# ─── YOLOv8 Model ──────────────────────────────────────────────────────────────
MODEL_PATH = "models/fire_smoke.pt"

# Class ID của "lửa" trong model – kiểm tra bằng model.names sau khi load
CLASS_FIRE = 0

# Ngưỡng confidence tối thiểu để chấp nhận một detection là lửa thật
FIRE_CONF_THRESHOLD = 0.50

# ─── Ngưỡng phân loại kích thước lửa (theo % PIXEL khung hình bị che) ─────────
#   ratio < 10%            → "nhỏ"
#   10% <= ratio < 25%     → "vừa"
#   ratio >= 25%           → "lớn"
SMALL_FIRE_MAX_RATIO  = 0.10
MEDIUM_FIRE_MAX_RATIO = 0.25

# ─── Debounce kích hoạt & độ trễ tắt ──────────────────────────────────────────
# Số frame liên tiếp PHẢI thấy lửa mới được tính là "có cháy" (chống false positive)
ACTIVATE_CONFIRMATION_FRAMES = 3

# Số giây sau khi KHÔNG còn thấy lửa mới tắt đèn + chuông của Zone đó
# (đúng yêu cầu: "sau khi lửa tắt 5 giây tắt đèn, tắt chuông báo")
OFF_DELAY_SECONDS = 5.0

# Khoảng cách tối thiểu (giây) giữa 2 lần in lại CÙNG MỘT mức cảnh báo
# (tránh terminal bị spam khi lửa cháy liên tục nhiều giây)
PRINT_COOLDOWN_SEC = 2.0

# ─── ESP32 Serial ──────────────────────────────────────────────────────────────
# Windows: "COM3", "COM4", …      Linux/macOS: "/dev/ttyUSB0", "/dev/ttyACM0"
ESP32_PORT      = "COM3"
ESP32_BAUD_RATE = 115200
ESP32_TIMEOUT   = 1.0

# ─── Logging ────────────────────────────────────────────────────────────────────
LOG_FILE = "logs/fire_alarm.log"
