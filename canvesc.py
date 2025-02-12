from can import Message, Bus
from typing import Callable, Dict
from threading import Thread, Event
import threading
from time import sleep, time
from struct import unpack

DEBUG = False  # Set to True to enable debug output
TICK = 0.001  # 1000 Hz (adjust as needed)

class CanVescState:
    def __init__(self):
        self.rpm = 0
        self.current = 0
        self.duty = 0
        self.amp_hours = 0
        self.amp_hours_charged = 0
        self.watt_hours = 0
        self.watt_hours_charged = 0
        self.temp_fet = 0
        self.temp_motor = 0
        self.current_in = 0
        self.pid_pos_now = 0
        self.tachometer = 0
        self.input_voltage = 0

    def __repr__(self):
        return f"<CanVescState rpm={self.rpm} current={self.current:.2f}A duty={self.duty:.2f} temp_fet={self.temp_fet:.1f}°C temp_motor={self.temp_motor:.1f}°C tachometer={self.tachometer} input_voltage={self.input_voltage:.1f}V>"

class CanVesc:
    CAN_PACKET_STATUS_1 = 0x09
    CAN_PACKET_STATUS_2 = 0x0E
    CAN_PACKET_STATUS_3 = 0x0F
    CAN_PACKET_STATUS_4 = 0x10
    CAN_PACKET_STATUS_5 = 0x1B
    CAN_PACKET_SET_DUTY = 0x01
    CAN_PACKET_SET_CURRENT = 0x02
    CAN_PACKET_SET_RPM = 0x03

    RPM_SCALE_FACTOR = 2000  # This might need adjustment based on your specific VESC firmware

    def __init__(self, stop_event: Event, channel='can0', bustype='socketcan', motor_temp_offset=1000):
        self.stop_event = stop_event
        self.bus = Bus(channel=channel, bustype=bustype, bitrate=500000)
        self.states = {}
        self.callbacks: Dict[int, Callable] = {}
        self._running = False
        self._thread = None
        self.motor_temp_offset = motor_temp_offset
        self.rpm_command_thread = None
        self.rpm_command_lock = threading.Lock()
        self.current_rpm_command = 0

    def start(self):
        if not self._running:
            self._running = True
            self._thread = Thread(target=self._run)
            self._thread.start()
            self.start_rpm_command_thread()

    def stop(self):
        self._running = False
        self.stop_rpm_command_thread()
        if self._thread:
            self._thread.join(timeout=2)  # Wait up to 2 seconds for the thread to stop
        self.bus.shutdown()

    def _run(self):
        while self._running and not self.stop_event.is_set():
            self.read()
            sleep(TICK)

    def read(self):
        try:
            message = self.bus.recv(timeout=TICK)
            if message:
                self._process_message(message)
        except Exception as e:
            if DEBUG:
                print(f"Error reading from CAN bus: {e}")

    def _process_message(self, message):
        unit_id = message.arbitration_id & 0xFF
        packet_id = (message.arbitration_id >> 8) & 0xFF

        if all(byte == 0 for byte in message.data):
            return

        if unit_id not in self.states:
            self.states[unit_id] = CanVescState()

        state = self.states[unit_id]

        try:
            if packet_id == self.CAN_PACKET_STATUS_1:
                rpm, current = unpack('>ii', message.data)
                state.rpm = rpm
                state.current = current / 10.0
            elif packet_id == self.CAN_PACKET_STATUS_2:
                duty, amp_hours, amp_hours_charged = unpack('>hHH', message.data[:6])
                state.duty = duty / 1000.0
                state.amp_hours = amp_hours / 10.0
                state.amp_hours_charged = amp_hours_charged / 10.0
            elif packet_id == self.CAN_PACKET_STATUS_3:
                watt_hours, watt_hours_charged = unpack('>ii', message.data)
                state.watt_hours = watt_hours / 10.0
                state.watt_hours_charged = watt_hours_charged / 10.0
            elif packet_id == self.CAN_PACKET_STATUS_4:
                temp_fet, temp_motor, current_in, pid_pos_now = unpack('>hhhH', message.data)
                state.temp_fet = temp_fet / 10.0
                state.temp_motor = (temp_motor + self.motor_temp_offset) / 10.0
                state.current_in = current_in / 10.0
                state.pid_pos_now = pid_pos_now / 50.0

                if DEBUG:
                    print(f"Processed temperature - FET: {state.temp_fet:.1f}°C, Motor: {state.temp_motor:.1f}°C")
            elif packet_id == self.CAN_PACKET_STATUS_5:
                tachometer, voltage = unpack('>iH', message.data[:6])
                state.tachometer = tachometer
                state.input_voltage = voltage / 10.0

                if DEBUG:
                    print(f"Status 5 - Tachometer: {state.tachometer}, Input Voltage: {state.input_voltage:.1f}V")

            if packet_id in self.callbacks:
                self.callbacks[packet_id](unit_id, state)
        except Exception as e:
            if DEBUG:
                print(f"Error processing message: {e}")

    def register_callback(self, packet_id: int, callback: Callable):
        self.callbacks[packet_id] = callback

    def set_duty(self, duty: float, unit_id: int = 0xFF):
        duty_i = int(duty * 100000)
        message = Message(
            arbitration_id=(self.CAN_PACKET_SET_DUTY << 8) | unit_id,
            data=duty_i.to_bytes(4, 'big'),
            is_extended_id=True
        )
        try:
            self.bus.send(message)
        except Exception as e:
            if DEBUG:
                print(f"Error sending set_duty command: {e}")

    def set_current(self, current: float, unit_id: int = 0xFF):
        current_i = int(current * 1000)
        message = Message(
            arbitration_id=(self.CAN_PACKET_SET_CURRENT << 8) | unit_id,
            data=current_i.to_bytes(4, 'big'),
            is_extended_id=True
        )
        try:
            self.bus.send(message)
        except Exception as e:
            if DEBUG:
                print(f"Error sending set_current command: {e}")

    def set_rpm(self, rpm: float, unit_id: int = 0xFF):
        with self.rpm_command_lock:
            self.current_rpm_command = rpm
        scaled_rpm = int(rpm * self.RPM_SCALE_FACTOR)
        message = Message(
            arbitration_id=(self.CAN_PACKET_SET_RPM << 8) | unit_id,
            data=scaled_rpm.to_bytes(4, 'big', signed=True),
            is_extended_id=True
        )
        try:
            self.bus.send(message)
        except Exception as e:
            if DEBUG:
                print(f"Error sending set_rpm command: {e}")

    def _send_rpm_command_loop(self):
        while not self.stop_event.is_set():
            with self.rpm_command_lock:
                rpm = self.current_rpm_command
            if rpm != 0:
                self.set_rpm(rpm)
            sleep(0.1)  # Send command every 100ms

    def start_rpm_command_thread(self):
        if self.rpm_command_thread is None or not self.rpm_command_thread.is_alive():
            self.rpm_command_thread = threading.Thread(target=self._send_rpm_command_loop)
            self.rpm_command_thread.start()

    def stop_rpm_command_thread(self):
        if self.rpm_command_thread and self.rpm_command_thread.is_alive():
            self.stop_event.set()
            self.rpm_command_thread.join()
            self.rpm_command_thread = None

    def __repr__(self):
        return f"<CanVesc bus={self.bus} states={self.states}>"

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
