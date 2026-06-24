/*
 * relay_control.ino – ESP32 Relay Controller (2 Camera / 2 Zone)
 * ═════════════════════════════════════════════════════════════════
 *
 * Hệ thống báo cháy 2 Camera:
 *   Zone 1 = Camera PC        → đèn tại chân X (GPIO 26)
 *   Zone 2 = Camera DroidCam  → đèn tại chân Y (GPIO 27)
 *   Chuông báo cháy chung     → chân GPIO 25 (BẬT nếu Zone 1 HOẶC Zone 2 cháy)
 *
 * ── Luồng tín hiệu ───────────────────────────────────────────────
 *
 *  [Cam PC] ──► [Laptop: YOLOv8]              [Cam DroidCam] ──► [Laptop: YOLOv8]
 *                     │  Zone 1                                        │  Zone 2
 *                     └──────────────────┬─────────────────────────────┘
 *                                        │  USB Serial (Z1:ON, Z2:ON, BUZZER:ON…)
 *                                        ▼
 *                                    [ESP32]
 *                              ┌─────────┼─────────┐
 *                              ▼         ▼          ▼
 *                         Relay 1   Relay 2    Relay 3
 *                       (đèn Z1)  (đèn Z2)    (chuông)
 *
 * Lưu ý quan trọng: ESP32 KHÔNG tự tính thời gian trễ 5 giây.
 * Toàn bộ logic (khi nào bật, khi nào tắt sau 5s không còn lửa)
 * được tính bởi Python trên laptop – ESP32 chỉ thực thi lệnh ON/OFF
 * tường minh nhận được. Thiết kế này giữ firmware đơn giản, dễ debug.
 *
 * ── Giao thức Serial (115200 baud, kết thúc '\n') ─────────────────
 *
 *  PC gửi         │ ESP32 trả lời        │ Mô tả
 * ────────────────┼──────────────────────┼─────────────────────────────
 *  PING           │ PONG                 │ Kiểm tra kết nối
 *  Z1:ON / Z1:OFF │ OK                   │ Đèn Zone 1 (chân X)
 *  Z2:ON / Z2:OFF │ OK                   │ Đèn Zone 2 (chân Y)
 *  BUZZER:ON/OFF  │ OK                   │ Chuông báo cháy chung
 *  ALL:OFF        │ OK                   │ Tắt tất cả (2 đèn + chuông)
 *  RESET          │ OK                   │ Giống ALL:OFF
 *  STATUS         │ Z1:0,Z2:1,BUZZER:1   │ Đọc trạng thái hiện tại
 *
 * ── Sơ đồ nối dây ──────────────────────────────────────────────────
 *
 *  ESP32 GPIO │ Kết nối       │ Chức năng
 *  ───────────┼───────────────┼──────────────────────────────────────
 *  GPIO 26 (X)│ IN1 relay     │ Đèn Zone 1 (báo cháy khu vực Camera PC)
 *  GPIO 27 (Y)│ IN2 relay     │ Đèn Zone 2 (báo cháy khu vực DroidCam)
 *  GPIO 25    │ IN3 relay     │ Chuông / còi báo cháy chung
 *  GPIO  2    │ LED có sẵn    │ LED trạng thái ESP32 (built-in)
 *  5V / GND   │ VCC / GND     │ Nguồn cấp module relay
 *
 * ⚠  Module relay thường ACTIVE-LOW (GPIO LOW = relay BẬT).
 *    Nếu module của bạn active-high, đổi ACTIVE_LOW_MODE = false.
 */

// ─── Cấu hình chân ────────────────────────────────────────────────────────────

#define BAUD_RATE        115200

#define LIGHT_ZONE1_PIN  26     // Chân X – đèn Zone 1 (Camera PC)
#define LIGHT_ZONE2_PIN  27     // Chân Y – đèn Zone 2 (Camera DroidCam)
#define BUZZER_PIN       25     // Chuông báo cháy chung
#define STATUS_LED_PIN   2      // LED trạng thái ESP32 (built-in)

// true  = active-low  (LOW  → relay BẬT) – phổ biến nhất với module relay rời
// false = active-high (HIGH → relay BẬT)
const bool ACTIVE_LOW_MODE = true;

#define RELAY_ON_LEVEL  (ACTIVE_LOW_MODE ? LOW  : HIGH)
#define RELAY_OFF_LEVEL (ACTIVE_LOW_MODE ? HIGH : LOW)

// ─── Biến trạng thái ───────────────────────────────────────────────────────────

