#!/usr/bin/env python3
import subprocess
import time
import os

# --- Configuration Setup ---
# Enter your exact COSMOS username and node assignments
USERNAME = "your-username"
JUMP_HOST = f"{USERNAME}@sb1.cosmos-lab.org"
TX_NODE = f"root@sdr1-piradio"
RX_NODE = f"root@sdr2-piradio"
CENTER_FREQ = '8e9'

# The gain values we want to sweep (e.g., 0 to 30 dB in steps of 5)
GAINS = [0, 5, 10, 15, 20, 25, 30]
print("\nStarting Fully Automated Cross-Node SNR Sweep...\n")

for gain in GAINS:
    padded_gain = f"{gain:02d}"
    out_file = f"rx_capture_cf{CENTER_FREQ}_g{padded_gain}.npz"
    
    print("\n" + "="*60)
    print(f"SWEEP STEP: Setting TX Gain to {gain} dB\n")
    print("="*60)
    
    print(f"Initializing TX stream on {TX_NODE}...\n")
    tx_cmd = [
        "ssh", "-A", "-J", JUMP_HOST, TX_NODE,
        f"export PYTHONPATH=/usr/local/lib/python3.8/site-packages; cd /home/native/ota_ofdm && python3 tx_ofdm_ota.py --ref internal --rate 25e6 --gain {gain}"
    ]
    tx_process = subprocess.Popen(tx_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    time.sleep(5.0)

    # Check if TX process has already exited (error) or is still running (good)
    retcode = tx_process.poll()
    if retcode is not None:
        # Process already died — print its output
        stdout, stderr = tx_process.communicate()
        print(f"TX process exited early (code {retcode})\n")
        if stdout:
            print("STDOUT:", stdout.decode())
        if stderr:
            print("STDERR:", stderr.decode())
    else:
        print("TX process is running\n")

    # 2. Trigger the Receiver Capture on sr2-piradio
    print(f"Triggering RX capture on {RX_NODE}...\n")
    rx_cmd = [
    "ssh", "-A", "-J", JUMP_HOST, RX_NODE,
    f"export PYTHONPATH=/usr/local/lib/python3.8/site-packages; cd /home/native/ota_ofdm && python3 rx_capture_ota.py --ref internal --rate 25e6 --out ./{out_file}"
    ]

    subprocess.run(rx_cmd)
    
    print("Stopping TX stream...\n")
    # Kill the remote python process cleanly first
    kill_cmd = [
        "ssh", "-A", "-J", JUMP_HOST, TX_NODE,
        "pkill -SIGINT -f tx_ofdm_ota.py"
    ]
    subprocess.run(kill_cmd)
    time.sleep(2.0)  # Give UHD time to release the USRP cleanly

    # Now close the SSH tunnel
    tx_process.terminate()
    tx_process.wait()

    time.sleep(3.0)  # Give the X310 hardware time to fully reset before next iteration
    
    # Pull the captured data file from the remote node back down to your local laptop
    print(f"Pulling {out_file} to local workspace...\n")
    scp_cmd = [
        "scp", "-J", JUMP_HOST, f"{RX_NODE}:/home/native/ota_ofdm/{out_file}", f"./{out_file}"
    ]
    scp_result = subprocess.run(scp_cmd)
    if scp_result.returncode == 0:
        print(f"Success: Saved ./{out_file}\n")
    else:
        print(f"SCP failed for {out_file}\n")

print("Sweep completed! All files have been pulled locally.\n")