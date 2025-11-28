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

# EXPERIMENT SETTINGS
NUM_TRIALS = 5         # Run each freq 5 times to get an average
RUN_DURATION = 5.0     # Duration per trial (seconds)
FAILURE_THRESHOLD = 0.2 # Angle (rad) at which we consider it a "Fall"

# FREQUENCIES TO TEST (Hz)
TEST_FREQUENCIES = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

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
           "-b", f"{mbps}M", "-t", "9999"]
    if reverse: cmd.append("-R")
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def kill_iperf():
    if os.name == 'nt': os.system("taskkill /f /im iperf3.exe >nul 2>&1")
    else: os.system("pkill iperf3")

# ==========================================
# ROLE 1: THE ROBOT (Monte Carlo Sender)
# ==========================================
def run_robot(controller_ip, traffic_mode, bandwidth):
    print(f"\n=== I AM THE ROBOT (MONTE CARLO MODE) ===")
    print(f"Sending Telemetry -> {controller_ip}")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", MY_PORT))
    sock.setblocking(False)
    
    # Setup Traffic
    kill_iperf()
    start_iperf_server()
    if traffic_mode == 2: # Uplink Congestion
        time.sleep(1)
        start_iperf_client(controller_ip, bandwidth)
    
    # Store Final Results
    reliability_scores = []
    avg_rmse_scores = []
    
    # === OUTER LOOP: FREQUENCIES ===
    for freq in TEST_FREQUENCIES:
        target_dt = 1.0 / freq
        success_count = 0
        rmse_accum = 0
        
        print(f"\n>>> TESTING {freq} Hz ({NUM_TRIALS} Trials)")
        
        # === INNER LOOP: TRIALS ===
        for i in range(NUM_TRIALS):
            # Reset Physics
            theta = 0.1
            theta_dot = 0
            last_u = 0
            history_theta = []
            
            # Brief pause between trials to let Controller reset
            time.sleep(1.0) 
            
            run_start = time.time()
            fell = False
            
            try:
                while (time.time() - run_start) < RUN_DURATION:
                    loop_start = time.time()
                    
                    # A. Physics (Inverted Pendulum)
                    alpha = 15.0 * np.sin(theta) + last_u
                    theta_dot += alpha * target_dt
                    theta += theta_dot * target_dt
                    theta += np.random.normal(0, 0.002) # Sensor Noise
                    
                    # B. Comms
                    data = struct.pack('ff', theta, theta_dot)
                    sock.sendto(data, (controller_ip, TARGET_PORT))
                    
                    try:
                        data, _ = sock.recvfrom(1024)
                        last_u = struct.unpack('f', data)[0]
                    except BlockingIOError:
                        pass
                    
                    history_theta.append(theta)
                    
                    # C. Fall Check
                    if abs(theta) > 1.0: # Hard Fall limit
                        fell = True
                        break

                    # D. Precision Timing
                    elapsed = time.time() - loop_start
                    if elapsed < target_dt:
                        time.sleep(target_dt - elapsed)
            
            except KeyboardInterrupt:
                kill_iperf()
                return

            # Analyze Trial
            if not fell:
                # Calculate RMSE only for successful runs
                current_rmse = np.sqrt(np.mean(np.array(history_theta)**2))
                # Check if it was stable (RMSE < Threshold)
                if current_rmse < FAILURE_THRESHOLD:
                    success_count += 1
                    rmse_accum += current_rmse
                    print(f"    Trial {i+1}: PASS (RMSE={current_rmse:.3f})")
                else:
                    print(f"    Trial {i+1}: MARGINAL (RMSE={current_rmse:.3f})")
            else:
                print(f"    Trial {i+1}: FAIL (Robot Fell)")
        
        # Calculate Stats for this Frequency
        reliability = (success_count / NUM_TRIALS) * 100
        
        # Avoid divide by zero if 0 successes
        if success_count > 0:
            avg_rmse = rmse_accum / success_count
        else:
            avg_rmse = 1.0 # High penalty value
            
        reliability_scores.append(reliability)
        avg_rmse_scores.append(avg_rmse)
        print(f"  -> Reliability: {reliability}%")

    kill_iperf()
    
    # === PLOTTING ===
    plt.figure(figsize=(10, 8))
    
    # Plot 1: Reliability (Probability of Success)
    plt.subplot(2, 1, 1)
    plt.plot(TEST_FREQUENCIES, reliability_scores, 'g-o', linewidth=2)
    plt.axhline(50, color='r', linestyle='--', label='50% Reliability')
    plt.title(f"System Reliability vs Control Frequency (N={NUM_TRIALS})")
    plt.ylabel("Success Rate (%)")
    plt.grid(True)
    plt.ylim(-5, 105)
    plt.legend()
    
    # Plot 2: Stability (RMSE of Successful runs)
    plt.subplot(2, 1, 2)
    plt.plot(TEST_FREQUENCIES, avg_rmse_scores, 'b-s', linewidth=2)
    plt.title("Average Stability (RMSE) of Successful Trials")
    plt.xlabel("Control Frequency (Hz)")
    plt.ylabel("RMSE (rad)")
    plt.grid(True)
    
    plt.tight_layout()
    plt.show()

