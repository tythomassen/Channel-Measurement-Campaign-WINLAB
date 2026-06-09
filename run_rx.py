#!/usr/bin/env python3
# Receiver script for node1-2
# Captures IQ samples and writes timestamped metadata

import json
import subprocess
import datetime
import sys

FREQ = 900e6
RATE = 1e6
GAIN = 10
DURATION = 10  # seconds — change this as needed
NSAMPS = int(RATE * DURATION)

timestamp = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')
iq_file = f"iq_capture_{timestamp}.dat"
meta_file = f"iq_capture_{timestamp}.json"

metadata = {
    "role": "receiver",
    "node": "node1-2.sb7.cosmos-lab.org",
    "usrp_addr": "192.168.10.2",
    "antenna": "RX2",
    "center_freq_hz": FREQ,
    "sample_rate_sps": RATE,
    "gain_db": GAIN,
    "duration_s": DURATION,
    "num_samples": NSAMPS,
    "format": "complex float32 (interleaved I/Q)",
    "file": iq_file,
    "timestamp_start": datetime.datetime.utcnow().isoformat() + "Z",
    "spatial_arrangement": "sb7 sandbox, node1-2 receiving from node1-1",
    "known_transmitter": {
        "node": "node1-1.sb7.cosmos-lab.org",
        "center_freq_hz": 900e6,
        "baseband_freq_hz": 1e6,
        "sample_rate_sps": 5e6,
        "gain_db": 10,
        "amplitude": 0.2,
        "waveform": "cosine",
        "antenna": "TX/RX"
    }
}

print(f"[RX] Capturing {DURATION}s of IQ at {FREQ/1e6:.0f} MHz -> {iq_file}")

subprocess.run([
    '/usr/lib/uhd/examples/rx_samples_to_file',
    '--freq', str(int(FREQ)),
    '--rate', str(int(RATE)),
    '--gain', str(GAIN),
    '--nsamps', str(NSAMPS),
    '--type', 'float',
    '--file', iq_file
])

metadata['timestamp_end'] = datetime.datetime.utcnow().isoformat() + "Z"

with open(meta_file, 'w') as f:
    json.dump(metadata, f, indent=2)

print(f"[RX] Done.")
print(f"[RX] IQ data  -> {iq_file}")
print(f"[RX] Metadata -> {meta_file}")
