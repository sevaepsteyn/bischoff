#!/usr/bin/python3
import time
import serial
from threading import Event
from pyvesc.VESC.messages import GetValues, SetDutyCycle, SetCurrent, SetCurrentBrake
from pyvesc.protocol.interface import encode
from nunchuck import Nunchuck

class MultiVESCController:
    def __init__(self, serial_port="/dev/ttyACM0", baudrate=115200, num_motors=4):
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.num_motors = num_motors
        self._port = None
        try:
            # Open serial port directly
            self._port = serial.Serial(
                port=self.serial_port,
                baudrate=self.baudrate,
                timeout=0.05
            )
            
            # Force initial state
            print("Setting initial zero current...")
            for _ in range(3):  # Send multiple times to ensure it takes
                self.set_current([0] * self.num_motors)
                time.sleep(0.1)
            
            # Get CAN status
            self.can_status = self.get_can_status()
            
            print(f"Successfully connected to {self.num_motors} VESCs")
        except Exception as e:
            print(f"Failed to connect to VESC: {e}")
            if self._port and self._port.is_open:
                self._port.close()
            raise

    def get_can_status(self):
        """Query VESC CAN status and configuration"""
        try:
            status = []
            status.append("=== VESC System Configuration ===")
            status.append(f"Master VESC on {self.serial_port}")
            status.append(f"Configured for {self.num_motors} motors")

            # Commands based on VESC protocol
            COMM_FW_VERSION = b'\x00'  # Firmware version command
            COMM_GET_VALUES = b'\x04'  # Get values command
            
            status.append("\nChecking VESC firmware:")
            try:
                # Send firmware version request
                packet = b'\x02' + COMM_FW_VERSION + b'\x03'  # Start byte + command + end byte
                self._port.write(packet)
                time.sleep(0.1)
                
                if self._port.in_waiting:
                    response = self._port.read(self._port.in_waiting)
                    status.append(f"Response received: {len(response)} bytes")
                    status.append(f"Raw response: {response.hex()}")
                else:
                    status.append("No firmware response")

            except Exception as e:
                status.append(f"Firmware query error: {str(e)}")

            # Try to read values directly from each expected VESC
            status.append("\nScanning for VESCs:")
            for i in range(self.num_motors):
                try:
                    # Send ping using direct protocol
                    packet = b'\x02' + bytes([i]) + COMM_GET_VALUES + b'\x03'
                    self._port.write(packet)
                    time.sleep(0.1)
                    
                    if self._port.in_waiting:
                        response = self._port.read(self._port.in_waiting)
                        status.append(f"VESC {i}: Response {len(response)} bytes")
                    else:
                        status.append(f"VESC {i}: No response")
                        
                except Exception as e:
                    status.append(f"VESC {i}: Error - {str(e)}")

            # Read any remaining data
            if self._port.in_waiting:
                self._port.read(self._port.in_waiting)
                
            return status
            
        except Exception as e:
            return [f"Error getting CAN status: {e}"]

    def set_current(self, currents):
        """Set motor currents in amperes
        currents: list of current values for each motor"""
        try:
            # Send command to each motor
            for motor_id, current in enumerate(currents):
                # Create SetCurrent command with CAN ID
                msg = encode(SetCurrent(current))
                self._port.write(msg)
                print(f"Motor {motor_id}: Sent current command: {current}A")
                time.sleep(0.002)  # Small delay between commands
        except Exception as e:
            print(f"Error setting currents: {e}")

    def brake(self, brake_currents):
        """Apply brake with specified currents in amperes"""
        try:
            for motor_id, current in enumerate(brake_currents):
                msg = encode(SetCurrentBrake(current))
                self._port.write(msg)
                print(f"Motor {motor_id}: Sent brake command: {current}A")
                time.sleep(0.002)
        except Exception as e:
            print(f"Error applying brakes: {e}")

    def close(self):
        """Close the serial port"""
        try:
            print("Setting zero current before closing...")
            self.set_current([0] * self.num_motors)
            time.sleep(0.1)
            if self._port and self._port.is_open:
                self._port.close()
        except Exception as e:
            print(f"Error closing VESC: {e}")

def main():
    # Configuration
    NUM_MOTORS = 4  # Total number of motors (2 dual VESCs = 4 motors)
    MAX_CURRENT = 20.0  # Maximum motor current in amperes
    BRAKE_CURRENT = 10.0  # Brake current in amperes
    DEADZONE = 0.1  # 10% deadzone
    UPDATE_RATE = 50  # Hz

    vesc = None
    nunchuck = None
    stop_event = Event()

    try:
        print("\n=== System Configuration ===")
        print(f"Number of motors: {NUM_MOTORS}")
        print(f"Max current: {MAX_CURRENT}A")
        print(f"Brake current: {BRAKE_CURRENT}A")
        print(f"Deadzone: {DEADZONE * 100}%")
        print(f"Update rate: {UPDATE_RATE}Hz")
        
        print("\n=== Initializing Hardware ===")
        vesc = MultiVESCController(num_motors=NUM_MOTORS)
        
        print("\n=== Serial Port Info ===")
        print(f"Port: {vesc.serial_port}")
        print(f"Baudrate: {vesc.baudrate}")
        print(f"Port open: {vesc._port.is_open}")
        
        print("\n=== VESC CAN Status ===")
        for line in vesc.can_status:
            print(line)
        
        print("\n=== Initializing Nunchuck ===")
        nunchuck = Nunchuck(stop_event)
        nunchuck.start()
        
        # Get initial nunchuck state
        time.sleep(0.1)  # Wait for first reading
        print("\n=== Initial Nunchuck State ===")
        print(f"Joystick: {nunchuck.state.stick}")
        print(f"Buttons: C={nunchuck.state.button_c} Z={nunchuck.state.button_z}")
        print(f"Accelerometer: {nunchuck.state.accel}")
        
        print("\n=== Control Instructions ===")
        print("- Use joystick Y-axis for throttle")
        print("- Press Z button for brake")
        print("- Use Ctrl+C to exit")
        
        input("\nPress Enter to start control loop...")

        while not stop_event.is_set():
            try:
                state = nunchuck.state
                
                if state.button_z:
                    # Apply brake to all motors
                    brake_currents = [BRAKE_CURRENT] * NUM_MOTORS
                    vesc.brake(brake_currents)
                    print(f"Braking all motors: {BRAKE_CURRENT}A")
                    continue

                # Get Y axis and normalize from 0-255 to -1.0 to 1.0
                joy_y = (state.stick[1] - 128) / 128.0

                # Apply deadzone
                if abs(joy_y) < DEADZONE:
                    currents = [0] * NUM_MOTORS
                    print("In deadzone - setting zero current")
                else:
                    # Scale the remaining range to still use full output range
                    normalized = (abs(joy_y) - DEADZONE) / (1 - DEADZONE)
                    if joy_y < 0:
                        normalized = -normalized
                    currents = [normalized * MAX_CURRENT] * NUM_MOTORS

                vesc.set_current(currents)
                print(f"Joystick: {joy_y:.3f}, Currents: {currents[0]:.2f}A")

                time.sleep(1.0 / UPDATE_RATE)

            except KeyboardInterrupt:
                print("\nShutting down...")
                stop_event.set()
                break
            except Exception as e:
                print(f"Error during operation: {e}")
                # On error, set current to 0 for safety
                if vesc:
                    vesc.set_current([0] * NUM_MOTORS)
                time.sleep(1)

    except Exception as e:
        print(f"Setup failed: {e}")
    finally:
        if vesc:
            vesc.close()
        if nunchuck:
            nunchuck.stop()

if __name__ == "__main__":
    main()
