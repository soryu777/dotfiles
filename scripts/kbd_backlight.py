#!/usr/bin/env python3
"""
kbd_backlight.py — переключение LED подсветки клавиатуры через evdev
Arch Linux / Hyprland

Зависимости:
  sudo pacman -S python-evdev   (или: pip install evdev)

Запуск:
  sudo python kbd_backlight.py                          # авто-выбор устройства
  sudo python kbd_backlight.py --device /dev/input/eventX
  sudo python kbd_backlight.py --device /dev/input/eventX --hotkey KEY_SCROLLLOCK
  sudo python kbd_backlight.py --list                   # показать устройства
"""

import argparse
import sys

try:
    import evdev
    from evdev import InputDevice, UInput, ecodes, categorize
except ImportError:
    print("Установи evdev: sudo pacman -S python-evdev")
    sys.exit(1)


# ─────────────────────────────────────────────
#  Утилиты
# ─────────────────────────────────────────────

def list_keyboards() -> list[InputDevice]:
    keyboards = []
    for path in evdev.list_devices():
        try:
            dev = InputDevice(path)
            caps = dev.capabilities()
            if ecodes.EV_KEY in caps:
                keys = caps[ecodes.EV_KEY]
                if ecodes.KEY_A in keys and ecodes.KEY_SPACE in keys:
                    keyboards.append(dev)
        except Exception:
            pass
    return keyboards


def pick_device(keyboards: list[InputDevice]) -> InputDevice | None:
    if not keyboards:
        print("[!] Клавиатуры не найдены")
        return None
    if len(keyboards) == 1:
        print(f"[i] Используется: {keyboards[0].name} ({keyboards[0].path})")
        return keyboards[0]
    print("\nДоступные клавиатуры:")
    for i, dev in enumerate(keyboards):
        print(f"  [{i}] {dev.name}  ({dev.path})")
    try:
        choice = int(input("Выбери номер: "))
        return keyboards[choice]
    except (ValueError, IndexError):
        return keyboards[0]


def get_hotkey_code(name: str) -> int | None:
    code = getattr(ecodes, name.upper(), None)
    if code is None:
        print(f"[!] Клавиша '{name}' не найдена")
    return code


# ─────────────────────────────────────────────
#  LED-контроллер через evdev
# ─────────────────────────────────────────────

# Маппинг: имя LED → код ecodes
LED_MAP = {
    "scrolllock": ecodes.LED_SCROLLL,
    "capslock":   ecodes.LED_CAPSL,
    "numlock":    ecodes.LED_NUML,
}

class LedController:
    def __init__(self, device: InputDevice, led_code: int):
        self.device = device
        self.led_code = led_code
        self._state: bool = led_code in device.leds()
        name = {v: k for k, v in LED_MAP.items()}.get(led_code, str(led_code))
        print(f"[i] LED: {name}  (код {led_code})")

    def toggle(self):
        self._state = not self._state
        val = 1 if self._state else 0
        self.device.write(ecodes.EV_LED, self.led_code, val)
        self.device.write(ecodes.EV_SYN, ecodes.SYN_REPORT, 0)
        label = "ВКЛ 🟡" if self._state else "ВЫКЛ ⬛"
        print(f"[✓] Scroll Lock LED: {label}")

    def set_state(self, on: bool):
        self._state = on
        state = 1 if on else 0
        self.device.write(ecodes.EV_LED, self.led_code, state)
        self.device.write(ecodes.EV_SYN, ecodes.SYN_REPORT, 0)

    def restore(self):
        """Восстановить текущее желаемое состояние LED."""
        state = 1 if self._state else 0
        self.device.write(ecodes.EV_LED, self.led_code, state)
        self.device.write(ecodes.EV_SYN, ecodes.SYN_REPORT, 0)


# ─────────────────────────────────────────────
#  Основной цикл прослушивания
# ─────────────────────────────────────────────

