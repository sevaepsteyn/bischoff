from threading import Thread, Event
from time import sleep
from typing import Callable
from smbus import SMBus

DEBUG = False  # Set to True to enable debug output

DEVICE_BUS = 1
NUNCHUCK_ADDR = 0x52
TICK = 0.01  # 100 Hz
MAX_RETRIES = 3
RETRY_DELAY = 0.1

class NunchuckState:
    def __init__(self, stick=(0, 0), accel=(0, 0, 0), button_c=False, button_z=False):
        self.stick = stick
        self.accel = accel
        self.button_c = button_c
        self.button_z = button_z

    def __repr__(self):
        return f"<NunchuckState stick={self.stick} accel={self.accel} C={self.button_c} Z={self.button_z}>"

class Nunchuck:
    def __init__(self, stop_event: Event):
        self.stop_event = stop_event
        self._thread = Thread(target=self._run)
        self.state = NunchuckState()
        self.last_state = NunchuckState()
        self._init_i2c()

    def _init_i2c(self):
        print("Initializing Nunchuck...")
        try:
            self.bus = SMBus(DEVICE_BUS)
            self.bus.write_byte_data(NUNCHUCK_ADDR, 0xF0, 0x55)
            sleep(0.1)
            self.bus.write_byte_data(NUNCHUCK_ADDR, 0xFB, 0x00)
            sleep(0.1)
            print("Nunchuck initialized successfully")
        except Exception as e:
            print(f"Error initializing Nunchuck: {e}")

    def read(self):
        try:
            self.bus.write_byte(NUNCHUCK_ADDR, 0x00)
            sleep(0.001)
            data = [self.bus.read_byte(NUNCHUCK_ADDR) for _ in range(6)]
            
            stick = (data[0], data[1])
            accel = (data[2], data[3], data[4])
            buttons = data[5]
            button_c = not (buttons & 0x02)
            button_z = not (buttons & 0x01)

            self.last_state = self.state
            self.state = NunchuckState(stick, accel, button_c, button_z)
            
            if DEBUG:
                print(f"Raw data: {data}")
                print(f"Processed state: {self.state}")

            return self.state
        except Exception as e:
            if DEBUG:
                print(f"Error reading from Nunchuck: {e}")
            return None

    def get_button_changes(self):
        changes = []
        if self.state.button_c != self.last_state.button_c:
            changes.append(('C', self.state.button_c))
        if self.state.button_z != self.last_state.button_z:
            changes.append(('Z', self.state.button_z))
        return changes

    def start(self):
        self._thread.start()

    def stop(self):
        self.stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)  # Wait up to 2 seconds for the thread to stop

    def _run(self):
        while not self.stop_event.is_set():
            self.read()
            sleep(TICK)

    def __repr__(self):
        return f"<Nunchuck {hex(NUNCHUCK_ADDR)} {self.state}>"
