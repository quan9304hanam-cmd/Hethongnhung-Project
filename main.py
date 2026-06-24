"""
main.py – Luồng chính: Hệ thống báo cháy 2 Camera (Zone 1 = PC, Zone 2 = DroidCam)
══════════════════════════════════════════════════════════════════════════════════

Quy trình mỗi vòng lặp:
  1. Đọc frame từ Camera 1 (PC) và Camera 2 (DroidCam)
  2. Chạy YOLOv8 (batch cả 2 frame trong 1 lần inference cho nhanh)
  3. Với mỗi Zone: tính % pixel bị lửa che → phân loại nhỏ/vừa/lớn
  4. In cảnh báo màu lên terminal theo đúng mức độ
  5. Cập nhật state máy trạng thái từng Zone (debounce BẬT, độ trễ 5s TẮT)
  6. Đồng bộ lệnh xuống ESP32: đèn Zone 1 (chân X), đèn Zone 2 (chân Y), chuông
  7. Hiển thị 2 khung hình camera kèm bounding box + thanh trạng thái

Phím tắt trong cửa sổ hiển thị:
  [Q] – Thoát
  [S] – Chụp ảnh cả 2 khung, lưu vào logs/
  [A] – Tắt tất cả relay ngay lập tức (test khẩn cấp)
"""

import cv2
import numpy as np
import time
import logging
import logging.handlers
import sys
import os
from datetime import datetime

from ultralytics import YOLO
from colorama import init as colorama_init, Fore, Style

import config
import vision_utils
from communication import ESP32Controller

colorama_init(autoreset=True)


# ─── Logging setup ────────────────────────────────────────────────────────────

def setup_logging():
    os.makedirs("logs", exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)-7s] %(message)s",
                            datefmt="%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    fh = logging.handlers.RotatingFileHandler(
        config.LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3,
        encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)


# ─── In cảnh báo màu lên terminal ─────────────────────────────────────────────

_SIZE_COLOR = {
    "nho": Fore.GREEN,
    "vua": Fore.YELLOW,
    "lon": Fore.RED + Style.BRIGHT,
}


def print_fire_alert(zone_id: int, size_label: str, ratio: float):
    """
    In cảnh báo đúng định dạng yêu cầu: "lửa <nhỏ/vừa/lớn> ở zone <x>"
    kèm thêm thời gian và % pixel để dễ theo dõi.
    """
    size_vi = vision_utils.SIZE_LABEL_VI[size_label]
    color   = _SIZE_COLOR[size_label]
    ts      = time.strftime("%H:%M:%S")
    msg     = f"lửa {size_vi} ở zone {zone_id}"
    print(f"{color}[{ts}] 🔥 {msg}  (chiếm {ratio*100:.1f}% khung hình){Style.RESET_ALL}")


def print_zone_activated(zone_id: int):
    print(f"{Fore.RED}{Style.BRIGHT}[{time.strftime('%H:%M:%S')}] "
          f"🚨 KÍCH HOẠT báo động Zone {zone_id} – Bật đèn + chuông!{Style.RESET_ALL}")


def print_zone_deactivated(zone_id: int):
    print(f"{Fore.GREEN}[{time.strftime('%H:%M:%S')}] "
          f"✅ Zone {zone_id}: hết lửa quá 5 giây – Tắt đèn.{Style.RESET_ALL}")


# ─── Camera helpers ───────────────────────────────────────────────────────────

def open_camera1():
    """Mở Camera 1 – Webcam PC."""
    cap = cv2.VideoCapture(config.CAM1_SOURCE)
    if config.CAMERA_WIDTH:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  config.CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
    return cap if cap.isOpened() else None


def open_camera2():
    """Mở Camera 2 – DroidCam (WiFi ưu tiên, fallback USB)."""
    if config.CAM2_MODE == "wifi":
        cap = cv2.VideoCapture(config.DROIDCAM_WIFI_URL)
        if cap.isOpened():
            return cap
        logging.getLogger(__name__).warning("DroidCam WiFi thất bại, thử USB…")

    cap = cv2.VideoCapture(config.DROIDCAM_USB_INDEX)
    if config.CAMERA_WIDTH:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  config.CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
    return cap if cap.isOpened() else None


def safe_read(cap):
    """Đọc 1 frame an toàn. Trả về None nếu lỗi hoặc cap đã đóng."""
    if cap is None or not cap.isOpened():
        return None
    ret, frame = cap.read()
    return frame if ret else None


# ─── State machine cho từng Zone ──────────────────────────────────────────────

