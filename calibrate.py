"""
calibrate.py – Công cụ hiệu chuẩn phối cảnh tương tác
═══════════════════════════════════════════════════════

Chạy file này MỘT LẦN để xác định 4 góc của khu vực giám sát
trong ảnh camera nghiêng. Kết quả lưu vào calibration.json
và sẽ được main.py tự động tải khi khởi động.

Hướng dẫn click:
  1. Góc trên-trái  (Top-Left)  của khu vực sàn
  2. Góc trên-phải  (Top-Right)
  3. Góc dưới-phải  (Bottom-Right)
  4. Góc dưới-trái  (Bottom-Left)

Phím tắt:
  [S]   – Lưu & thoát
  [R]   – Xóa & click lại từ đầu
  [P]   – Xem trước bird's-eye (sau khi đã click đủ 4 điểm)
  [Q]   – Thoát không lưu
"""

import cv2
import json
import numpy as np
import sys
import config
import vision_utils

# ─── Hằng số giao diện ───────────────────────────────────────────────────────
WIN_MAIN    = "Calibration – Click 4 goc (TL → TR → BR → BL)   [S]Luu  [R]Lai  [P]Preview  [Q]Thoat"
WIN_PREVIEW = "Bird's-eye Preview – Nhan phim bat ky de dong"

POINT_LABELS = [
    "1: Top-Left  (Trên-Trái)",
    "2: Top-Right (Trên-Phải)",
    "3: Bottom-Right (Dưới-Phải)",
    "4: Bottom-Left  (Dưới-Trái)",
]
# Mỗi điểm một màu để phân biệt dễ
POINT_COLORS = [
    (0,   230,  0),    # xanh lá
    (0,   200, 255),   # xanh lam
    (0,    80, 255),   # cam
    (200,   0, 255),   # tím
]

# ─── Global state ─────────────────────────────────────────────────────────────
clicked_points: list = []   # tối đa 4 phần tử


# ─── Mouse callback ───────────────────────────────────────────────────────────

def _mouse_cb(event, x, y, flags, param):
    global clicked_points
    if event == cv2.EVENT_LBUTTONDOWN and len(clicked_points) < 4:
        clicked_points.append([x, y])
        idx = len(clicked_points) - 1
        print(f"  ✔  Điểm {idx + 1} đã click: ({x}, {y})  ← {POINT_LABELS[idx]}")


# ─── Vẽ giao diện hiệu chuẩn ─────────────────────────────────────────────────

