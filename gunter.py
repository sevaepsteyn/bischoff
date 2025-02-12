from canvesc import CanVesc, CanVescState
from nunchuck import Nunchuck, NunchuckState
from time import sleep, time
import traceback
import atexit
import sys
import threading

# Global event to signal all threads to stop
stop_event = threading.Event()

canvesc = CanVesc(stop_event)
nunchuck = Nunchuck(stop_event)

# Constants for joystick control
JOYSTICK_MIN = 0
JOYSTICK_MAX = 255
JOYSTICK_MIDDLE = (JOYSTICK_MAX - JOYSTICK_MIN) / 2
DEADZONE = 10  # Adjust this value to change the size of the deadzone
DUTY_MIN = -0.10  # -5% duty cycle
DUTY_MAX = 0.10  # 5% duty cycle

def map_joystick_to_duty(joystick_y):
    if abs(joystick_y - JOYSTICK_MIDDLE) <= DEADZONE:
        return 0
    elif joystick_y > JOYSTICK_MIDDLE:
        # Map upper half to positive duty cycle
        return (joystick_y - (JOYSTICK_MIDDLE + DEADZONE)) / (JOYSTICK_MIDDLE - DEADZONE) * DUTY_MAX
    else:
        # Map lower half to negative duty cycle
        return (joystick_y - (JOYSTICK_MIDDLE - DEADZONE)) / (JOYSTICK_MIDDLE - DEADZONE) * DUTY_MIN

def set_motor_duty(duty):
    for unit_id in canvesc.states.keys():
        try:
            canvesc.set_duty(duty, unit_id)
            print(f"Set VESC {unit_id} duty cycle to {duty:.2%}")
        except Exception as e:
            print(f"Error setting duty cycle for VESC {unit_id}: {e}")
            traceback.print_exc()

def print_vesc_and_nunchuck_state(nunchuck_state):
    print("VESC States:")
    for unit_id, state in canvesc.states.items():
        print(f"VESC {unit_id}: {state}")
    print(f"Nunchuck State: Joystick {nunchuck_state.stick}, Accel {nunchuck_state.accel}, C: {nunchuck_state.button_c}, Z: {nunchuck_state.button_z}")

def stop_and_brake_all_motors():
    for unit_id in canvesc.states.keys():
        try:
            canvesc.set_current(0, unit_id)  # Set current to 0 to stop the motor
            print(f"Stopped and braked VESC {unit_id}")
        except Exception as e:
            print(f"Error stopping VESC {unit_id}: {e}")
            traceback.print_exc()

def cleanup():
    print("Performing cleanup...")
    stop_event.set()  # Signal all threads to stop
    
    try:
        stop_and_brake_all_motors()
        print("All motors stopped.")
    except Exception as e:
        print(f"Error during cleanup: {e}")
    
    try:
        print("Stopping CanVesc...")
        canvesc.stop()
        print("CanVesc stopped.")
    except Exception as e:
        print(f"Error stopping CanVesc: {e}")
    
    try:
        print("Stopping Nunchuck...")
        nunchuck.stop()
        print("Nunchuck stopped.")
    except Exception as e:
        print(f"Error stopping Nunchuck: {e}")
    
    print("Cleanup completed.")

# Register the cleanup function to be called on exit
atexit.register(cleanup)

def main():
    try:
        print("Starting CanVesc and Nunchuck...")
        canvesc.start()
        nunchuck.start()
        print("CanVesc and Nunchuck started. Press Ctrl+C to stop.")
        
        last_duty = 0
        while not stop_event.is_set():
            try:
                state = nunchuck.read()
                
                if state is None:
                    print("Failed to read Nunchuck state. Retrying...")
                    sleep(0.1)
                    continue

                # Get joystick Y position and map to duty cycle
                joystick_y = state.stick[1]
                duty = map_joystick_to_duty(joystick_y)
                
                # Only update motor if duty cycle has changed
                if abs(duty - last_duty) > 0.001:  # Add a small threshold to prevent minute changes
                    set_motor_duty(duty)
                    last_duty = duty

                button_changes = nunchuck.get_button_changes()
                for button, is_pressed in button_changes:
                    if is_pressed:
                        print(f"Nunchuck: {button} button pressed")
                        if button == 'C':
                            print_vesc_and_nunchuck_state(state)
                        elif button == 'Z':
                            stop_and_brake_all_motors()
                    else:
                        print(f"Nunchuck: {button} button released")

                sleep(0.01)  # Small sleep to prevent CPU hogging
            
            except Exception as e:
                print(f"An error occurred in the main loop: {e}")
                traceback.print_exc()
                print("Attempting to continue...")
                sleep(1)  # Wait a bit before retrying
            
    except KeyboardInterrupt:
        print("\nReceived KeyboardInterrupt. Stopping program...")
    except Exception as e:
        print(f"An unhandled error occurred: {e}")
        traceback.print_exc()
    finally:
        print("Exiting main function...")
        stop_event.set()  # Ensure the stop event is set

if __name__ == "__main__":
    main()
    # Wait for cleanup to complete (with timeout)
    cleanup_timeout = 5  # 5 seconds timeout
    cleanup_start = time()
    while time() - cleanup_start < cleanup_timeout:
        if not (canvesc._thread and canvesc._thread.is_alive()) and not (nunchuck._thread and nunchuck._thread.is_alive()):
            break
        sleep(0.1)
    sys.exit(0)