class ZoneAlarmState:
    """
    Quản lý trạng thái BẬT/TẮT của 1 Zone với:
      • Debounce BẬT: cần ACTIVATE_CONFIRMATION_FRAMES frame liên tiếp có lửa
      • Độ trễ TẮT  : chờ OFF_DELAY_SECONDS giây sau khi KHÔNG còn thấy lửa
    """

    def __init__(self, zone_id: int):
        self.zone_id = zone_id
        self.active  = False          # Đèn/chuông của Zone này đang BẬT?
        self._frames_seen   = 0
        self._last_seen_time = 0.0
        self._last_print_time = 0.0
        self._last_size_label = None

    def update(self, fire_present: bool, ratio: float, size_label, now: float):
        """
        Cập nhật trạng thái dựa trên kết quả phát hiện frame hiện tại.
        Trả về (newly_activated: bool, newly_deactivated: bool)
        """
        newly_on  = False
        newly_off = False

        if fire_present:
            self._frames_seen += 1
            self._last_seen_time = now

            if not self.active and self._frames_seen >= config.ACTIVATE_CONFIRMATION_FRAMES:
                self.active = True
                newly_on = True
        else:
            self._frames_seen = 0
            if self.active and (now - self._last_seen_time) >= config.OFF_DELAY_SECONDS:
                self.active = False
                newly_off = True

        # In cảnh báo kích thước lửa lên terminal (có cooldown chống spam)
        if fire_present and size_label:
            changed     = size_label != self._last_size_label
            cooldown_ok = (now - self._last_print_time) >= config.PRINT_COOLDOWN_SEC
            if changed or cooldown_ok:
                print_fire_alert(self.zone_id, size_label, ratio)
                self._last_print_time = now
            self._last_size_label = size_label
        else:
            self._last_size_label = None

        return newly_on, newly_off


# ─── Xử lý detections của 1 Zone ──────────────────────────────────────────────

def process_zone_results(results, frame_w: int, frame_h: int) -> tuple[list, float, str | None]:
    """
    Trích xuất detection lửa từ kết quả YOLO, tính tỷ lệ pixel và phân loại.

    Trả về (detections, ratio, size_label)
    """
    detections   = []
    fire_bboxes  = []

    for box in results.boxes:
        cls_id = int(box.cls[0])
        conf   = float(box.conf[0])

        if cls_id != config.CLASS_FIRE or conf < config.FIRE_CONF_THRESHOLD:
            continue

        xyxy = box.xyxy[0].tolist()
        detections.append({"bbox": xyxy, "conf": conf})
        fire_bboxes.append(xyxy)

    ratio      = vision_utils.compute_fire_pixel_ratio(fire_bboxes, frame_w, frame_h)
    size_label = vision_utils.classify_fire_size(ratio)
    return detections, ratio, size_label


# ─── Main loop ────────────────────────────────────────────────────────────────

