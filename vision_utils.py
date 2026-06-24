"""
vision_utils.py – Tính tỷ lệ pixel lửa & phân loại kích thước
═══════════════════════════════════════════════════════════════
Không còn Perspective Transform — Zone được xác định trực tiếp bởi
camera nào phát hiện ra lửa (Cam 1 → Zone 1, Cam 2 → Zone 2).

Cung cấp:
  • compute_fire_pixel_ratio() – tỷ lệ % pixel khung hình bị lửa che
    (dùng mask để không đếm trùng vùng các bbox chồng lên nhau)
  • classify_fire_size()        – "nho" / "vua" / "lon" theo ngưỡng config
  • draw_detections_on_frame()  – vẽ bbox lửa + nhãn lên frame
  • draw_zone_status_bar()      – thanh trạng thái Zone phía dưới frame
  • make_offline_frame()        – khung hình báo "camera mất kết nối"
"""

import cv2
import numpy as np
import config


# ─── Tính tỷ lệ pixel lửa ─────────────────────────────────────────────────────

def compute_fire_pixel_ratio(
    fire_bboxes: list,
    frame_w: int,
    frame_h: int
) -> float:
    """
    Tính % pixel của khung hình bị (các) bounding box lửa che phủ.

    Dùng mask nhị phân để xử lý đúng trường hợp nhiều bbox chồng lấn –
    không bị đếm trùng diện tích như khi cộng dồn area từng box.

    Tham số
    -------
    fire_bboxes : list[[x1, y1, x2, y2], ...]
    frame_w, frame_h : kích thước khung hình

    Trả về
    ------
    float trong [0.0, 1.0] – tỷ lệ pixel bị che.
    """
    if not fire_bboxes:
        return 0.0

    mask = np.zeros((frame_h, frame_w), dtype=np.uint8)

    for (x1, y1, x2, y2) in fire_bboxes:
        x1c = max(0, min(frame_w,  int(round(x1))))
        x2c = max(0, min(frame_w,  int(round(x2))))
        y1c = max(0, min(frame_h,  int(round(y1))))
        y2c = max(0, min(frame_h,  int(round(y2))))
        if x2c > x1c and y2c > y1c:
            mask[y1c:y2c, x1c:x2c] = 1

    covered_pixels = int(mask.sum())
    total_pixels   = frame_w * frame_h
    return covered_pixels / max(total_pixels, 1)


# ─── Phân loại kích thước lửa ─────────────────────────────────────────────────

def classify_fire_size(ratio: float) -> str | None:
    """
    Phân loại kích thước lửa theo % pixel khung hình.

    Trả về: "nho" | "vua" | "lon"   (None nếu ratio <= 0, không có lửa)
    """
    if ratio <= 0:
        return None
    if ratio < config.SMALL_FIRE_MAX_RATIO:
        return "nho"
    elif ratio < config.MEDIUM_FIRE_MAX_RATIO:
        return "vua"
    else:
        return "lon"


# Nhãn tiếng Việt đầy đủ dấu, dùng khi hiển thị
SIZE_LABEL_VI = {
    "nho": "nhỏ",
    "vua": "vừa",
    "lon": "lớn",
}


# ─── Visualization ────────────────────────────────────────────────────────────

_SIZE_BOX_COLOR = {
    "nho": (0, 200,   0),     # xanh lá
    "vua": (0, 200, 255),     # vàng-cam
    "lon": (0,   0, 255),     # đỏ
}


def draw_detections_on_frame(
    frame: np.ndarray,
    detections: list,
    size_label: str | None
) -> np.ndarray:
    """
    Vẽ bounding box lửa lên frame. Màu bbox đổi theo kích thước lửa
    hiện tại của TOÀN khung hình (nho/vua/lon) để dễ quan sát nhanh.
    """
    vis = frame.copy()
    color = _SIZE_BOX_COLOR.get(size_label, (0, 200, 0))

    for det in detections:
        x1, y1, x2, y2 = map(int, det["bbox"])
        conf = det["conf"]

        cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)

        tag = f"Lua {conf:.0%}"
        (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(vis, (x1, y1 - th - 8), (x1 + tw + 6, y1), color, -1)
        cv2.putText(vis, tag, (x1 + 3, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1,
                    cv2.LINE_AA)

    return vis


def draw_zone_status_bar(
    frame: np.ndarray,
    zone_label: str,
    is_active: bool,
    ratio: float,
    size_label: str | None,
    fps: float
) -> np.ndarray:
    """Thanh trạng thái phía dưới mỗi khung camera."""
    vis = frame.copy()
    h, w = vis.shape[:2]
    bar_h = 42

    bar_color = (0, 0, 80) if is_active else (20, 20, 20)
    cv2.rectangle(vis, (0, h - bar_h), (w, h), bar_color, -1)
    cv2.line(vis, (0, h - bar_h), (w, h - bar_h), (80, 80, 80), 1)

    if is_active:
        size_vi = SIZE_LABEL_VI.get(size_label, "?")
        text = f"🔥 {zone_label}: CHÁY ({size_vi}, {ratio*100:.1f}%)"
        tcolor = (60, 60, 255)
    else:
        text = f"✓ {zone_label}: Bình thường"
        tcolor = (90, 220, 90)

    cv2.putText(vis, text, (10, h - 13),
                cv2.FONT_HERSHEY_SIMPLEX, 0.58, tcolor, 2, cv2.LINE_AA)

    fps_txt = f"{fps:.1f} FPS"
    (fw, _), _ = cv2.getTextSize(fps_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.putText(vis, fps_txt, (w - fw - 10, h - 13),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1, cv2.LINE_AA)

    return vis


def make_offline_frame(width: int, height: int, zone_label: str) -> np.ndarray:
    """Khung hình hiển thị khi camera của Zone bị mất kết nối."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    text1 = f"{zone_label}"
    text2 = "MAT KET NOI CAMERA"

    (tw1, th1), _ = cv2.getTextSize(text1, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
    (tw2, th2), _ = cv2.getTextSize(text2, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)

    cx, cy = width // 2, height // 2
    cv2.putText(frame, text1, (cx - tw1 // 2, cy - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (100, 100, 100), 2, cv2.LINE_AA)
    cv2.putText(frame, text2, (cx - tw2 // 2, cy + 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (60, 60, 200), 2, cv2.LINE_AA)
    return frame
