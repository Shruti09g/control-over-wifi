# How to Run Experiments

Important: These scripts require two physical machines.

## 1. Setup

Ensure both laptops are on the same Wi-Fi.

Disable Firewalls (or allow Python/UDP/TCP).

Ensure iperf3 is installed.

## 2. Execution Order

Always start the Controller (Role 2) first, then start the Robot (Role 1).

## 3. Traffic Modes

Mode 1 (Baseline): No interference. Used for sanity checks.

Mode 2 (Uplink Stress): Robot uploads TCP. Tests Queueing Delay (Bufferbloat). Note: This is the primary failure mode.

Mode 3 (Downlink Stress): Controller uploads TCP. Tests Contention Delay (Jitter).

## Troubleshooting

"FileNotFoundError: iperf3": You must download iperf3 and place the .exe (Windows) in this folder or add it to your PATH.

Graphs show 0 Torque: The Robot and Controller are not talking. Check IP addresses and Firewall settings.