def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 64)
    logger.info("  HỆ THỐNG BÁO CHÁY 2 CAMERA – Zone 1 (PC) / Zone 2 (DroidCam)")
    logger.info("=" * 64)

    # ── Load model ────────────────────────────────────────────────────────
    logger.info(f"Tải mô hình YOLOv8: {config.MODEL_PATH}")
    if not os.path.exists(config.MODEL_PATH):
        logger.critical(
            f"Không tìm thấy model: {config.MODEL_PATH}\n"
            "  Đặt file .pt vào thư mục models/ và cập nhật MODEL_PATH trong config.py"
        )
        sys.exit(1)
    try:
        model = YOLO(config.MODEL_PATH)
        logger.info(f"Model sẵn sàng. Classes: {model.names}")
    except Exception as e:
        logger.critical(f"Lỗi tải model: {e}")
        sys.exit(1)

    # ── Cameras ───────────────────────────────────────────────────────────
    cap1 = open_camera1()
    cap2 = open_camera2()

    if cap1 is None:
        logger.error("Không mở được Camera 1 (PC) – Zone 1 sẽ hiển thị OFFLINE.")
    else:
        logger.info("Camera 1 (PC) – Zone 1: OK")

    if cap2 is None:
        logger.error("Không mở được Camera 2 (DroidCam) – Zone 2 sẽ hiển thị OFFLINE.")
    else:
        logger.info("Camera 2 (DroidCam) – Zone 2: OK")

    if cap1 is None and cap2 is None:
        logger.critical("Cả 2 camera đều không mở được. Dừng chương trình.")
        sys.exit(1)

    frame_w, frame_h = config.CAMERA_WIDTH, config.CAMERA_HEIGHT

    # ── ESP32 ─────────────────────────────────────────────────────────────
    esp = ESP32Controller()
    esp_ok = esp.connect()
    if not esp_ok:
        logger.warning(f"ESP32 chưa kết nối (cổng {config.ESP32_PORT}) – relay bị vô hiệu hóa.")

    # ── State ─────────────────────────────────────────────────────────────
    zone1 = ZoneAlarmState(1)
    zone2 = ZoneAlarmState(2)

    fps_counter, fps_timer, fps = 0, time.time(), 0.0

    WIN = "He thong bao chay 2 Camera  |  [Q] Thoat  [S] Chup anh  [A] Tat tat ca"
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)

    logger.info("Hệ thống đang chạy. Nhấn [Q] trong cửa sổ để thoát.\n")

    while True:
        now = time.time()

        # ── Đọc frame từ 2 camera ───────────────────────────────────────
        frame1 = safe_read(cap1)
        frame2 = safe_read(cap2)

        # FPS
        fps_counter += 1
        if now - fps_timer >= 1.0:
            fps = fps_counter / (now - fps_timer)
            fps_counter, fps_timer = 0, now

        # ── YOLO inference (batch 2 frame hợp lệ trong 1 lần forward) ─────
        batch, batch_zone_ids = [], []
        if frame1 is not None:
            batch.append(frame1); batch_zone_ids.append(1)
        if frame2 is not None:
            batch.append(frame2); batch_zone_ids.append(2)

        results_map = {}
        if batch:
            results_list = model(batch, verbose=False)
            results_map = dict(zip(batch_zone_ids, results_list))

        # ── Xử lý Zone 1 ───────────────────────────────────────────────────
        if frame1 is not None and 1 in results_map:
            det1, ratio1, size1 = process_zone_results(results_map[1], frame_w, frame_h)
            fire1 = size1 is not None
        else:
            det1, ratio1, size1, fire1 = [], 0.0, None, False

        # ── Xử lý Zone 2 ───────────────────────────────────────────────────
        if frame2 is not None and 2 in results_map:
            det2, ratio2, size2 = process_zone_results(results_map[2], frame_w, frame_h)
            fire2 = size2 is not None
        else:
            det2, ratio2, size2, fire2 = [], 0.0, None, False

        # ── Cập nhật state machine từng Zone ─────────────────────────────
        z1_on, z1_off = zone1.update(fire1, ratio1, size1, now)
        z2_on, z2_off = zone2.update(fire2, ratio2, size2, now)

        if z1_on:  print_zone_activated(1)
        if z2_on:  print_zone_activated(2)
        if z1_off: print_zone_deactivated(1)
        if z2_off: print_zone_deactivated(2)

        # ── Đồng bộ relay ESP32 ───────────────────────────────────────────
        buzzer_on = zone1.active or zone2.active
        if esp.is_connected():
            esp.sync(zone1.active, zone2.active, buzzer_on)
        elif esp_ok:
            esp_ok = False
            logger.error("[ESP32] Mất kết nối!")

        # ── Hiển thị ──────────────────────────────────────────────────────
        if frame1 is not None:
            vis1 = vision_utils.draw_detections_on_frame(frame1, det1, size1)
        else:
            vis1 = vision_utils.make_offline_frame(frame_w, frame_h, "Zone 1 (PC)")
        vis1 = vision_utils.draw_zone_status_bar(vis1, "Zone 1 (PC)", zone1.active, ratio1, size1, fps)

        if frame2 is not None:
            vis2 = vision_utils.draw_detections_on_frame(frame2, det2, size2)
        else:
            vis2 = vision_utils.make_offline_frame(frame_w, frame_h, "Zone 2 (DroidCam)")
        vis2 = vision_utils.draw_zone_status_bar(vis2, "Zone 2 (DroidCam)", zone2.active, ratio2, size2, fps)

        # Resize đồng nhất chiều cao rồi ghép ngang
        h = max(vis1.shape[0], vis2.shape[0])
        if vis1.shape[0] != h:
            vis1 = cv2.resize(vis1, (int(vis1.shape[1] * h / vis1.shape[0]), h))
        if vis2.shape[0] != h:
            vis2 = cv2.resize(vis2, (int(vis2.shape[1] * h / vis2.shape[0]), h))

        combined = np.hstack([vis1, vis2])
        cv2.imshow(WIN, combined)

        # ── Phím tắt ──────────────────────────────────────────────────────
        key = cv2.waitKey(1) & 0xFF

        if key == ord('q'):
            logger.info("Thoát theo yêu cầu.")
            break

        elif key == ord('s'):
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = f"logs/screenshot_{ts}.jpg"
            cv2.imwrite(path, combined)
            logger.info(f"Đã lưu ảnh: {path}")

        elif key == ord('a'):
            logger.warning("Yêu cầu tắt tất cả relay thủ công.")
            esp.all_off()
            zone1 = ZoneAlarmState(1)
            zone2 = ZoneAlarmState(2)

    # ── Cleanup ───────────────────────────────────────────────────────────────
    logger.info("Đang tắt hệ thống…")
    esp.all_off()
    esp.disconnect()
    if cap1: cap1.release()
    if cap2: cap2.release()
    cv2.destroyAllWindows()
    logger.info("Hệ thống đã tắt hoàn toàn.")


if __name__ == "__main__":
    main()
