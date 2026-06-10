"""
communication.py – Giao tiếp ESP32 & Cảnh báo Telegram
═══════════════════════════════════════════════════════

Lớp ESP32Controller:
  • Giao thức Serial văn bản đơn giản (115200 baud, kết thúc bằng \\n)
  • PC gửi  : "Z1:ON", "Z2:OFF", "ALL:OFF", "PING"
  • ESP32 trả lời: "OK", "PONG", "READY", "ERR:..."
  • Tự động reconnect nếu mất kết nối

Lớp TelegramAlerter:
  • Gửi cảnh báo cháy thông thường (có cooldown)
  • Gửi cảnh báo khẩn cấp (chỉ 1 lần / sự kiện cháy)
  • Gửi thông báo đã dập tắt
"""

import serial
import time
import threading
import logging
import requests
import config

logger = logging.getLogger(__name__)


# ─── ESP32 Controller ─────────────────────────────────────────────────────────

class ESP32Controller:
    """
    Quản lý giao tiếp Serial với bộ điều khiển Relay ESP32.

    Giao thức:
        Z<n>:ON\\n   → Bật relay Zone n (n = 1-4)
        Z<n>:OFF\\n  → Tắt relay Zone n
        ALL:OFF\\n   → Tắt tất cả relay
        PING\\n      → Kiểm tra kết nối (ESP32 trả "PONG")

    Thread-safe: có thể gọi từ nhiều thread.
    """

    def __init__(self):
        self._ser: serial.Serial | None = None
        self._lock  = threading.Lock()
        # Trạng thái relay hiện tại theo góc nhìn của PC
        self._zone_states: dict[int, bool] = {z: False for z in range(1, 5)}
        self._connected = False

    # ── Kết nối / ngắt kết nối ──────────────────────────────────────────────

    def connect(self,
                port: str      = config.ESP32_PORT,
                baud: int      = config.ESP32_BAUD_RATE,
                timeout: float = config.ESP32_TIMEOUT) -> bool:
        """
        Kết nối đến ESP32 qua cổng Serial.
        Trả về True nếu thành công.
        """
        try:
            self._ser = serial.Serial(port, baud, timeout=timeout)
            # Chờ ESP32 khởi động lại sau khi DTR pulse
            time.sleep(2.5)
            self._ser.reset_input_buffer()
            self._connected = True
            logger.info(f"[ESP32] Kết nối thành công: {port} @ {baud}bps")
            return True
        except serial.SerialException as e:
            logger.error(f"[ESP32] Không thể mở cổng {port}: {e}")
            self._ser = None
            self._connected = False
            return False

    def disconnect(self):
        """Tắt tất cả relay rồi đóng cổng Serial."""
        if self.is_connected():
            self.all_off()
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None
        self._connected = False
        logger.info("[ESP32] Đã ngắt kết nối.")

    def is_connected(self) -> bool:
        return self._connected and self._ser is not None and self._ser.is_open

    def try_reconnect(self) -> bool:
        """Thử kết nối lại 1 lần."""
        logger.warning("[ESP32] Đang thử kết nối lại…")
        self.disconnect()
        return self.connect()

    # ── Gửi lệnh ────────────────────────────────────────────────────────────

    def _send(self, cmd: str) -> str | None:
        """
        Gửi lệnh và đọc 1 dòng phản hồi.
        Trả về chuỗi phản hồi (đã strip) hoặc None nếu lỗi.
        """
        if not self.is_connected():
            return None

        line_bytes = (cmd.strip() + "\n").encode("ascii")

        with self._lock:
            try:
                self._ser.write(line_bytes)
                resp = self._ser.readline().decode("ascii", errors="replace").strip()
                return resp if resp else None
            except serial.SerialException as e:
                logger.error(f"[ESP32] Lỗi ghi Serial: {e}")
                self._connected = False
                return None

    # ── API điều khiển relay ─────────────────────────────────────────────────

    def set_zone(self, zone: int, on: bool) -> bool:
        """
        Bật/tắt relay của Zone.

        Tham số
        -------
        zone : số thứ tự Zone (1-4)
        on   : True = bật, False = tắt

        Trả về True nếu ESP32 phản hồi "OK".
        """
        if not 1 <= zone <= 4:
            logger.warning(f"[ESP32] Zone không hợp lệ: {zone}")
            return False

        state = "ON" if on else "OFF"
        resp  = self._send(f"Z{zone}:{state}")

        if resp and resp.startswith("OK"):
            self._zone_states[zone] = on
            logger.debug(f"[ESP32] Zone {zone} → {state}")
            return True
        else:
            logger.warning(f"[ESP32] set_zone({zone}, {on}): phản hồi không mong đợi: {resp!r}")
            return False

    def all_off(self) -> bool:
        """Tắt tất cả relay trong một lệnh."""
        resp = self._send("ALL:OFF")
        if resp and resp.startswith("OK"):
            for z in self._zone_states:
                self._zone_states[z] = False
            logger.info("[ESP32] ALL:OFF – tất cả relay đã tắt.")
            return True
        return False

    def sync_zones(self, target_zones: set) -> None:
        """
        Đồng bộ trạng thái relay với tập hợp Zone cần BẬT.
        Chỉ gửi lệnh cho các Zone có thay đổi, tránh giao tiếp thừa.

        Tham số
        -------
        target_zones : set[int] – các Zone phải BẬT, phần còn lại sẽ TẮT.
        """
        for z in range(1, config.NUM_ZONES + 1):
            want = z in target_zones
            have = self._zone_states.get(z, False)
            if want != have:
                success = self.set_zone(z, want)
                if not success and not self.is_connected():
                    # Thử kết nối lại nếu mất kết nối
                    if self.try_reconnect():
                        self.set_zone(z, want)
                    break   # Dừng sync, sẽ thử lại frame sau

    def ping(self) -> bool:
        """Kiểm tra ESP32 còn phản hồi không. Trả về True = OK."""
        resp = self._send("PING")
        return resp == "PONG"

    def get_zone_states(self) -> dict:
        """Trả về bản sao trạng thái relay hiện tại."""
        return dict(self._zone_states)


