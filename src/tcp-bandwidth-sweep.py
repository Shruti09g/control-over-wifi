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
SIM_DURATION = 15 # Seconds

# ==========================================
# UTILS: IPERF3 MANAGER
# ==========================================
def start_iperf_server():
    print("[NET] Starting local iPerf3 Server...")
    subprocess.Popen(["iperf3", "-s", "-p", str(IPERF_PORT)], 
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def start_iperf_client(target_ip, mbps, reverse=False):
    if mbps <= 0: return
    print(f"[NET] BLASTING {mbps} Mbps TCP to {target_ip}...")
    cmd = ["iperf3", "-c", target_ip, "-p", str(IPERF_PORT), 
       "-b", f"{mbps}M", "-t", str(SIM_DURATION + 5)]
    if reverse: cmd.append("-R")
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def kill_iperf():
    if os.name == 'nt': os.system("taskkill /f /im iperf3.exe >nul 2>&1")
    else: os.system("pkill iperf3")

# ==========================================
# UTILS: NETWORK FORENSICS (NEW!)
# ==========================================
def generate_network_report(arrival_times, seq_history):
    if len(arrival_times) < 2:
        print("Not enough data.")
        return

    # 1. Physical Loss (What you calculate now)
    seq_sorted = np.sort(seq_history)
    expected_count = seq_sorted[-1] - seq_sorted[0] + 1
    physical_loss = expected_count - len(seq_sorted)
    
    # 2. "Effective" Loss (The new metric)
    # We define a "Deadline". If packet takes > 50ms (0.05s) between arrivals, it's "Effective Loss"
    DEADLINE = 0.05 
    deltas = np.diff(arrival_times)
    
    # Count how many intervals exceeded the deadline
    late_packets = np.sum(deltas > DEADLINE)
    
    # Total "Bad" Packets
    total_bad = physical_loss + late_packets
    total_bad_percent = (total_bad / expected_count) * 100

    print("\n" + "="*40)
    print("   REAL-TIME CONTROL ANALYSIS")
    print("="*40)
    print(f"Physical Drop Rate: {physical_loss} pkts ({(physical_loss/expected_count)*100:.1f}%)")
    print(f"High Latency Rate:  {late_packets} pkts (Late > 50ms)")
    print("-" * 20)
    print(f"EFFECTIVE LOSS:     {total_bad_percent:.2f}%")
    print("="*40 + "\n")

    
    # 3. Plot Forensics
    plt.figure(figsize=(12, 5))
    
    # Histogram of Inter-Arrival Times
    plt.subplot(1, 2, 1)
    # Filter out extreme outliers for better histogram viz
    filtered_deltas = deltas[deltas < 0.1] 
    plt.hist(filtered_deltas * 1000, bins=30, color='purple', alpha=0.7)
    plt.axvline(10, color='r', linestyle='--', label='Target (10ms)')
    plt.xlabel('Inter-Arrival Time (ms)')
    plt.ylabel('Count')
    plt.title('Jitter Histogram (The "Heartbeat")')
    plt.legend()
    
    # Time Series of Arrival Gaps
    plt.subplot(1, 2, 2)
    plt.plot(deltas * 1000, 'r-', linewidth=0.5)
    plt.axhline(10, color='k', linestyle='--')
    plt.ylabel('Time Since Last Packet (ms)')
    plt.xlabel('Packet Index')
    plt.title('Latency Spikes Over Time')
    plt.grid(True)
    
    plt.tight_layout()
    plt.show()

# ==========================================
# ROLE 1: THE ROBOT (Sender)
# ==========================================
def run_robot(controller_ip, traffic_mode, bandwidth):
    print(f"\n=== I AM THE ROBOT ===")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", MY_PORT))
    sock.setblocking(False)
    
    kill_iperf()
    start_iperf_server()
    if traffic_mode == 2: # Uplink Stress
        time.sleep(1)
        start_iperf_client(controller_ip, bandwidth)
    
    theta = 0.1
    theta_dot = 0
    last_u = 0
    seq_counter = 0
    
    start_time = time.time()
    print(">>> ROBOT RUNNING...")
    
    try:
        while (time.time() - start_time) < SIM_DURATION:
            loop_start = time.time()
            
            # Physics
            alpha = 15.0 * np.sin(theta) + last_u
            theta_dot += alpha * DT
            theta += theta_dot * DT
            theta += np.random.normal(0, 0.002) 
            
            # Send
            seq_counter += 1
            data = struct.pack('Iff', seq_counter, theta, theta_dot)
            sock.sendto(data, (controller_ip, TARGET_PORT))
            
            # Receive
            try:
                data, _ = sock.recvfrom(1024)
                ctrl_seq, last_u = struct.unpack('If', data)
            except BlockingIOError:
                pass 
            
            # Timing
            elapsed = time.time() - loop_start
            if elapsed < DT:
                time.sleep(DT - elapsed)
                
    except KeyboardInterrupt:
        pass
    
    print(">>> ROBOT FINISHED")
    kill_iperf()

# ==========================================
# ROLE 2: THE CONTROLLER (Receiver/Probe)
# ==========================================
def run_controller(robot_ip, traffic_mode, bandwidth):
    print(f"\n=== I AM THE CONTROLLER (FORENSICS MODE) ===")
    print(f"Sending Commands -> {robot_ip}")
    
    Kp, Kd, Ki = 30.0, 4.0, 0.5
    integral = 0
    prev_error = 0
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", MY_PORT))
    sock.setblocking(False)
    
    kill_iperf()
    start_iperf_server()
    
    if traffic_mode == 3: # Downlink Stress
        time.sleep(1)
        start_iperf_client(robot_ip, bandwidth)

    # STORAGE FOR FORENSICS
    arrival_times = []
    seq_history = []
    
    print(f">>> COLLECTING DATA FOR {SIM_DURATION} SECONDS...")
    start_time = time.time()
    
    try:
        while (time.time() - start_time) < SIM_DURATION:
            try:
                data, addr = sock.recvfrom(1024)
                
                # 1. LOGGING (The Forensics Step)
                now = time.time()
                seq_id, theta, theta_dot = struct.unpack('Iff', data)
                
                arrival_times.append(now)
                seq_history.append(seq_id)
                
                # 2. PID CONTROL
                error = 0 - theta
                integral += error * DT
                derivative = (error - prev_error) / DT
                u = (Kp * error) + (Ki * integral) + (Kd * derivative)
                u = max(min(u, 50), -50)
                
                reply = struct.pack('If', seq_id, u)
                sock.sendto(reply, (robot_ip, TARGET_PORT))
                prev_error = error
                
            except BlockingIOError:
                pass
            
    except KeyboardInterrupt:
        pass
        
    print(">>> CONTROLLER FINISHED. GENERATING REPORT...")
    kill_iperf()
    
    # 3. GENERATE REPORT
    generate_network_report(arrival_times, seq_history)

# ==========================================
# MAIN MENU
# ==========================================
if __name__ == "__main__":
    print("--- STEP 2: NETWORK FORENSICS TOOL ---")
    role = input("Select Role:\n1. Robot (Laptop A)\n2. Controller (Laptop B)\nChoice: ")
    
    if role == '1':
        target_ip = input("Enter CONTROLLER IP: ")
        mode = 2 # Force Uplink Stress for this study
        print(f"\nMode set to: Uplink Stress (Robot -> Ctrl)")
        bw = int(input("Enter TCP Bandwidth (Mbps): "))
        run_robot(target_ip, mode, bw)
        
    elif role == '2':
        target_ip = input("Enter ROBOT IP: ")
        print(f"\nMode set to: Uplink Stress (Receiver)")
        run_controller(target_ip, 2, 0)