def listen_and_toggle(device: InputDevice,
                      controller: LedController,
                      hotkey_code: int):
    key_name = ecodes.KEY[hotkey_code] if hotkey_code in ecodes.KEY else str(hotkey_code)

    # Захватываем устройство и пересылаем все события кроме хоткея
    try:
        ui = UInput.from_device(device, name=f"{device.name} (passthrough)")
    except Exception as e:
        print(f"[!] Не удалось создать uinput: {e}")
        print(f"    Попробуй: sudo modprobe uinput")
        sys.exit(1)

    try:
        device.grab()
    except Exception as e:
        print(f"[!] Не удалось захватить устройство: {e}")
        ui.close()
        sys.exit(1)

    print(f"\n[▶] Слушаю {device.name}")
    print(f"    Хоткей: {key_name}  |  Ctrl+C для выхода\n")

    try:
        for event in device.read_loop():
            # Хоткей — переключаем LED, не пересылаем в систему
            if (event.type == ecodes.EV_KEY
                    and event.code == hotkey_code
                    and event.value == 1):
                controller.toggle()
                continue

            # Ядро пытается сбросить LED — перехватываем и игнорируем
            if event.type == ecodes.EV_LED and event.code == controller.led_code:
                # Восстанавливаем наше состояние
                controller.restore()
                continue

            # Всё остальное — пересылаем прозрачно
            ui.write_event(event)
            ui.syn()

            # После любого события клавиши восстанавливаем LED
            # (ядро может сбросить его в фоне)
            if event.type == ecodes.EV_KEY:
                controller.restore()

    except KeyboardInterrupt:
        print("\n[i] Выход.")
    except PermissionError:
        print(f"[!] Нет прав: запусти через sudo")
    finally:
        try:
            device.ungrab()
        except Exception:
            pass
        try:
            ui.close()
        except Exception:
            pass


# ─────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────

def cmd_list():
    print("=== Клавиатуры ===")
    for dev in list_keyboards():
        caps = dev.capabilities()
        leds = []
        if ecodes.EV_LED in caps:
            leds = [ecodes.LED[c] for c in caps[ecodes.EV_LED] if c in ecodes.LED]
        print(f"  {dev.path}  |  {dev.name}")
        if leds:
            print(f"           LEDs: {', '.join(leds)}")


def main():
    parser = argparse.ArgumentParser(
        description="Переключение LED подсветки клавиатуры через evdev",
    )
    parser.add_argument("--list",   action="store_true",
                        help="показать клавиатуры и их LED")
    parser.add_argument("--device", metavar="PATH",
                        help="путь к устройству, например /dev/input/event5")
    parser.add_argument("--hotkey", metavar="KEY", default="KEY_SCROLLLOCK",
                        help="клавиша-хоткей (по умолчанию: KEY_SCROLLLOCK)")
    parser.add_argument("--led",    metavar="NAME", default="scrolllock",
                        choices=list(LED_MAP.keys()),
                        help="какой LED переключать: scrolllock, capslock, numlock (по умолчанию: scrolllock)")
    args = parser.parse_args()

    if args.list:
        cmd_list()
        return

    # Выбор устройства
    if args.device:
        try:
            device = InputDevice(args.device)
        except Exception as e:
            print(f"[!] Не удалось открыть {args.device}: {e}")
            sys.exit(1)
    else:
        keyboards = list_keyboards()
        device = pick_device(keyboards)
        if device is None:
            sys.exit(1)

    # Проверяем что у устройства есть нужный LED
    led_code = LED_MAP[args.led]
    dev_caps = device.capabilities()
    if ecodes.EV_LED not in dev_caps or led_code not in dev_caps[ecodes.EV_LED]:
        print(f"[!] Устройство {device.name} не поддерживает LED '{args.led}'")
        print(f"    Доступные LED: {list(dev_caps.get(ecodes.EV_LED, []))}")
        sys.exit(1)

    hotkey_code = get_hotkey_code(args.hotkey)
    if hotkey_code is None:
        sys.exit(1)

    controller = LedController(device, led_code)
    listen_and_toggle(device, controller, hotkey_code)


if __name__ == "__main__":
    main()
