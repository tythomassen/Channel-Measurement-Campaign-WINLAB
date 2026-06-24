#!/usr/bin/env python3
import subprocess
import time
import os

# --- Configuration Setup ---
# sb7 sandbox: console is the SSH jump host, nodes are node1-1 (TX) / node1-2 (RX),
# each with its own directly-attached USRP2 (no PCIe X310 here).
USERNAME = "tyler_thomassen"
JUMP_HOST = f"{USERNAME}@console.sb7.cosmos-lab.org"
TX_NODE = "root@node1-1.sb7.cosmos-lab.org"
RX_NODE = "root@node1-2.sb7.cosmos-lab.org"

# Remote working directory on both nodes — created by the deploy step below.
REMOTE_DIR = "/root/ota_ofdm"

# USRP2/SBX covers 400 MHz-4400 MHz, so keep this under that ceiling
# (the X310 setup could go to 8 GHz; sb7 cannot).
CENTER_FREQ = '3.5e9'

# USRP2 over GbE can't sustain X310-class rates — 5 MSps is the rate
# proven to work reliably on sb7 (see ORBIT sb7 IQ-capture notes).
RATE = '5e6'

# Local files that must exist before running this script.
LOCAL_FILES = ["tx_ofdm_ota.py", "rx_capture_ota.py", "tx_waveform.npz"]

# The gain values we want to sweep. Capped at 15 dB — at fixed RX gain
# (31.5 dB), TX gains of 20+ clip the USRP2's ADC (see RUNBOOK.md).
GAINS = [0, 5, 10, 15]

# --- Physical experiment context (not measured by the radio) ---
# Fill these in to match the actual sb7 node1-1/node1-2 deployment;
# they get written into every capture's .sigmf-meta.
ENVIRONMENT = "unspecified"      # e.g. "indoor-lab", "anechoic", "outdoor"
DISTANCE_M = None                # TX-RX separation in meters
LINK_CONDITION = "unspecified"   # "los", "nlos", or "unspecified"


def deploy_files():
    """Push the TX/RX scripts and waveform to both sb7 nodes via the console jump host."""
    print("\n--- Deploying scripts + waveform to TX/RX nodes ---\n")
    for node in (TX_NODE, RX_NODE):
        mkdir_cmd = ["ssh", "-A", "-J", JUMP_HOST, node, f"mkdir -p {REMOTE_DIR}"]
        subprocess.run(mkdir_cmd, check=True)
        for f in LOCAL_FILES:
            if not os.path.exists(f):
                raise FileNotFoundError(f"Missing local file: {f}")
            scp_cmd = ["scp", "-J", JUMP_HOST, f, f"{node}:{REMOTE_DIR}/{f}"]
            print(f"  Pushing {f} -> {node}:{REMOTE_DIR}/")
            subprocess.run(scp_cmd, check=True)
    print("\nDeploy complete.\n")


def context_args(tx_gain=None):
    """Shared --environment/--distance-m/--link-condition (+ optional --tx-gain) flags."""
    parts = [f"--environment {ENVIRONMENT}", f"--link-condition {LINK_CONDITION}"]
    if DISTANCE_M is not None:
        parts.append(f"--distance-m {DISTANCE_M}")
    if tx_gain is not None:
        parts.append(f"--tx-gain {tx_gain}")
    return " ".join(parts)


def main():
    deploy_files()

    print("\nStarting Fully Automated Cross-Node SNR Sweep (sb7, USRP2)...\n")

    for gain in GAINS:
        padded_gain = f"{gain:02d}"
        out_base = f"rx_capture_cf{CENTER_FREQ}_g{padded_gain}"

        print("\n" + "=" * 60)
        print(f"SWEEP STEP: Setting TX Gain to {gain} dB\n")
        print("=" * 60)

        print(f"Initializing TX stream on {TX_NODE}...\n")
        tx_cmd = [
            "ssh", "-A", "-J", JUMP_HOST, TX_NODE,
            f"export PYTHONPATH=/usr/local/lib/python3.8/site-packages; "
            f"cd {REMOTE_DIR} && python3 tx_ofdm_ota.py "
            f"--ref internal --rate {RATE} --freq {CENTER_FREQ} --gain {gain}"
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

        # 2. Trigger the Receiver Capture on node1-2
        print(f"Triggering RX capture on {RX_NODE}...\n")
        rx_cmd = [
            "ssh", "-A", "-J", JUMP_HOST, RX_NODE,
            f"export PYTHONPATH=/usr/local/lib/python3.8/site-packages; "
            f"cd {REMOTE_DIR} && python3 rx_capture_ota.py "
            f"--ref internal --rate {RATE} --freq {CENTER_FREQ} --out ./{out_base} "
            f"{context_args(tx_gain=gain)}"
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

        time.sleep(3.0)  # Give the USRP2 time to fully reset before next iteration

        print(f"Capture saved on {RX_NODE}:{REMOTE_DIR}/{out_base}.sigmf-data (+.sigmf-meta)\n")

    # Noise floor — capture with TX off, needed by the postprocessing notebook
    # to compute SNR relative to the actual noise floor at each gain step.
    print("\n" + "=" * 60)
    print("Capturing noise floor (TX off)\n")
    print("=" * 60)
    noise_base = "rx_noise"
    rx_cmd = [
        "ssh", "-A", "-J", JUMP_HOST, RX_NODE,
        f"export PYTHONPATH=/usr/local/lib/python3.8/site-packages; "
        f"cd {REMOTE_DIR} && python3 rx_capture_ota.py "
        f"--ref internal --rate {RATE} --freq {CENTER_FREQ} --out ./{noise_base} "
        f"{context_args()}"
    ]
    subprocess.run(rx_cmd)
    print(f"Capture saved on {RX_NODE}:{REMOTE_DIR}/{noise_base}.sigmf-data (+.sigmf-meta)\n")

    print(f"Sweep completed! All captures remain on {RX_NODE}:{REMOTE_DIR}/ — nothing was pulled locally.\n")


if __name__ == "__main__":
    main()