def _draw_ui(frame: np.ndarray) -> np.ndarray:
    vis = frame.copy()
    h, w = vis.shape[:2]
    n = len(clicked_points)

    # Thanh hướng dẫn phía trên
    cv2.rectangle(vis, (0, 0), (w, 44), (25, 25, 25), -1)
    if n < 4:
        instr = f"Buoc {n + 1}/4: Click {POINT_LABELS[n]}"
    else:
        instr = "Xong! Nhan [S] luu  |  [P] preview  |  [R] chon lai"
    cv2.putText(vis, instr, (8, 29),
                cv2.FONT_HERSHEY_SIMPLEX, 0.62, (240, 220, 80), 1, cv2.LINE_AA)

    # Vẽ các điểm đã click
    for i, pt in enumerate(clicked_points):
        px, py = pt[0], pt[1]
        col = POINT_COLORS[i]
        cv2.circle(vis, (px, py), 9, col, -1)
        cv2.circle(vis, (px, py), 9, (255, 255, 255), 1)
        cv2.putText(vis, str(i + 1),
                    (px + 13, py - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2, cv2.LINE_AA)

    # Đường nối các điểm
    if len(clicked_points) >= 2:
        pts_np = np.array(clicked_points, np.int32).reshape((-1, 1, 2))
        cv2.polylines(vis, [pts_np],
                      isClosed=(len(clicked_points) == 4),
                      color=(0, 240, 240), thickness=2)

    return vis


# ─── Xem trước bird's-eye ─────────────────────────────────────────────────────

def _show_preview(frame: np.ndarray, pts: list):
    M, _ = vision_utils.compute_perspective_matrix(pts)
    warped = vision_utils.warp_frame(frame, M)
    warped = vision_utils.draw_zone_grid(warped, active_zones=set())

    # Thêm nhãn Zone rõ hơn
    h, w = warped.shape[:2]
    cv2.line(warped, (w // 2, 0), (w // 2, h), (180, 180, 180), 1)
    cv2.line(warped, (0, h // 2), (w, h // 2), (180, 180, 180), 1)

    cv2.imshow(WIN_PREVIEW, warped)
    print("\n  [Preview] Đây là cách hệ thống nhìn từ trên xuống.")
    print("  Kiểm tra: các góc của mặt bằng có khớp với 4 góc ảnh không?")
    print("  Nhấn phím bất kỳ để đóng preview.")
    cv2.waitKey(0)
    cv2.destroyWindow(WIN_PREVIEW)


# ─── Lưu calibration ─────────────────────────────────────────────────────────

def _save(pts: list):
    data = {"src_points": pts}
    with open(config.CALIBRATION_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\n✅  Đã lưu calibration vào: {config.CALIBRATION_FILE}")
    print(f"   src_points = {pts}\n")


# ─── Mở camera ───────────────────────────────────────────────────────────────

def _open_camera():
    """Thử DroidCam WiFi trước, fallback về USB."""
    if config.CAMERA_MODE == "wifi":
        cap = cv2.VideoCapture(config.DROIDCAM_WIFI_URL)
        if cap.isOpened():
            print(f"[Camera] DroidCam WiFi: {config.DROIDCAM_WIFI_URL}")
            return cap
        print("⚠  DroidCam WiFi không kết nối được. Thử USB…")

    cap = cv2.VideoCapture(config.DROIDCAM_USB_INDEX)
    if cap.isOpened():
        print(f"[Camera] USB index {config.DROIDCAM_USB_INDEX}")
        return cap

    print("❌  Không tìm thấy camera nào!")
    return None


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    global clicked_points

    cap = _open_camera()
    if cap is None:
        sys.exit(1)

    # Thiết lập độ phân giải camera
    if config.CAMERA_WIDTH:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  config.CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)

    cv2.namedWindow(WIN_MAIN, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(WIN_MAIN, _mouse_cb)

    print("\n" + "=" * 56)
    print("  CALIBRATION TOOL – Hệ thống phát hiện cháy")
    print("=" * 56)
    print("Click lần lượt 4 góc KHU VỰC SÀN trong ảnh camera:")
    for lbl in POINT_LABELS:
        print(f"  • {lbl}")
    print("\nPhím tắt:  [S] Lưu  |  [R] Làm lại  |  [P] Preview  |  [Q] Thoát")
    print("-" * 56 + "\n")

    last_frame = None

    while True:
        ret, frame = cap.read()
        if ret:
            last_frame = frame.copy()
        if last_frame is None:
            continue

        vis = _draw_ui(last_frame)
        cv2.imshow(WIN_MAIN, vis)

        key = cv2.waitKey(25) & 0xFF

        if key == ord('q'):
            print("↩  Thoát không lưu.")
            break

        elif key == ord('r'):
            clicked_points = []
            print("↺  Đã xóa – click lại từ đầu.")

        elif key == ord('p'):
            if len(clicked_points) == 4:
                _show_preview(last_frame, clicked_points)
            else:
                print(f"⚠  Cần đủ 4 điểm. Hiện tại: {len(clicked_points)}/4")

        elif key == ord('s'):
            if len(clicked_points) == 4:
                _show_preview(last_frame, clicked_points)
                _save(clicked_points)
                break
            else:
                print(f"⚠  Cần đủ 4 điểm trước khi lưu. Hiện tại: {len(clicked_points)}/4")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