# ─── Telegram Alerter ─────────────────────────────────────────────────────────

class TelegramAlerter:
    """
    Gửi thông báo qua Telegram Bot API.

    Logic:
    • Cảnh báo cháy thông thường: gửi khi phát hiện lần đầu,
      sau đó mỗi ALERT_COOLDOWN giây nếu còn cháy.
    • Cảnh báo khẩn cấp: gửi đúng 1 lần / sự kiện cháy.
    • Thông báo đã dập tắt: gửi khi hệ thống trở về bình thường.

    Tất cả lệnh gọi HTTP chạy trong thread riêng để không block vòng lặp.
    """

    def __init__(self):
        self._last_normal_time: float = 0.0
        self._emergency_sent:   bool  = False
        self._fire_active:      bool  = False

        if config.TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
            logger.warning("[Telegram] Token chưa được cấu hình – thông báo sẽ bị tắt.")

    # ── Internal ─────────────────────────────────────────────────────────────

    def _is_configured(self) -> bool:
        return (config.TELEGRAM_BOT_TOKEN not in ("YOUR_BOT_TOKEN_HERE", "")
                and config.TELEGRAM_CHAT_ID not in ("YOUR_CHAT_ID_HERE", ""))

    def _post_message(self, text: str) -> bool:
        """Gửi tin nhắn đến Telegram (blocking). Gọi từ thread phụ."""
        url = (f"https://api.telegram.org"
               f"/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage")
        payload = {
            "chat_id":    config.TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "HTML",
        }
        try:
            r = requests.post(url, json=payload, timeout=10)
            if r.ok:
                logger.info("[Telegram] Đã gửi thông báo.")
                return True
            else:
                logger.error(f"[Telegram] HTTP {r.status_code}: {r.text[:120]}")
                return False
        except requests.RequestException as e:
            logger.error(f"[Telegram] Lỗi kết nối: {e}")
            return False

    def _send_async(self, text: str):
        """Gửi không đồng bộ để không chặn vòng lặp chính."""
        if not self._is_configured():
            return
        t = threading.Thread(target=self._post_message, args=(text,), daemon=True)
        t.start()

    # ── Public API ───────────────────────────────────────────────────────────

    def notify_fire(self, zones: set) -> None:
        """
        Gửi cảnh báo cháy thông thường.
        Sẽ không gửi nếu chưa hết thời gian cooldown.
        """
        now = time.time()
        if now - self._last_normal_time < config.TELEGRAM_ALERT_COOLDOWN_SEC:
            return

        zone_str = ", ".join(f"<b>Zone {z}</b>" for z in sorted(zones))
        msg = (
            "🔥 <b>PHÁT HIỆN CHÁY</b>\n"
            f"📍 Vị trí: {zone_str}\n"
            f"⏰ {_now_str()}\n"
            "🚿 Hệ thống đã kích hoạt thiết bị chữa cháy tại khu vực tương ứng."
        )
        self._send_async(msg)
        self._last_normal_time = now
        self._fire_active = True

    def notify_emergency(self, reason: str) -> None:
        """
        Gửi cảnh báo KHẨN CẤP.
        Chỉ gửi đúng 1 lần trong suốt sự kiện cháy (tránh spam).
        """
        if self._emergency_sent:
            return

        msg = (
            "🚨 <b>KHẨN CẤP – ĐÁM CHÁY LỚN</b>\n"
            f"⚠️ Lý do: {reason}\n"
            f"⏰ {_now_str()}\n"
            "☎️ <b>Gọi ngay lực lượng PCCC: 114</b>"
        )
        self._send_async(msg)
        self._emergency_sent = True

    def notify_clear(self) -> None:
        """Gửi thông báo đám cháy đã được dập tắt."""
        if not self._fire_active:
            return

        msg = (
            "✅ <b>Đám cháy đã được dập tắt</b>\n"
            f"⏰ {_now_str()}\n"
            "🟢 Hệ thống trở về trạng thái giám sát bình thường."
        )
        self._send_async(msg)
        self._reset()

    def _reset(self):
        """Reset trạng thái sau khi đám cháy đã tắt."""
        self._emergency_sent = False
        self._fire_active    = False


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now_str() -> str:
    """Chuỗi thời gian hiện tại dạng dd/mm/yyyy HH:MM:SS."""
    return time.strftime("%d/%m/%Y %H:%M:%S")
