import subprocess
import os
import os.path

# commands
LCD_CLEARDISPLAY = "\014"
LCD_RETURNHOME = "\033[H"
LCD_XY = "\033[Lx%dy%d;"
LCD_BACKLIGHT_ON = "\033[L+"
LCD_BACKLIGHT_OFF = "\033[L-"

PWM_BACKLIGHT = "/sys/class/backlight/gxdisp-0-0051"
PWM_BRIGHTNESS_ON = 15
PWM_BRIGHTNESS_OFF = 1
ADC_DAYLIGHT = 200


class Lcd(object):
    # initializes objects and lcd
    def __init__(self, lcd_dev):
        self.lcd = os.open(lcd_dev, os.O_WRONLY)
        self._backlight_on = True
        self.pwm_backlight = os.path.exists(PWM_BACKLIGHT)
        if self.pwm_backlight:
            self.write_attr("auto_brightness", 0)
            self.on_pwm(True)
            self.on_gpio(True)

    def write(self, data):
        os.write(self.lcd, data)

    def write_string(self, str):
        self.write(str.encode())

    def write_attr(self, attr, val):
        f = open(PWM_BACKLIGHT + "/" + attr, "wb")
        f.write(str(val).encode("ascii"))
        f.close()

    # put string function
    def display_string(self, string, line):
        self.write_string(LCD_XY % (0, line - 1))
        self.write_string(string)

    # clear lcd and set to home
    def clear(self):
        self.write_string(LCD_CLEARDISPLAY)

    @property
    def on(self):
        return self._backlight_on

    @on.setter
    def on(self, v):
        self._backlight_on = bool(v)
        if v:
            self.write_string(LCD_RETURNHOME)

        if self.pwm_backlight:
            self.on_pwm(v)
        else:
            self.on_gpio(v)

    def on_pwm(self, v):
        if v:
            self.write_attr("brightness", PWM_BRIGHTNESS_ON)
        else:
            self.write_attr("brightness", PWM_BRIGHTNESS_OFF)

    def on_gpio(self, v):
        if v:
            self.write_string(LCD_BACKLIGHT_ON)
        else:
            self.write_string(LCD_BACKLIGHT_OFF)

    @property
    def daylight(self):
        if self.pwm_backlight:
            return self.daylight_adc()
        else:
            return self.daylight_gpio()

    def daylight_adc(self):
        try:
            v = int(open(PWM_BACKLIGHT + "/adc_value", "rb").read().strip())
            return v >= ADC_DAYLIGHT
        except Exception:
            pass
        return True

    def daylight_gpio(self):
        """Read the light sensor and return true if high level of ambient
        light is detected."""
        try:
            return open("/dev/gpio/display_sensor/value", "rb").read().strip() == b"0"
        except IOError:
            pass
        return True

    def splash(self):
        product = "Unknown model"
        try:
            product = subprocess.check_output(["product-name"]).decode("utf8").strip()
        except OSError:
            pass
        self.on = True
        self.display_string(" Victron Energy ", 1)
        self.display_string(product.center(16), 2)


class DebugLcd(Lcd):
    def __init__(self):
        pass

    def display_string(self, string, line):
        if line == 1:
            print("|" + "-" * 16 + "|")
        print("|" + string + "|")

    def clear(self):
        pass

    @property
    def on(self):
        pass

    @on.setter
    def on(self, v):
        pass

    @property
    def daylight(self):
        return True
