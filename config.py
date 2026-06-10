"""
config.py – Cấu hình trung tâm của hệ thống phát hiện cháy
══════════════════════════════════════════════════════════
Chỉnh sửa file này để thay đổi các tham số hệ thống.
Các tọa độ hiệu chuẩn phối cảnh được đọc từ calibration.json
(tạo bằng cách chạy: python calibrate.py)
"""

import json
import os

# ─── Camera ──────────────────────────────────────────────────────────────────
# DroidCam WiFi: đổi IP thành IP điện thoại trong cùng mạng LAN
DROIDCAM_WIFI_URL = "http://192.168.1.95:4747/video"

# DroidCam USB: dùng index thiết bị (thường là 1 hoặc 2)
DROIDCAM_USB_INDEX = 1

# Chọn chế độ: "wifi" hoặc "usb"
CAMERA_MODE = "wifi"

# Độ phân giải mong muốn (None = dùng mặc định của camera)
CAMERA_WIDTH  = 1280
CAMERA_HEIGHT = 720

# ─── YOLOv8 Model ────────────────────────────────────────────────────────────
MODEL_PATH = "models/fire_smoke.pt"

# Class IDs – điều chỉnh theo model bạn sử dụng
CLASS_FIRE  = 0
CLASS_SMOKE = 1
CLASS_NAMES = {CLASS_FIRE: "Lửa", CLASS_SMOKE: "Khói"}

# Ngưỡng confidence tối thiểu để chấp nhận kết quả phát hiện
FIRE_CONF_THRESHOLD  = 0.50
SMOKE_CONF_THRESHOLD = 0.45

# ─── Perspective Transform ───────────────────────────────────────────────────
CALIBRATION_FILE = "calibration.json"

# Kích thước ảnh bird's-eye (nhìn từ trên xuống) sau khi nắn thẳng
WARP_WIDTH  = 640
WARP_HEIGHT = 640

# Tọa độ mặc định dùng khi chưa có file calibration.json
# Thứ tự: [trên-trái, trên-phải, dưới-phải, dưới-trái] trong ảnh camera gốc
DEFAULT_SRC_POINTS = [
    [120,  60],
    [520,  60],
    [590, 410],
    [50,  410],
]


def load_calibration() -> list:
    """
    Đọc tọa độ 4 điểm từ calibration.json.
    Trả về DEFAULT_SRC_POINTS nếu file chưa tồn tại.
    """
    if os.path.exists(CALIBRATION_FILE):
        try:
            with open(CALIBRATION_FILE, "r") as f:
                data = json.load(f)
            pts = data.get("src_points")
            if pts and len(pts) == 4:
                print(f"[Config] Đã tải calibration từ {CALIBRATION_FILE}")
                return pts
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[Config] Lỗi đọc calibration: {e} – dùng mặc định.")
    else:
        print(f"[Config] Chưa có {CALIBRATION_FILE}. Chạy calibrate.py trước!")
    return DEFAULT_SRC_POINTS


# ─── Zone Layout ─────────────────────────────────────────────────────────────
NUM_ZONES = 4
# Bố cục 2×2 trên ảnh bird's-eye:
#   Zone 1 (trên-trái)  │  Zone 2 (trên-phải)
#  ─────────────────────┼──────────────────────
#   Zone 3 (dưới-trái)  │  Zone 4 (dưới-phải)


# ─── ESP32 Serial ────────────────────────────────────────────────────────────
# Windows: "COM3", "COM4", …
# Linux/macOS: "/dev/ttyUSB0", "/dev/ttyACM0", …
ESP32_PORT      = "COM3"
ESP32_BAUD_RATE = 115200
ESP32_TIMEOUT   = 1.0   # giây – timeout khi đọc phản hồi


# ─── Ngưỡng cảnh báo ─────────────────────────────────────────────────────────
# Tỷ lệ diện tích bbox / tổng khung hình → kích hoạt KHẨN CẤP
FIRE_AREA_EMERGENCY_RATIO  = 0.15   # 15% → lửa quá lớn
SMOKE_AREA_EMERGENCY_RATIO = 0.40   # 40% → khói che khuất camera

# Số frame liên tiếp KHÔNG phát hiện lửa trước khi tắt relay của Zone đó
CLEAR_CONFIRMATION_FRAMES = 30      # ≈ 1 giây ở 30fps

# Số frame phát hiện liên tiếp trước khi kích hoạt relay (lọc false positive)
ACTIVATE_CONFIRMATION_FRAMES = 3


# ─── Telegram ────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID   = "YOUR_CHAT_ID_HERE"

# Thời gian chờ tối thiểu (giây) giữa 2 lần gửi cảnh báo thông thường
TELEGRAM_ALERT_COOLDOWN_SEC = 30


# ─── Logging ─────────────────────────────────────────────────────────────────
LOG_FILE = "logs/fire_system.log"
