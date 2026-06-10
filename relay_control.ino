/*
 * relay_control.ino – ESP32 Relay Controller
 * ═══════════════════════════════════════════
 * Nhận lệnh từ PC qua Serial (115200 baud, kết thúc '\n')
 * và điều khiển 4 relay tương ứng 4 Zone.
 *
 * ── Giao thức (ASCII, newline-terminated) ──────────────────
 *  PC gửi     │ ESP32 phản hồi
 * ────────────┼──────────────────────────────────────────────
 *  PING       │ PONG
 *  Z1:ON      │ OK        – Bật relay Zone 1
 *  Z2:OFF     │ OK        – Tắt relay Zone 2
 *  Z3:ON      │ OK        – Bật relay Zone 3
 *  Z4:OFF     │ OK        – Tắt relay Zone 4
 *  ALL:OFF    │ OK        – Tắt tất cả relay
 *  STATUS     │ Z1:0,Z2:1,Z3:0,Z4:0   (0=off, 1=on)
 *  RESET      │ OK        – Tắt tất cả + reset trạng thái
 *
 * ── Sơ đồ nối dây ──────────────────────────────────────────
 *  Zone 1 → GPIO 26 → IN1 của relay module
 *  Zone 2 → GPIO 27 → IN2
 *  Zone 3 → GPIO 14 → IN3
 *  Zone 4 → GPIO 12 → IN4
 *
 *  VCC relay module → 5V (hoặc 3.3V tùy module)
 *  GND relay module → GND ESP32
 *
 * ── Lưu ý module relay ─────────────────────────────────────
 *  Hầu hết module relay "active-low": GPIO LOW = relay bật.
 *  Nếu module của bạn "active-high": đổi RELAY_ACTIVE_LEVEL = HIGH.
 */

// ─── Cấu hình ────────────────────────────────────────────────────────────────

#define NUM_ZONES       4
#define BAUD_RATE       115200
#define HEARTBEAT_MS    5000     // Gửi heartbeat mỗi 5 giây

// GPIO cho từng Zone (Zone 1 → index 0, ...)
const int RELAY_PIN[NUM_ZONES] = {26, 27, 14, 12};

// Active-low (LOW = relay bật) – dùng cho hầu hết module relay phổ thông
// Đổi thành HIGH nếu module của bạn là active-high
const int RELAY_ACTIVE_LEVEL   = LOW;
const int RELAY_INACTIVE_LEVEL = HIGH;

// ─── Biến toàn cục ────────────────────────────────────────────────────────────

bool zoneState[NUM_ZONES] = {false, false, false, false};
unsigned long lastHeartbeat = 0;

// ─── Hàm helper ──────────────────────────────────────────────────────────────

void setRelay(int zone, bool on) {
  // zone: 1-based
  if (zone < 1 || zone > NUM_ZONES) return;
  int idx = zone - 1;
  zoneState[idx] = on;
  digitalWrite(RELAY_PIN[idx], on ? RELAY_ACTIVE_LEVEL : RELAY_INACTIVE_LEVEL);
}

void allOff() {
  for (int i = 0; i < NUM_ZONES; i++) {
    zoneState[i] = false;
    digitalWrite(RELAY_PIN[i], RELAY_INACTIVE_LEVEL);
  }
}

void sendStatus() {
  String msg = "";
  for (int i = 0; i < NUM_ZONES; i++) {
    if (i > 0) msg += ",";
    msg += "Z" + String(i + 1) + ":" + (zoneState[i] ? "1" : "0");
  }
  Serial.println(msg);
}

// ─── Xử lý lệnh ──────────────────────────────────────────────────────────────

void handleCommand(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;

  // PING
  if (cmd == "PING") {
    Serial.println("PONG");
    return;
  }

  // ALL:OFF
  if (cmd == "ALL:OFF" || cmd == "RESET") {
    allOff();
    Serial.println("OK");
    return;
  }

  // STATUS
  if (cmd == "STATUS") {
    sendStatus();
    return;
  }

  // Z<n>:ON  hoặc  Z<n>:OFF
  // Định dạng mong đợi: "Z1:ON", "Z4:OFF", v.v.
  if (cmd.length() >= 5 && cmd[0] == 'Z') {
    int  zone   = cmd[1] - '0';             // ký tự số → int
    String act  = cmd.substring(3);         // "ON" hoặc "OFF"
    act.trim();

    if (zone >= 1 && zone <= NUM_ZONES) {
      if (act == "ON") {
        setRelay(zone, true);
        Serial.println("OK");
      } else if (act == "OFF") {
        setRelay(zone, false);
        Serial.println("OK");
      } else {
        Serial.println("ERR:UNKNOWN_ACTION");
      }
    } else {
      Serial.println("ERR:INVALID_ZONE");
    }
    return;
  }

  // Lệnh không nhận dạng được
  Serial.println("ERR:UNKNOWN_CMD");
}

// ─── Setup ────────────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(BAUD_RATE);

  // Khởi tạo GPIO relay – tắt hết trước
  for (int i = 0; i < NUM_ZONES; i++) {
    pinMode(RELAY_PIN[i], OUTPUT);
    digitalWrite(RELAY_PIN[i], RELAY_INACTIVE_LEVEL);
  }

  delay(300);
  Serial.println("READY");   // Thông báo PC rằng ESP32 đã sẵn sàng
}

// ─── Loop ─────────────────────────────────────────────────────────────────────

void loop() {
  // Đọc lệnh từ Serial
  if (Serial.available() > 0) {
    String line = Serial.readStringUntil('\n');
    handleCommand(line);
  }

  // Heartbeat định kỳ (giúp PC phát hiện nếu ESP32 bị treo)
  unsigned long now = millis();
  if (now - lastHeartbeat >= HEARTBEAT_MS) {
    lastHeartbeat = now;
    // Gửi trạng thái relay để PC có thể đồng bộ nếu cần
    // Bỏ comment dòng dưới nếu muốn bật heartbeat
    // Serial.println("HB:" + String(now / 1000));
  }
}
