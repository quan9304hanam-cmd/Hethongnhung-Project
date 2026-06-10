"""
vision_utils.py – Xử lý hình ảnh & xác định Zone
══════════════════════════════════════════════════
Cung cấp:
  • Tính ma trận Perspective Transform (nắn thẳng góc nghiêng → bird's-eye)
  • Biến đổi tọa độ điểm / biến đổi toàn bộ frame
  • Xác định Zone (1-4) từ tọa độ trong ảnh đã nắn
  • Hàm vẽ lưới Zone lên ảnh bird's-eye để hiển thị
"""

import cv2
import numpy as np
import config


# ─── Perspective Matrix ───────────────────────────────────────────────────────

def compute_perspective_matrix(
    src_points: list
) -> tuple[np.ndarray, np.ndarray]:
    """
    Tính cặp ma trận Perspective Transform M và nghịch đảo M_inv.

    Tham số
    -------
    src_points : list[list[int]]
        4 điểm nguồn trong ảnh camera (thứ tự bắt buộc):
        [trên-trái, trên-phải, dưới-phải, dưới-trái]

    Trả về
    ------
    M     : ma trận camera-space  → bird's-eye-space
    M_inv : ma trận bird's-eye-space → camera-space  (để vẽ ngược lại)
    """
    src = np.float32(src_points)
    dst = np.float32([
        [0,                   0],
        [config.WARP_WIDTH,   0],
        [config.WARP_WIDTH,   config.WARP_HEIGHT],
        [0,                   config.WARP_HEIGHT],
    ])
    M     = cv2.getPerspectiveTransform(src, dst)
    M_inv = cv2.getPerspectiveTransform(dst, src)
    return M, M_inv


def warp_frame(frame: np.ndarray, M: np.ndarray) -> np.ndarray:
    """
    Áp dụng Perspective Transform lên toàn bộ frame.
    Trả về ảnh bird's-eye kích thước (WARP_WIDTH × WARP_HEIGHT).
    """
    return cv2.warpPerspective(
        frame, M,
        (config.WARP_WIDTH, config.WARP_HEIGHT),
        flags=cv2.INTER_LINEAR
    )


def transform_point(
    pt: tuple[float, float],
    M: np.ndarray
) -> tuple[float, float]:
    """
    Biến đổi một điểm (x, y) từ camera-space sang bird's-eye-space.

    Hiệu quả hơn warp_frame khi chỉ cần tọa độ tâm bbox,
    không cần nắn toàn bộ ảnh.
    """
    p = np.array([[[pt[0], pt[1]]]], dtype=np.float32)   # shape (1,1,2)
    warped = cv2.perspectiveTransform(p, M)               # shape (1,1,2)
    return float(warped[0, 0, 0]), float(warped[0, 0, 1])


def clamp_to_warp(wx: float, wy: float) -> tuple[float, float]:
    """Giữ điểm trong giới hạn ảnh bird's-eye."""
    wx = max(0.0, min(float(config.WARP_WIDTH  - 1), wx))
    wy = max(0.0, min(float(config.WARP_HEIGHT - 1), wy))
    return wx, wy


# ─── Zone Detection ───────────────────────────────────────────────────────────

def get_zone(wx: float, wy: float) -> int:
    """
    Xác định Zone (1–4) từ tọa độ (wx, wy) trong ảnh bird's-eye.

    Bố cục:
      Zone 1 | Zone 2
     ─────────────────
      Zone 3 | Zone 4
    """
    mid_x = config.WARP_WIDTH  / 2.0
    mid_y = config.WARP_HEIGHT / 2.0

    if wx < mid_x:
        return 1 if wy < mid_y else 3
    else:
        return 2 if wy < mid_y else 4


def get_zone_rect(zone: int) -> tuple[int, int, int, int]:
    """
    Trả về (x1, y1, x2, y2) của Zone trong ảnh bird's-eye.
    Dùng để vẽ hoặc kiểm tra overlap.
    """
    mid_x = config.WARP_WIDTH  // 2
    mid_y = config.WARP_HEIGHT // 2
    rects = {
        1: (0,     0,     mid_x, mid_y),
        2: (mid_x, 0,     config.WARP_WIDTH,  mid_y),
        3: (0,     mid_y, mid_x, config.WARP_HEIGHT),
        4: (mid_x, mid_y, config.WARP_WIDTH,  config.WARP_HEIGHT),
    }
    return rects[zone]


# ─── Area Ratio ───────────────────────────────────────────────────────────────

def bbox_area_ratio(
    x1: float, y1: float,
    x2: float, y2: float,
    frame_w: int, frame_h: int
) -> float:
    """
    Tính diện tích bounding box / diện tích toàn khung hình.
    Kết quả trong khoảng [0, 1].
    """
    bbox_area  = abs(x2 - x1) * abs(y2 - y1)
    frame_area = frame_w * frame_h
    return bbox_area / max(frame_area, 1)


# ─── Visualization ────────────────────────────────────────────────────────────

# Màu sắc Zone
_ZONE_COLORS = {
    1: (200, 160,  40),   # vàng-đồng
    2: ( 40, 180, 200),   # xanh lam
    3: (180,  60, 180),   # tím
    4: ( 60, 180,  60),   # xanh lá
}
_ZONE_FIRE_COLOR  = (0, 0, 220)          # đỏ khi có lửa
_ZONE_ALPHA_FILL  = 0.22                 # độ trong suốt nền Zone khi có lửa


