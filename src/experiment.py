import socket
import time
import struct
import subprocess
import threading
import numpy as np
import matplotlib.pyplot as plt
import os
import sys

# ==========================================
# CONFIGURATION
# ==========================================
MY_PORT = 5005
TARGET_PORT = 5005
IPERF_PORT = 5201
DT = 0.01  # 100Hz Loop
SIM_DURATION = 30 # Seconds

# ==========================================
# UTILS: IPERF3 MANAGER
# ==========================================
def start_iperf_server():
    """Starts iPerf3 Server (Background Sink)"""
    print("[NET] Starting local iPerf3 Server...")
    subprocess.Popen(["iperf3", "-s", "-p", str(IPERF_PORT)], 
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def start_iperf_client(target_ip, mbps, reverse=False):
    """Starts iPerf3 Traffic Generator"""
    print(f"[NET] BLASTING {mbps} Mbps TCP to {target_ip}...")
    cmd = ["iperf3", "-c", target_ip, "-p", str(IPERF_PORT), 
           "-b", f"{mbps}M", "-t", str(SIM_DURATION + 5)]
    if reverse: cmd.append("-R")
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def kill_iperf():
    if os.name == 'nt': os.system("taskkill /f /im iperf3.exe >nul 2>&1")
    else: os.system("pkill iperf3")

# ==========================================
# ROLE 1: THE ROBOT (Laptop A)
# ==========================================
def run_robot(controller_ip, traffic_mode, bandwidth):
    print(f"\n=== I AM THE ROBOT ===")
    print(f"Sending Telemetry -> {controller_ip}")
    print(f"Listening on 0.0.0.0:{MY_PORT}")
    
    # 1. Setup Network
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", MY_PORT))
    sock.setblocking(False)
    
    # 2. Setup Traffic Jam (If applicable)
    kill_iperf()
    start_iperf_server() # Always run server just in case
    
    if traffic_mode == 2: # Uplink Congestion (I send TCP)
        time.sleep(1)
        start_iperf_client(controller_ip, bandwidth, reverse=False)
    
    # 3. Physics Loop
    theta = 0.1
    theta_dot = 0
    last_u = 0
    
    history_t = []
    history_theta = []
    history_u = []
    
    start_time = time.time()
    
    print(">>> SIMULATION STARTED")
    try:
        while (time.time() - start_time) < SIM_DURATION:
            loop_start = time.time()
            
            # A. Physics (Inverted Pendulum)
            alpha = 15.0 * np.sin(theta) + last_u
            theta_dot += alpha * DT
            theta += theta_dot * DT
            theta += np.random.normal(0, 0.002) # Sensor Noise
            
            # B. Send Telemetry
            data = struct.pack('ff', theta, theta_dot)
            sock.sendto(data, (controller_ip, TARGET_PORT))
            
            # C. Receive Command
            try:
                data, _ = sock.recvfrom(1024)
                last_u = struct.unpack('f', data)[0]
            except BlockingIOError:
                pass # Zero Order Hold (Packet Loss/Delay)
            
            # D. Log
            history_t.append(time.time() - start_time)
            history_theta.append(theta)
            history_u.append(last_u)
            
            # E. Timing
            elapsed = time.time() - loop_start
            if elapsed < DT:
                time.sleep(DT - elapsed)
                
    except KeyboardInterrupt:
        pass
    
    print(">>> SIMULATION ENDED")
    kill_iperf()
    
    # 4. Plotting (Only Robot needs to plot)
    plt.figure(figsize=(10, 6))
    plt.subplot(2,1,1)
    plt.plot(history_t, history_theta, 'b')
    plt.axhline(0.2, color='r', linestyle='--')
    plt.axhline(-0.2, color='r', linestyle='--')
    plt.title(f"Robot Stability (Traffic Mode {traffic_mode})")
    plt.ylabel("Angle (rad)")
    plt.grid(True)
    
    plt.subplot(2,1,2)
    plt.plot(history_t, history_u, 'g')
    plt.ylabel("Motor Torque")
    plt.xlabel("Time (s)")
    plt.grid(True)
    plt.show()

# ==========================================
# ROLE 2: THE CONTROLLER (Laptop B)
# ==========================================
def run_controller(robot_ip, traffic_mode, bandwidth):
    print(f"\n=== I AM THE CONTROLLER ===")
    print(f"Sending Commands -> {robot_ip}")
    print(f"Listening on 0.0.0.0:{MY_PORT}")
    
    # PID Gains
    Kp, Kd, Ki = 30.0, 4.0, 0.5
    integral = 0
    prev_error = 0
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", MY_PORT))
    sock.setblocking(False)
    
    # Traffic Setup
    kill_iperf()
    start_iperf_server()
    
    if traffic_mode == 3: # Downlink Congestion (I send TCP to Robot)
        time.sleep(1)
        start_iperf_client(robot_ip, bandwidth, reverse=False)

    print(">>> CONTROLLER ACTIVE (Ctrl+C to stop)")
    try:
        while True:
            try:
                # A. Receive Telemetry
                data, addr = sock.recvfrom(1024)
                theta, theta_dot = struct.unpack('ff', data)
                
                # B. Calculate PID
                error = 0 - theta
                integral += error * DT
                derivative = (error - prev_error) / DT
                u = (Kp * error) + (Ki * integral) + (Kd * derivative)
                u = max(min(u, 50), -50)
                
                # C. Send Command
                reply = struct.pack('f', u)
                sock.sendto(reply, (robot_ip, TARGET_PORT))
                
                prev_error = error
                
            except BlockingIOError:
                pass
            
    except KeyboardInterrupt:
        print("\nStopping...")
        kill_iperf()

# ==========================================
# MAIN MENU
# ==========================================
if __name__ == "__main__":
    print("--- DUAL LAPTOP ROBOT SIMULATOR ---")
    role = input("Select Role:\n1. Robot (Simulates Physics + Plots)\n2. Controller (Runs PID)\nChoice: ")
    
    if role == '1':
        target_ip = input("Enter CONTROLLER IP: ")
        print("\nScenarios:")
        print("1. Baseline (No Traffic)")
        print("2. Uplink Stress (Robot uploads TCP)")
        print("3. Downlink Stress (Controller uploads TCP)")
        mode = int(input("Choice: "))
        bw = 0
        if mode > 1:
            bw = int(input("Enter TCP Bandwidth (Mbps): "))
        run_robot(target_ip, mode, bw)
        
    elif role == '2':
        target_ip = input("Enter ROBOT IP: ")
        # Controller just needs to know if it should blast traffic (Mode 3)
        # We ask the same questions to sync up
        print("\nSync Settings:")
        print("1. Baseline")
        print("2. Uplink Stress")
        print("3. Downlink Stress")
        mode = int(input("Choice (Must match Robot): "))
        bw = 0
        if mode == 3:
            bw = int(input("Enter TCP Bandwidth (Mbps): "))
        run_controller(target_ip, mode, bw)