# ==========================================
# ROLE 2: THE CONTROLLER (Adaptive Receiver)
# ==========================================
def run_controller(robot_ip, traffic_mode, bandwidth):
    print(f"\n=== I AM THE CONTROLLER (ADAPTIVE MODE) ===")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", MY_PORT))
    sock.setblocking(False)
    
    kill_iperf()
    start_iperf_server()
    if traffic_mode == 3:
        time.sleep(1)
        start_iperf_client(robot_ip, bandwidth)

    Kp, Kd, Ki = 30.0, 4.0, 0.5
    integral = 0
    prev_error = 0
    last_packet_time = time.time()
    
    print(">>> Waiting for packets... (I will auto-detect Frequency)")
    
    try:
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                now = time.time()
                
                # 1. AUTO-RESET LOGIC
                # If we haven't heard from robot in 0.5 seconds, it's a new trial
                if (now - last_packet_time) > 0.5:
                    integral = 0
                    prev_error = 0
                    
                # 2. DYNAMIC DT CALCULATION
                dt_dynamic = now - last_packet_time
                if dt_dynamic <= 0.0001: dt_dynamic = 0.01 
                # Cap dt to avoid massive derivative spikes on first packet
                if dt_dynamic > 0.2: dt_dynamic = 0.01
                
                last_packet_time = now
                
                theta, theta_dot = struct.unpack('ff', data)
                
                # 3. PID CONTROL
                error = 0 - theta
                integral += error * dt_dynamic
                derivative = (error - prev_error) / dt_dynamic
                
                u = (Kp * error) + (Ki * integral) + (Kd * derivative)
                u = max(min(u, 50), -50)
                
                reply = struct.pack('f', u)
                sock.sendto(reply, (robot_ip, TARGET_PORT))
                prev_error = error
                
            except BlockingIOError:
                pass
            
    except KeyboardInterrupt:
        kill_iperf()

# ==========================================
# MAIN MENU
# ==========================================
if __name__ == "__main__":
    print("--- MONTE CARLO STABILITY EXPERIMENT ---")
    role = input("Select Role:\n1. Robot (Laptop A)\n2. Controller (Laptop B)\nChoice: ")
    
    if role == '1':
        target_ip = input("Enter CONTROLLER IP: ")
        print("1. Baseline (No Traffic)")
        print("2. Uplink Stress")
        mode = int(input("Choice: "))
        bw = 0
        if mode == 2: bw = int(input("Enter Bandwidth: "))
        run_robot(target_ip, mode, bw)
        
    elif role == '2':
        target_ip = input("Enter ROBOT IP: ")
        print("1. Baseline")
        print("3. Downlink Stress")
        mode = int(input("Choice: "))
        bw = 0
        if mode == 3: bw = int(input("Enter Bandwidth: "))
        run_controller(target_ip, mode, bw)