bool light1State = false;   // Đèn Zone 1
bool light2State = false;   // Đèn Zone 2
bool buzzerState = false;   // Chuông báo cháy

unsigned long lastLedToggle = 0;
bool          ledOn         = false;
const unsigned long LED_BLINK_MS = 300;   // Nhấp nháy khi đang có cảnh báo

// ─── Hàm phụ ────────────────────────────────────────────────────────────────────

void writeRelay(int pin, bool on) {
  digitalWrite(pin, on ? RELAY_ON_LEVEL : RELAY_OFF_LEVEL);
}

void setLight1(bool on) {
  light1State = on;
  writeRelay(LIGHT_ZONE1_PIN, on);
}

void setLight2(bool on) {
  light2State = on;
  writeRelay(LIGHT_ZONE2_PIN, on);
}

void setBuzzer(bool on) {
  buzzerState = on;
  writeRelay(BUZZER_PIN, on);
}

void allOff() {
  setLight1(false);
  setLight2(false);
  setBuzzer(false);
}

bool anyActive() {
  return light1State || light2State || buzzerState;
}

void sendStatus() {
  String msg = "Z1:" + String(light1State ? "1" : "0") +
               ",Z2:" + String(light2State ? "1" : "0") +
               ",BUZZER:" + String(buzzerState ? "1" : "0");
  Serial.println(msg);
}

// ─── Xử lý lệnh Serial ──────────────────────────────────────────────────────────

void handleCommand(String raw) {
  raw.trim();
  if (raw.length() == 0) return;

  // PING
  if (raw == "PING") {
    Serial.println("PONG");
    return;
  }

  // STATUS
  if (raw == "STATUS") {
    sendStatus();
    return;
  }

  // ALL:OFF / RESET
  if (raw == "ALL:OFF" || raw == "RESET") {
    allOff();
    Serial.println("OK");
    return;
  }

  // Z1:ON / Z1:OFF – đèn Zone 1 (chân X)
  if (raw == "Z1:ON")  { setLight1(true);  Serial.println("OK"); return; }
  if (raw == "Z1:OFF") { setLight1(false); Serial.println("OK"); return; }

  // Z2:ON / Z2:OFF – đèn Zone 2 (chân Y)
  if (raw == "Z2:ON")  { setLight2(true);  Serial.println("OK"); return; }
  if (raw == "Z2:OFF") { setLight2(false); Serial.println("OK"); return; }

  // BUZZER:ON / BUZZER:OFF – chuông báo cháy chung
  if (raw == "BUZZER:ON")  { setBuzzer(true);  Serial.println("OK"); return; }
  if (raw == "BUZZER:OFF") { setBuzzer(false); Serial.println("OK"); return; }

  // Lệnh không nhận dạng được
  Serial.println("ERR:UNKNOWN_CMD:" + raw);
}

// ─── LED trạng thái ──────────────────────────────────────────────────────────────
//   Bình thường  : LED sáng liên tục
//   Có cảnh báo  : LED nhấp nháy nhanh

void updateStatusLed() {
  unsigned long now = millis();
  if (anyActive()) {
    if (now - lastLedToggle >= LED_BLINK_MS) {
      ledOn = !ledOn;
      digitalWrite(STATUS_LED_PIN, ledOn ? HIGH : LOW);
      lastLedToggle = now;
    }
  } else {
    if (!ledOn) {
      digitalWrite(STATUS_LED_PIN, HIGH);
      ledOn = true;
    }
  }
}

// ─── Setup ──────────────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(BAUD_RATE);

  pinMode(STATUS_LED_PIN, OUTPUT);
  digitalWrite(STATUS_LED_PIN, LOW);

  pinMode(LIGHT_ZONE1_PIN, OUTPUT);
  pinMode(LIGHT_ZONE2_PIN, OUTPUT);
  pinMode(BUZZER_PIN,      OUTPUT);

  // Đảm bảo tất cả relay TẮT ngay khi khởi động (an toàn)
  writeRelay(LIGHT_ZONE1_PIN, false);
  writeRelay(LIGHT_ZONE2_PIN, false);
  writeRelay(BUZZER_PIN,      false);

  delay(300);
  Serial.println("READY");     // Báo cho Python: ESP32 đã sẵn sàng nhận lệnh
  digitalWrite(STATUS_LED_PIN, HIGH);
}

// ─── Loop ───────────────────────────────────────────────────────────────────────

void loop() {
  if (Serial.available() > 0) {
    String line = Serial.readStringUntil('\n');
    handleCommand(line);
  }
  updateStatusLed();
}
