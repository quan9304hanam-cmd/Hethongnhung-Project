"""
main.py – Luồng chính của Hệ thống Phát hiện Cháy
══════════════════════════════════════════════════

Quy trình mỗi frame:
  1. Đọc frame từ DroidCam
  2. Chạy YOLOv8 → danh sách detection (lửa / khói)
  3. Biến đổi tọa độ tâm lửa → bird's-eye → xác định Zone
  4. Kiểm tra ngưỡng khẩn cấp (diện tích quá lớn / khói dày)
  5. Cập nhật bộ đếm persistence (tránh false positive / jitter)
  6. Đồng bộ relay ESP32 theo Zone đang bật
  7. Gửi cảnh báo Telegram (nếu cần)
  8. Hiển thị: frame gốc có bbox | ảnh bird's-eye có lưới Zone

Phím tắt trong cửa sổ hiển thị:
  [Q] – Thoát
  [S] – Chụp màn hình và lưu vào logs/
  [T] – Gửi thử thông báo Telegram
  [A] – Tắt tất cả relay ngay lập tức
"""

import cv2
import numpy as np
import time
import logging
import logging.handlers
import sys
import os
from collections import defaultdict
from datetime import datetime

from ultralytics import YOLO

import config
import vision_utils
from communication import ESP32Controller, TelegramAlerter


# ─── Logging setup ────────────────────────────────────────────────────────────

def setup_logging():
    os.makedirs("logs", exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)-7s] %(message)s",
                            datefmt="%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # File (rotating 5MB × 3)
    fh = logging.handlers.RotatingFileHandler(
        config.LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3,
        encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)


# ─── Camera helper ────────────────────────────────────────────────────────────

def open_camera():
    """Mở DroidCam (WiFi hoặc USB). Trả về VideoCapture hoặc None."""
    logger = logging.getLogger(__name__)

    if config.CAMERA_MODE == "wifi":
        cap = cv2.VideoCapture(config.DROIDCAM_WIFI_URL)
        if cap.isOpened():
            logger.info(f"Camera: DroidCam WiFi {config.DROIDCAM_WIFI_URL}")
        else:
            logger.warning("DroidCam WiFi thất bại, thử USB…")
            cap = cv2.VideoCapture(config.DROIDCAM_USB_INDEX)
    else:
        cap = cv2.VideoCapture(config.DROIDCAM_USB_INDEX)

    if not cap.isOpened():
        logger.critical("Không tìm thấy camera!")
        return None

    # Thiết lập độ phân giải
    if config.CAMERA_WIDTH:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  config.CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    logger.info(f"Độ phân giải camera: {w}×{h}")
    return cap


# ─── State machine ────────────────────────────────────────────────────────────

class ZoneStateManager:
    """
    Quản lý trạng thái từng Zone theo cơ chế persistence:
      • Cần ACTIVATE_FRAMES frame phát hiện liên tiếp → BẬT relay
      • Cần CLEAR_FRAMES frame không phát hiện liên tiếp → TẮT relay
    Loại bỏ false positive và jitter của YOLO.
    """

    ACTIVATE_FRAMES = config.ACTIVATE_CONFIRMATION_FRAMES
    CLEAR_FRAMES    = config.CLEAR_CONFIRMATION_FRAMES

    def __init__(self):
        # Bộ đếm frame khi có lửa (reset về 0 khi không phát hiện)
        self._fire_run:  dict[int, int] = defaultdict(int)
        # Bộ đếm frame khi không có lửa (reset về 0 khi phát hiện)
        self._clear_run: dict[int, int] = defaultdict(int)
        # Các Zone đang BẬT relay
        self.active: set = set()

    def update(self, detected_zones: set) -> tuple[set, set]:
        """
        Cập nhật state với tập Zone vừa phát hiện lửa trong frame này.

        Trả về:
            newly_activated : Zone vừa bật
            newly_cleared   : Zone vừa tắt
        """
        newly_activated: set = set()
        newly_cleared:   set = set()

        for z in range(1, config.NUM_ZONES + 1):
            if z in detected_zones:
                self._fire_run[z]  += 1
                self._clear_run[z]  = 0
                if z not in self.active and self._fire_run[z] >= self.ACTIVATE_FRAMES:
                    self.active.add(z)
                    newly_activated.add(z)
            else:
                self._fire_run[z]   = 0
                self._clear_run[z] += 1
                if z in self.active and self._clear_run[z] >= self.CLEAR_FRAMES:
                    self.active.discard(z)
                    newly_cleared.add(z)

        return newly_activated, newly_cleared


