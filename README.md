# Hệ thống Báo cháy 2 Camera
**YOLOv8 + OpenCV + ESP32 — Zone 1 (Camera PC) & Zone 2 (DroidCam)**

> Đây là bản làm lại theo yêu cầu mới: **không còn Perspective Transform / lưới
> 4 Zone**. Thay vào đó, **mỗi camera tự là 1 Zone** — đơn giản, trực quan,
> dễ lắp đặt hơn cho 2 vị trí giám sát riêng biệt.

---

## Nguyên lý hoạt động

```
[Camera PC]  ──Zone 1──┐
                        │  YOLOv8 (Laptop)
[DroidCam]   ──Zone 2──┘
                        │
                        │  Tính % pixel lửa → phân loại nhỏ/vừa/lớn
                        │  In cảnh báo màu lên terminal
                        │
                        │  USB Serial: Z1:ON / Z2:ON / BUZZER:ON
                        ▼
                    [ESP32]
              ┌────────┼────────┐
              ▼        ▼         ▼
         Đèn Zone1  Đèn Zone2  Chuông
         (chân X)   (chân Y)   báo cháy
```

**Quy tắc phân loại kích thước lửa** (theo % pixel khung hình bị che):

| Tỷ lệ pixel | Mức độ | Thông báo terminal |
|---|---|---|
| < 10% | Nhỏ | `lửa nhỏ ở zone x` |
| 10% – 25% | Vừa | `lửa vừa ở zone x` |
| > 25% | Lớn | `lửa lớn ở zone x` |

**Quy tắc relay:**
- Có lửa ở Zone 1 → bật đèn chân X + bật chuông
- Có lửa ở Zone 2 → bật đèn chân Y + bật chuông
- Hết lửa **quá 5 giây liên tục** → tắt đèn của Zone đó (chuông tự tắt khi cả 2 Zone đều hết cháy)

---

## Cấu trúc dự án

```
fire_alarm_2cam/
├── config.py          # Cấu hình (camera, ngưỡng %, cổng COM, độ trễ)
├── vision_utils.py     # Tính % pixel lửa + phân loại kích thước
├── communication.py    # Giao tiếp ESP32 (2 đèn + chuông)
├── main.py             # Luồng chính – đọc 2 camera, AI, điều khiển
├── requirements.txt
├── models/              # Đặt file .pt vào đây
└── esp32_firmware/
    └── relay_control.ino
```

> Lưu ý: bản này **không cần `calibrate.py`** nữa vì không còn nắn phối
> cảnh. Nếu bạn vẫn cần tính năng Telegram / phát hiện khói / 4-Zone từ
> bản trước, có thể yêu cầu thêm lại — kiến trúc 2 module
> (`communication.py`, `vision_utils.py`) đều dễ mở rộng.

---

## Cài đặt

### 1. Cài Python packages
```bash
pip install -r requirements.txt
```

### 2. Chuẩn bị model YOLOv8
Cần file `.pt` nhận diện class **fire**. Đặt vào `models/fire.pt`, kiểm tra
class ID khớp với `CLASS_FIRE` trong `config.py`:
```python
from ultralytics import YOLO
model = YOLO("models/fire.pt")
print(model.names)   # ví dụ: {0: 'fire'}
```

### 3. Nạp firmware ESP32

- Mở `esp32_firmware/relay_control.ino` bằng Arduino IDE
- Board: *ESP32 Dev Module*, Upload Speed: **115200** (đỡ lỗi `Write timeout`)
- Nạp vào ESP32, ghi lại cổng COM

**Sơ đồ nối dây:**
```
ESP32 GPIO 26 (X) → IN1 relay → Đèn Zone 1
ESP32 GPIO 27 (Y) → IN2 relay → Đèn Zone 2
ESP32 GPIO 25     → IN3 relay → Chuông báo cháy
5V / GND          → VCC / GND module relay
```
> ⚠ Nếu module relay của bạn là active-high (không phải active-low phổ biến),
> đổi `ACTIVE_LOW_MODE = false` trong file `.ino`.

### 4. Cấu hình `config.py`

```python
CAM1_SOURCE = 0                      # Webcam PC – thử 0, 1, 2 nếu sai
DROIDCAM_WIFI_URL = "http://192.168.x.x:4747/video"
ESP32_PORT = "COM3"                  # Cổng USB ESP32
MODEL_PATH = "models/fire.pt"
```

### 5. Chạy hệ thống

```bash
python main.py
```

Cửa sổ hiển thị 2 khung hình cạnh nhau (Zone 1 | Zone 2), mỗi khung có
bounding box lửa + thanh trạng thái phía dưới. Terminal in cảnh báo màu:

```
[14:23:05] 🔥 lửa nhỏ ở zone 1  (chiếm 6.2% khung hình)
[14:23:05] 🚨 KÍCH HOẠT báo động Zone 1 – Bật đèn + chuông!
[14:23:08] 🔥 lửa vừa ở zone 1  (chiếm 14.7% khung hình)
[14:23:15] 🔥 lửa lớn ở zone 1  (chiếm 31.0% khung hình)
[14:23:24] ✅ Zone 1: hết lửa quá 5 giây – Tắt đèn.
```

**Phím tắt trong cửa sổ:**
| Phím | Tác dụng |
|---|---|
| Q | Thoát (tắt relay an toàn) |
| S | Chụp ảnh 2 khung, lưu vào `logs/` |
| A | Tắt tất cả relay ngay (test khẩn cấp) |

---

## Tinh chỉnh tham số (`config.py`)

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `FIRE_CONF_THRESHOLD` | 0.50 | Confidence tối thiểu để nhận là lửa |
| `SMALL_FIRE_MAX_RATIO` | 0.10 | Ngưỡng % pixel: dưới mức này = "nhỏ" |
| `MEDIUM_FIRE_MAX_RATIO` | 0.25 | Ngưỡng % pixel: dưới mức này = "vừa", trên = "lớn" |
| `ACTIVATE_CONFIRMATION_FRAMES` | 3 | Số frame liên tiếp có lửa mới bật relay |
| `OFF_DELAY_SECONDS` | 5.0 | Số giây không thấy lửa mới tắt đèn/chuông |
| `PRINT_COOLDOWN_SEC` | 2.0 | Giây giữa 2 lần in lại cùng mức cảnh báo |

---

## Xử lý sự cố

**Lỗi `Write timeout` khi nạp ESP32:**
Đóng `main.py`/Serial Monitor đang chiếm cổng COM → hạ Upload Speed về
115200 → thử cáp USB khác → nếu vẫn lỗi, giữ nút BOOT khi nạp.

**Camera PC không mở được:**
Thử đổi `CAM1_SOURCE` thành 1 hoặc 2 trong `config.py` (laptop có webcam ảo
hoặc nhiều camera sẽ lệch index).

**DroidCam không kết nối:**
Kiểm tra điện thoại và laptop cùng mạng WiFi, IP đúng với app DroidCam hiển
thị. Thử đổi `CAM2_MODE = "usb"` nếu WiFi không ổn định.

**Relay bật/tắt chập chờn (jitter):**
Tăng `ACTIVATE_CONFIRMATION_FRAMES` lên 5–8 để lọc false positive tốt hơn.

**Terminal không hiện màu (chỉ thấy mã ANSI lạ):**
Đảm bảo đã cài `colorama` (`pip install colorama`) — cần thiết để màu hiển
thị đúng trên terminal Windows/VS Code.
