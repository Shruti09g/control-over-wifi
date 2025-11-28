# Stability Analysis of Cyber-Physical Systems under Network Congestion

This project investigates the impact of network latency, jitter, and packet loss on real-time feedback control systems. Using a Hardware-in-the-Loop (HIL) simulation of a self-balancing robot distributed across two physical nodes over Wi-Fi, we analyze the effects of TCP interference on UDP control packets.

## System Architecture

Node A (Robot): Runs physics simulation (100Hz) & sends UDP telemetry.

Node B (Controller): Runs PID logic & sends UDP motor commands.

Interference: iperf3 generates controlled TCP background traffic to induce queue saturation.

## Repository Structure

/src: Python scripts for HIL experiments and synthetic simulations.

/img: Generated graphs 

## Prerequisites

Python 3.x (numpy, matplotlib)

iPerf3 installed and added to system PATH (Required for generating network stress).

Two Computers connected to the same Wi-Fi network.

## Quick Start

Navigate to src/.

Run the desired experiment script on both laptops.

Select Role 1 (Robot) on Laptop A and Role 2 (Controller) on Laptop B.

Enter the IP address of the other machine when prompted.

### Author: Shruti Ghoniya