# ─── Main loop ────────────────────────────────────────────────────────────────

def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("  HỆ THỐNG PHÁT HIỆN CHÁY – Khởi động")
    logger.info("=" * 60)

    # ── Load model ────────────────────────────────────────────────────────
    logger.info(f"Tải mô hình YOLOv8: {config.MODEL_PATH}")
    if not os.path.exists(config.MODEL_PATH):
        logger.critical(
            f"Không tìm thấy model: {config.MODEL_PATH}\n"
            "  Hãy đặt file .pt vào thư mục models/ và cập nhật MODEL_PATH trong config.py"
        )
        sys.exit(1)
    try:
        model = YOLO(config.MODEL_PATH)
        logger.info(f"Model sẵn sàng. Classes: {model.names}")
    except Exception as e:
        logger.critical(f"Lỗi tải model: {e}")
        sys.exit(1)

    # ── Camera ────────────────────────────────────────────────────────────
    cap = open_camera()
    if cap is None:
        sys.exit(1)

    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # ── Perspective transform ─────────────────────────────────────────────
    src_points = config.load_calibration()
    M, M_inv   = vision_utils.compute_perspective_matrix(src_points)
    logger.info("Ma trận Perspective Transform đã sẵn sàng.")

    # ── ESP32 ─────────────────────────────────────────────────────────────
    esp = ESP32Controller()
    esp_ok = esp.connect()
    if not esp_ok:
        logger.warning("ESP32 chưa kết nối – relay control bị vô hiệu hóa.")
        logger.warning(f"  Kiểm tra cổng COM: {config.ESP32_PORT}")

    # ── Telegram ──────────────────────────────────────────────────────────
    alerter = TelegramAlerter()

    # ── State ─────────────────────────────────────────────────────────────
    zone_mgr      = ZoneStateManager()
    fire_active   = False          # True khi đang có ít nhất 1 Zone bật
    emergency     = False          # True khi đã gửi cảnh báo khẩn cấp
    prev_active   : set = set()

    # FPS counter
    fps_counter   = 0
    fps_timer     = time.time()
    fps           = 0.0

    WIN = "Fire Detection System  |  [Q] Thoat  [S] Chup anh  [T] Test Telegram  [A] All OFF"
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)

    logger.info("Hệ thống đang chạy. Nhấn [Q] trong cửa sổ để thoát.\n")

    while True:
        # ── Đọc frame ───────────────────────────────────────────────────
        ret, frame = cap.read()
        if not ret:
            logger.warning("Không đọc được frame – thử lại…")
            time.sleep(0.05)
            continue

        # ── FPS ─────────────────────────────────────────────────────────
        fps_counter += 1
        now = time.time()
        if now - fps_timer >= 1.0:
            fps = fps_counter / (now - fps_timer)
            fps_counter = 0
            fps_timer   = now

        # ── YOLO inference ───────────────────────────────────────────────
        results = model(frame, verbose=False)[0]

        # ── Parse detections ─────────────────────────────────────────────
        detections: list[dict] = []
        detected_fire_zones: set = set()
        emergency_reason: str | None = None

        for box in results.boxes:
            cls_id = int(box.cls[0])
            conf   = float(box.conf[0])
            xyxy   = box.xyxy[0].tolist()   # [x1, y1, x2, y2]
            x1, y1, x2, y2 = xyxy

            # Lọc theo threshold
            if cls_id == config.CLASS_FIRE and conf < config.FIRE_CONF_THRESHOLD:
                continue
            if cls_id == config.CLASS_SMOKE and conf < config.SMOKE_CONF_THRESHOLD:
                continue

            area_ratio = vision_utils.bbox_area_ratio(
                x1, y1, x2, y2, frame_w, frame_h
            )

            zone = None

            # ── Lửa: xác định Zone qua perspective transform ──────────
            if cls_id == config.CLASS_FIRE:
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                wx, wy = vision_utils.transform_point((cx, cy), M)
                wx, wy = vision_utils.clamp_to_warp(wx, wy)
                zone = vision_utils.get_zone(wx, wy)
                detected_fire_zones.add(zone)

                # Kiểm tra ngưỡng khẩn cấp – diện tích
                if area_ratio >= config.FIRE_AREA_EMERGENCY_RATIO:
                    emergency_reason = (
                        f"Diện tích đám cháy {area_ratio:.0%} khung hình "
                        f"(ngưỡng: {config.FIRE_AREA_EMERGENCY_RATIO:.0%})"
                    )

            # ── Khói: kiểm tra che khuất camera ──────────────────────
            elif cls_id == config.CLASS_SMOKE:
                if area_ratio >= config.SMOKE_AREA_EMERGENCY_RATIO:
                    emergency_reason = (
                        f"Khói dày đặc che khuất {area_ratio:.0%} khung hình "
                        f"(ngưỡng: {config.SMOKE_AREA_EMERGENCY_RATIO:.0%})"
                    )

            detections.append({
                "cls":   cls_id,
                "conf":  conf,
                "bbox":  xyxy,
                "label": config.CLASS_NAMES.get(cls_id, str(cls_id)),
                "zone":  zone,
                "area":  area_ratio,
                # Lưu tọa độ bird's-eye của lửa để vẽ lên warped map
                "warp_pt": (wx, wy) if cls_id == config.CLASS_FIRE else None,
            })

        # ── Cập nhật Zone state ──────────────────────────────────────────
        newly_on, newly_off = zone_mgr.update(detected_fire_zones)

        # ── Đồng bộ relay ESP32 ──────────────────────────────────────────
        if esp.is_connected():
            esp.sync_zones(zone_mgr.active)
        elif esp_ok:
            # Đánh dấu mất kết nối
            esp_ok = False
            logger.error("[ESP32] Mất kết nối!")

        # ── Telegram alerts ──────────────────────────────────────────────
        if zone_mgr.active:
            if not fire_active:
                # Lần đầu phát hiện lửa
                alerter.notify_fire(zone_mgr.active)
                fire_active = True
                logger.warning(f"CHÁY – Zone: {sorted(zone_mgr.active)}")
            elif newly_on:
                # Lan sang Zone mới
                alerter.notify_fire(zone_mgr.active)
                logger.warning(f"CHÁY LAN – Zone mới: {sorted(newly_on)}")

            if emergency_reason and not emergency:
                alerter.notify_emergency(emergency_reason)
                emergency = True
                logger.critical(f"KHẨN CẤP: {emergency_reason}")

        else:
            if fire_active:
                alerter.notify_clear()
                fire_active = False
                emergency   = False
                logger.info("Đám cháy đã tắt – relay reset.")

        prev_active = zone_mgr.active.copy()

        # ── Visualisation ─────────────────────────────────────────────────

        # Khung trái: ảnh gốc + bbox
        vis_orig = vision_utils.draw_detections_on_frame(frame, detections)
        vis_orig = vision_utils.draw_status_bar(
            vis_orig, zone_mgr.active, fps, emergency, esp.is_connected()
        )

        # Khung phải: bird's-eye view + lưới Zone
        warped = vision_utils.warp_frame(frame, M)
        fire_warp_pts = [
            d["warp_pt"] for d in detections
            if d["cls"] == config.CLASS_FIRE and d["warp_pt"] is not None
        ]
        vis_bev = vision_utils.draw_zone_grid(
            warped, zone_mgr.active, fire_warp_pts
        )

        # Tiêu đề ảnh bird's-eye
        cv2.putText(vis_bev, "Bird's-eye View", (8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1, cv2.LINE_AA)

        # Ghép 2 ảnh cạnh nhau (resize bird's-eye về cùng chiều cao)
        bev_target_h = vis_orig.shape[0]
        bev_target_w = int(config.WARP_WIDTH * bev_target_h / config.WARP_HEIGHT)
        vis_bev_rs   = cv2.resize(vis_bev, (bev_target_w, bev_target_h))
        combined     = np.hstack([vis_orig, vis_bev_rs])

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

        elif key == ord('t'):
            logger.info("Gửi thử Telegram…")
            alerter.notify_fire({1})   # Gửi thử với Zone 1

        elif key == ord('a'):
            logger.warning("Yêu cầu tắt tất cả relay thủ công.")
            esp.all_off()
            # Reset state
            zone_mgr = ZoneStateManager()
            fire_active = emergency = False

    # ── Cleanup ───────────────────────────────────────────────────────────────
    logger.info("Đang tắt hệ thống…")
    esp.all_off()
    esp.disconnect()
    cap.release()
    cv2.destroyAllWindows()
    logger.info("Hệ thống đã tắt hoàn toàn.")


if __name__ == "__main__":
    main()