def draw_zone_grid(
    warped: np.ndarray,
    active_zones: set,
    fire_points_warped: list | None = None
) -> np.ndarray:
    """
    Vẽ lưới 4 Zone lên ảnh bird's-eye.

    Tham số
    -------
    warped            : ảnh bird's-eye (đã warp)
    active_zones      : tập hợp Zone đang có relay bật  {1, 3, …}
    fire_points_warped: danh sách tọa độ (wx, wy) tâm lửa đã biến đổi
    """
    vis = warped.copy()

    for zone in range(1, config.NUM_ZONES + 1):
        x1, y1, x2, y2 = get_zone_rect(zone)
        on = zone in active_zones

        base_color = _ZONE_FIRE_COLOR if on else _ZONE_COLORS[zone]

        # Tô nền mờ khi Zone đang cháy
        if on:
            overlay = vis.copy()
            cv2.rectangle(overlay, (x1, y1), (x2, y2), _ZONE_FIRE_COLOR, -1)
            cv2.addWeighted(overlay, _ZONE_ALPHA_FILL, vis, 1 - _ZONE_ALPHA_FILL, 0, vis)

        # Viền Zone
        thickness = 3 if on else 1
        cv2.rectangle(vis, (x1, y1), (x2, y2), base_color, thickness)

        # Nhãn Zone
        label = f"Zone {zone}"
        if on:
            label += " [CHAY]"
        cv2.putText(vis, label,
                    (x1 + 8, y1 + 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, base_color, 2,
                    cv2.LINE_AA)

    # Vẽ dấu lửa tại tọa độ đã biến đổi
    if fire_points_warped:
        for (wx, wy) in fire_points_warped:
            wx, wy = int(wx), int(wy)
            cv2.drawMarker(vis, (wx, wy), (0, 0, 255),
                           cv2.MARKER_STAR, 22, 2, cv2.LINE_AA)
            # Vòng tròn bên ngoài để dễ thấy
            cv2.circle(vis, (wx, wy), 14, (0, 80, 255), 1, cv2.LINE_AA)

    return vis


def draw_detections_on_frame(
    frame: np.ndarray,
    detections: list
) -> np.ndarray:
    """
    Vẽ bounding box, nhãn, và tâm của mỗi detection lên frame gốc.

    detections: danh sách dict từ main.py
        {"cls", "conf", "bbox": [x1,y1,x2,y2], "label", "zone"}
    """
    vis = frame.copy()

    for det in detections:
        x1, y1, x2, y2 = map(int, det["bbox"])
        cls   = det["cls"]
        conf  = det["conf"]
        label = det["label"]
        zone  = det.get("zone")

        # Màu: đỏ = lửa, vàng = khói
        color = (0, 50, 255) if cls == config.CLASS_FIRE else (0, 200, 255)

        # Bounding box
        cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)

        # Tag nhãn
        tag = f"{label} {conf:.0%}"
        if zone:
            tag += f"  Z{zone}"
        (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(vis, (x1, y1 - th - 8), (x1 + tw + 6, y1), color, -1)
        cv2.putText(vis, tag, (x1 + 3, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1,
                    cv2.LINE_AA)

        # Tâm bbox
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        cv2.circle(vis, (cx, cy), 5, (0, 255, 80), -1)

    return vis


def draw_status_bar(
    frame: np.ndarray,
    active_zones: set,
    fps: float,
    emergency: bool,
    esp32_ok: bool
) -> np.ndarray:
    """Thanh trạng thái ở cuối frame."""
    vis = frame.copy()
    h, w = vis.shape[:2]
    bar_h = 48

    # Nền thanh
    bar_color = (60, 0, 0) if (active_zones and emergency) else \
                (40, 0, 0) if active_zones else (20, 20, 20)
    cv2.rectangle(vis, (0, h - bar_h), (w, h), bar_color, -1)
    cv2.line(vis, (0, h - bar_h), (w, h - bar_h), (80, 80, 80), 1)

    # Nội dung trạng thái
    if active_zones:
        z_str = "  ".join(f"Zone {z} 🔥" for z in sorted(active_zones))
        prefix = "⚠ KHẨN CẤP" if emergency else "CẢNH BÁO"
        text   = f"[{prefix}]  {z_str}"
        tcolor = (50, 50, 255) if emergency else (50, 120, 255)
    else:
        text   = "✓ Bình thường – Không phát hiện cháy"
        tcolor = (80, 220, 80)

    cv2.putText(vis, text, (10, h - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.62, tcolor, 2, cv2.LINE_AA)

    # FPS + ESP32 status (góc phải)
    esp_txt   = "ESP32: OK" if esp32_ok else "ESP32: --"
    esp_color = (80, 220, 80) if esp32_ok else (100, 100, 100)
    info_txt  = f"FPS:{fps:.1f}  {esp_txt}"
    (iw, _), _ = cv2.getTextSize(info_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.50, 1)
    cv2.putText(vis, info_txt, (w - iw - 10, h - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.50, esp_color, 1, cv2.LINE_AA)

    return vis
