#include <Wire.h>
#include <LiquidCrystal_I2C.h>

const uint8_t PIN_BIT_ONE = 13;
const uint8_t PIN_BIT_ZERO = 12;
const unsigned long SERIAL_BAUD = 9600;
const unsigned long PULSE_DURATION_MS = 5;

LiquidCrystal_I2C lcd(0x27, 16, 2);

struct Instrument {
  uint8_t label;
  const char *name;
  const char *unit;
  float resolution;
  float minimum;
  float maximum;
};

// Keep this table synchronized with the instruments configured in the web app.
const Instrument instruments[] = {
  {0203, "Altitud", "ft", 0.5, -1000.0, 20000.0},
};
const size_t instrumentCount = sizeof(instruments) / sizeof(instruments[0]);

String serialLine;

uint8_t reverseLabel(uint8_t value) {
  uint8_t reversed = 0;
  for (uint8_t bit = 0; bit < 8; bit++) {
    reversed = (reversed << 1) | ((value >> bit) & 1);
  }
  return reversed;
}

bool hasOddParity(uint32_t word) {
  uint8_t ones = 0;
  while (word) {
    ones += word & 1U;
    word >>= 1;
  }
  return (ones & 1U) == 1U;
}

bool parseWord(const String &line, uint32_t &word) {
  if (line.length() != 8) return false;
  word = 0;
  for (size_t i = 0; i < line.length(); i++) {
    const char character = line[i];
    uint8_t nibble;
    if (character >= '0' && character <= '9') {
      nibble = character - '0';
    } else if (character >= 'A' && character <= 'F') {
      nibble = character - 'A' + 10;
    } else if (character >= 'a' && character <= 'f') {
      nibble = character - 'a' + 10;
    } else {
      return false;
    }
    word = (word << 4) | nibble;
  }
  return true;
}

void rejectWord(const char *message) {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Palabra invalida");
  lcd.setCursor(0, 1);
  lcd.print(message);
}

void pulseWord(uint32_t word) {
  for (int8_t bit = 31; bit >= 0; bit--) {
    const uint8_t pin = (word & (1UL << bit)) ? PIN_BIT_ONE : PIN_BIT_ZERO;
    digitalWrite(pin, HIGH);
    delay(PULSE_DURATION_MS);
    digitalWrite(pin, LOW);
    delay(PULSE_DURATION_MS);
  }
}

void processLine(const String &line) {
  uint32_t word;
  if (!parseWord(line, word)) {
    rejectWord("Formato hex invalido");
    return;
  }
  if (!hasOddParity(word)) {
    rejectWord("Paridad incorrecta");
    return;
  }

  const uint8_t label = reverseLabel(word & 0xFFU);
  const Instrument *instrument = nullptr;
  for (size_t i = 0; i < instrumentCount; i++) {
    if (instruments[i].label == label) {
      instrument = &instruments[i];
      break;
    }
  }
  if (instrument == nullptr) {
    rejectWord("Etiqueta no existe");
    return;
  }

  uint32_t rawData = (word >> 10) & 0x7FFFFU;
  const int32_t signedData = (rawData & 0x40000U)
      ? static_cast<int32_t>(rawData) - 0x80000L
      : static_cast<int32_t>(rawData);
  const float value = signedData * instrument->resolution;
  if (value < instrument->minimum || value > instrument->maximum) {
    rejectWord("Fuera de rango");
    return;
  }

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(instrument->name);
  lcd.setCursor(0, 1);
  lcd.print(value, 2);
  lcd.print(" ");
  lcd.print(instrument->unit);
  pulseWord(word);
}

void setup() {
  pinMode(PIN_BIT_ONE, OUTPUT);
  pinMode(PIN_BIT_ZERO, OUTPUT);
  digitalWrite(PIN_BIT_ONE, LOW);
  digitalWrite(PIN_BIT_ZERO, LOW);
  Serial.begin(SERIAL_BAUD);
  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0);
  lcd.print("ARINC 429 listo");
  lcd.setCursor(0, 1);
  lcd.print("9600 baudios");
}

void loop() {
  while (Serial.available() > 0) {
    const char character = static_cast<char>(Serial.read());
    if (character == '\n') {
      serialLine.trim();
      processLine(serialLine);
      serialLine = "";
    } else if (character != '\r') {
      if (serialLine.length() < 8) {
        serialLine += character;
      } else {
        serialLine = "";
        rejectWord("Trama demasiado larga");
      }
    }
  }
}
