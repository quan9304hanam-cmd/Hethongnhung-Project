"""
communication.py – Giao tiếp ESP32 (2 đèn Zone + 1 chuông báo cháy)
══════════════════════════════════════════════════════════════════

Giao thức Serial (115200 baud, ASCII, kết thúc '\\n'):

    PC gửi        │ ESP32 trả lời          │ Mô tả
   ───────────────┼────────────────────────┼─────────────────────────────
    PING          │ PONG                   │ Kiểm tra kết nối
    Z1:ON / OFF   │ OK                     │ Đèn Zone 1 (chân X)
    Z2:ON / OFF   │ OK                     │ Đèn Zone 2 (chân Y)
    BUZZER:ON/OFF │ OK                     │ Chuông báo cháy
    ALL:OFF       │ OK                     │ Tắt tất cả (2 đèn + chuông)
    STATUS        │ Z1:0,Z2:1,BUZZER:1     │ Đọc trạng thái hiện tại

ESP32 chỉ đóng vai trò "tay chân" – mọi logic quyết định BẬT/TẮT
(kể cả độ trễ 5 giây) đều được Python (laptop) tính toán và gửi lệnh
tường minh. Điều này giúp firmware ESP32 đơn giản, dễ debug.
"""

import serial
import threading
import time
import logging
import config

logger = logging.getLogger(__name__)


class ESP32Controller:
    """
    Quản lý giao tiếp Serial với ESP32 điều khiển 2 đèn Zone + 1 chuông.
    Thread-safe, tự động chỉ gửi lệnh khi trạng thái THAY ĐỔI.
    """

    def __init__(self):
        self._ser: serial.Serial | None = None
        self._lock = threading.Lock()
        self._connected = False

        # Trạng thái relay theo góc nhìn của PC (cache để tránh gửi lệnh thừa)
        self._zone_light_state: dict[int, bool] = {1: False, 2: False}
        self._buzzer_state: bool = False

    # ── Kết nối / ngắt kết nối ──────────────────────────────────────────────

    def connect(self,
                port: str      = config.ESP32_PORT,
                baud: int      = config.ESP32_BAUD_RATE,
                timeout: float = config.ESP32_TIMEOUT) -> bool:
        """Kết nối đến ESP32. Trả về True nếu thành công."""
        try:
            self._ser = serial.Serial(port, baud, timeout=timeout)
            time.sleep(2.5)   # Chờ ESP32 reset xong sau khi mở cổng Serial
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
        logger.warning("[ESP32] Đang thử kết nối lại…")
        self.disconnect()
        return self.connect()

    # ── Gửi lệnh thô ─────────────────────────────────────────────────────────

    def _send(self, cmd: str) -> str | None:
        """Gửi 1 lệnh, đọc 1 dòng phản hồi. None nếu lỗi."""
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

    # ── API điều khiển ────────────────────────────────────────────────────────

    def set_zone_light(self, zone: int, on: bool) -> bool:
        """
        Bật/tắt đèn của Zone (1 hoặc 2).
        Chỉ gửi lệnh thật khi trạng thái thay đổi so với lần trước.
        """
        if zone not in (1, 2):
            logger.warning(f"[ESP32] Zone không hợp lệ: {zone}")
            return False

        if self._zone_light_state[zone] == on:
            return True   # Không có gì thay đổi – không cần gửi lệnh

        cmd   = f"Z{zone}:{'ON' if on else 'OFF'}"
        resp  = self._send(cmd)

        if resp and resp.startswith("OK"):
            self._zone_light_state[zone] = on
            logger.info(f"[ESP32] Đèn Zone {zone} → {'BẬT' if on else 'TẮT'}")
            return True

        logger.warning(f"[ESP32] set_zone_light({zone}, {on}) thất bại: {resp!r}")
        return False

    def set_buzzer(self, on: bool) -> bool:
        """Bật/tắt chuông báo cháy. Chỉ gửi khi trạng thái thay đổi."""
        if self._buzzer_state == on:
            return True

        cmd  = "BUZZER:ON" if on else "BUZZER:OFF"
        resp = self._send(cmd)

        if resp and resp.startswith("OK"):
            self._buzzer_state = on
            logger.info(f"[ESP32] Chuông báo cháy → {'BẬT' if on else 'TẮT'}")
            return True

        logger.warning(f"[ESP32] set_buzzer({on}) thất bại: {resp!r}")
        return False

    def sync(self, zone1_on: bool, zone2_on: bool, buzzer_on: bool) -> None:
        """
        Đồng bộ cả 3 relay trong 1 lần gọi – dùng trong vòng lặp main.py
        mỗi frame. Tự động bỏ qua relay nào không có thay đổi.
        """
        ok1 = self.set_zone_light(1, zone1_on)
        ok2 = self.set_zone_light(2, zone2_on)
        ok3 = self.set_buzzer(buzzer_on)

        if not (ok1 and ok2 and ok3) and not self.is_connected():
            if self.try_reconnect():
                # Gửi lại sau khi kết nối lại
                self.set_zone_light(1, zone1_on)
                self.set_zone_light(2, zone2_on)
                self.set_buzzer(buzzer_on)

    def all_off(self) -> bool:
        """Tắt tất cả relay (2 đèn + chuông) trong 1 lệnh."""
        resp = self._send("ALL:OFF")
        if resp and resp.startswith("OK"):
            self._zone_light_state = {1: False, 2: False}
            self._buzzer_state = False
            logger.info("[ESP32] ALL:OFF – đã tắt 2 đèn + chuông.")
            return True
        return False

    def ping(self) -> bool:
        """Kiểm tra ESP32 còn phản hồi không."""
        return self._send("PING") == "PONG"

    def get_states(self) -> dict:
        """Trả về bản sao trạng thái relay hiện tại (debug/log)."""
        return {
            "zone1_light": self._zone_light_state[1],
            "zone2_light": self._zone_light_state[2],
            "buzzer":      self._buzzer_state,
        }
