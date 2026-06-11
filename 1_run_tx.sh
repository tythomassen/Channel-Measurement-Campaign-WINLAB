#!/bin/bash
# Transmitter script for node1-1
# Sends a cosine wave at 900 MHz and logs metadata

TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
META_FILE="tx_metadata_${TIMESTAMP}.json"
FREQ=900000000
RATE=5000000
GAIN=10
WAVE_FREQ=1000000
AMPL=0.2

cat > ${META_FILE} << EOF
{
  "role": "transmitter",
  "node": "node1-1.sb7.cosmos-lab.org",
  "usrp_addr": "192.168.10.2",
  "antenna": "TX/RX",
  "center_freq_hz": ${FREQ},
  "baseband_freq_hz": ${WAVE_FREQ},
  "sample_rate_sps": ${RATE},
  "gain_db": ${GAIN},
  "amplitude": ${AMPL},
  "waveform": "cosine",
  "spatial_arrangement": "sb7 sandbox, node1-1 transmitting to node1-2",
  "timestamp_start": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

echo "[TX] Metadata saved to ${META_FILE}"
echo "[TX] Transmitting cosine at 900 MHz, gain=${GAIN} dB ... (Ctrl+C to stop)"

/usr/lib/uhd/examples/tx_waveforms \
  --freq ${FREQ} \
  --rate ${RATE} \
  --gain ${GAIN} \
  --ampl ${AMPL} \
  --wave-freq ${WAVE_FREQ} \
  --wave-type SINE

echo "[TX] Transmission stopped."
