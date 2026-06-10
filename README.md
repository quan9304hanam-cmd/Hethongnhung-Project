# Hệ thống Phát hiện Cháy Tự động
**YOLOv8 + OpenCV + ESP32 + Telegram**

---

## Tổng quan

Camera điện thoại (qua DroidCam) quan sát khu vực mặt bằng từ góc nghiêng.
Laptop chạy YOLOv8 phát hiện lửa/khói, nắn thẳng góc nhìn qua Perspective Transform,
xác định Zone đang cháy, rồi ra lệnh cho ESP32 bật relay tương ứng.

```
[Camera/DroidCam] → [Laptop: YOLOv8 + OpenCV] → [ESP32 Serial] → [Relay × 4]
                                                ↓
                                         [Telegram Alert]
```

**Bố cục 4 Zone (nhìn từ trên xuống):**
```
  Zone 1  │  Zone 2
 ──────────┼──────────
  Zone 3  │  Zone 4
```

---

## Cài đặt

### 1. Clone / giải nén dự án
```
fire_detection_system/
├── config.py          # Cấu hình (sửa tại đây)
├── vision_utils.py    # Perspective transform + zone detection
├── communication.py   # ESP32 serial + Telegram
├── calibrate.py       # Công cụ hiệu chuẩn góc camera
├── main.py            # Luồng chính
├── requirements.txt
├── models/            # Đặt file .pt vào đây
└── esp32_firmware/
    └── relay_control.ino
```

### 2. Cài Python packages
```bash
pip install -r requirements.txt
```

### 3. Chuẩn bị YOLOv8 model

Cần file `.pt` được huấn luyện nhận diện **fire** (class 0) và **smoke** (class 1).

**Tùy chọn A – Tải model từ Roboflow Universe:**
```bash
pip install roboflow
# Tải model fire/smoke detection phù hợp, đặt vào models/fire_smoke.pt
```

**Tùy chọn B – Dùng model có sẵn (ví dụ):**
```python
from ultralytics import YOLO
# Kiểm tra class names của model
model = YOLO("models/fire_smoke.pt")
print(model.names)   # {0: 'fire', 1: 'smoke'} hay khác?
```
Nếu class ID khác, cập nhật `CLASS_FIRE` và `CLASS_SMOKE` trong `config.py`.

### 4. Nạp firmware ESP32

- Mở `esp32_firmware/relay_control.ino` bằng **Arduino IDE**
- Cài board: *ESP32 Dev Module*
- Nạp vào ESP32 (cổng USB)
- Ghi lại cổng COM (ví dụ `COM3` hoặc `/dev/ttyUSB0`)

**Nối dây relay:**
```
ESP32 GPIO 26 → IN1 (Zone 1)
ESP32 GPIO 27 → IN2 (Zone 2)
ESP32 GPIO 14 → IN3 (Zone 3)
ESP32 GPIO 12 → IN4 (Zone 4)
VCC (5V/3.3V) → VCC module relay
GND           → GND module relay
```
> ⚠ Module relay hầu hết là **active-low** (GPIO LOW = relay ON).
> Nếu module của bạn active-high, đổi `RELAY_ACTIVE_LEVEL = HIGH` trong `.ino`.

### 5. Cài DroidCam

- Tải **DroidCam** trên điện thoại (Android/iOS)
- Tải **DroidCam Client** trên máy tính
- Kết nối qua WiFi: lấy IP điện thoại → cập nhật `DROIDCAM_WIFI_URL` trong `config.py`
- Hoặc kết nối USB: cập nhật `CAMERA_MODE = "usb"` và `DROIDCAM_USB_INDEX`

### 6. Cấu hình Telegram (tùy chọn)

1. Nhắn `/newbot` cho [@BotFather](https://t.me/BotFather), lấy **Bot Token**
2. Nhắn tin cho bot, rồi truy cập:
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
   để lấy **Chat ID**
3. Điền vào `config.py`:
   ```python
   TELEGRAM_BOT_TOKEN = "1234567890:ABCdef..."
   TELEGRAM_CHAT_ID   = "987654321"
   ```

---

## Sử dụng

### Bước 1 – Hiệu chuẩn phối cảnh (chạy 1 lần)

```bash
python calibrate.py
```

Cửa sổ camera mở ra → click lần lượt **4 góc** của khu vực sàn muốn giám sát
theo thứ tự: **Trên-Trái → Trên-Phải → Dưới-Phải → Dưới-Trái** → nhấn **[P]** preview → **[S]** lưu.

File `calibration.json` được tạo tự động.

### Bước 2 – Chỉnh config.py

```python
ESP32_PORT      = "COM3"          # cổng USB của ESP32
DROIDCAM_WIFI_URL = "http://192.168.x.x:4747/video"
MODEL_PATH      = "models/fire_smoke.pt"
```

### Bước 3 – Chạy hệ thống chính

```bash
python main.py
```

Cửa sổ hiển thị gồm 2 phần:
- **Trái**: ảnh camera gốc với bounding box YOLOv8
- **Phải**: bird's-eye view với lưới 4 Zone và vị trí lửa (dấu ★)

**Phím tắt trong cửa sổ:**
| Phím | Tác dụng |
|------|----------|
| Q    | Thoát (tắt relay an toàn) |
| S    | Chụp màn hình lưu vào logs/ |
| T    | Gửi thử thông báo Telegram |
| A    | Tắt tất cả relay ngay lập tức |

---

## Tinh chỉnh tham số

Chỉnh trong `config.py`:

| Tham số | Mặc định | Ý nghĩa |
|---------|----------|---------|
| `FIRE_CONF_THRESHOLD` | 0.50 | Confidence tối thiểu để nhận lửa |
| `SMOKE_CONF_THRESHOLD` | 0.45 | Confidence tối thiểu để nhận khói |
| `ACTIVATE_CONFIRMATION_FRAMES` | 3 | Frame liên tiếp có lửa → bật relay |
| `CLEAR_CONFIRMATION_FRAMES` | 30 | Frame liên tiếp không có lửa → tắt relay |
| `FIRE_AREA_EMERGENCY_RATIO` | 0.15 | % diện tích → báo khẩn cấp |
| `SMOKE_AREA_EMERGENCY_RATIO` | 0.40 | % diện tích khói → báo khẩn cấp |
| `TELEGRAM_ALERT_COOLDOWN_SEC` | 30 | Giây giữa 2 lần gửi Telegram |

---

## Xử lý sự cố

**Camera không kết nối:**
- WiFi: Kiểm tra IP, đảm bảo cùng mạng LAN
- USB: Thử index 0, 1, 2 trong `DROIDCAM_USB_INDEX`

**ESP32 không phản hồi:**
- Kiểm tra cổng COM trong Device Manager (Windows) hoặc `ls /dev/tty*` (Linux)
- Thử cổng khác trong `config.py`
- Kiểm tra driver USB-to-Serial (CP2102 hoặc CH340)

**Model không nhận diện đúng:**
- Xác nhận class ID bằng `print(model.names)`
- Hạ `FIRE_CONF_THRESHOLD` xuống 0.35–0.40 nếu bỏ sót
- Tăng lên 0.60–0.70 nếu quá nhiều false positive

**Relay bật/tắt liên tục (jitter):**
- Tăng `ACTIVATE_CONFIRMATION_FRAMES` lên 5–10
- Tăng `CLEAR_CONFIRMATION_FRAMES` lên 60–90
