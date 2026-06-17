#!/bin/bash
# snr_sweep_ota.sh — TX gain sweep over-the-air on ORBIT grid.
#
# TX: node3-1  (X310, PCIe/RIO0, SBX-120)
# RX: node3-20 (X310, PCIe/RIO0, SBX-120)
# Both locked to external 10 MHz ref. ~19 m OTA separation.
#
# Run from console (console.grid.orbit-lab.org).
# Files stay on RX node under /root/snr_sweep/.
#
# Usage:
#   bash snr_sweep_ota.sh          # default label "run1"
#   bash snr_sweep_ota.sh run2     # custom label

TX_HOST="root@node3-1"
RX_HOST="root@node3-20"
WORK_DIR="/root/sb2_ota"
ENV="export PYTHONPATH=/usr/local/lib/python3.8/site-packages;"
LABEL="${1:-run1}"

# SBX-120 TX gain: 0–31.5 dB, step 0.5 dB.
# OTA path loss ~65-70 dB at 3.5 GHz over 19 m — keep TX near max.
TX_GAINS=(31 29 27 25)

# RX gain maxed at 31.5 (SBX-120 max) — OTA needs all the gain.
# If clipping warning appears in first capture, drop to 25.
RX_GAIN=31.5

# RX settle (built into rx_capture_ota.py --settle) + capture
RX_SETTLE=5.0    # seconds discarded before recording
RX_DURATION=1.0  # seconds saved

echo "═══════════════════════════════════════════════════════"
echo " SNR Sweep OTA: ${#TX_GAINS[@]} gain points, label=$LABEL"
echo " TX: node3-1  RX: node3-20  RX_GAIN=${RX_GAIN}"
echo " Settle: ${RX_SETTLE}s  Capture: ${RX_DURATION}s per point"
echo "═══════════════════════════════════════════════════════"

ssh "$RX_HOST" "mkdir -p /root/snr_sweep"

# Cleanup on Ctrl+C
trap 'echo " Interrupted — killing TX..."; \
      kill $TX_PID 2>/dev/null; \
      ssh "$TX_HOST" "pkill -f tx_ofdm_ota.py" 2>/dev/null; \
      exit 1' SIGINT SIGTERM

for TX_GAIN in "${TX_GAINS[@]}"; do
    RX_FILE="/root/snr_sweep/rx_${LABEL}_txg${TX_GAIN}.npz"
    echo ""
    echo "--- TX gain=${TX_GAIN} dB | RX gain=${RX_GAIN} dB ---"

    # Start TX in background (timeout covers settle + capture + overhead)
    ssh "$TX_HOST" "$ENV cd ${WORK_DIR} && timeout 30s python3 tx_ofdm_ota.py \
        --gain ${TX_GAIN}" &
    TX_PID=$!

    # Wait for TX to initialize USRP + lock external ref + start transmitting
    sleep 5

    # Capture with retry (X310 over PCIe should be reliable, but just in case)
    ATTEMPT=0
    while [ $ATTEMPT -lt 3 ]; do
        ssh "$RX_HOST" "$ENV cd ${WORK_DIR} && python3 rx_capture_ota.py \
            --gain ${RX_GAIN} \
            --settle ${RX_SETTLE} \
            --duration ${RX_DURATION} \
            --out ${RX_FILE}"

        FSIZE=$(ssh "$RX_HOST" "stat -c%s ${RX_FILE} 2>/dev/null || echo 0")
        # 1s @ 50 MSps = 50M complex64 = ~400 MB. Threshold at 200 MB.
        if [ "$FSIZE" -gt 200000000 ]; then break; fi
        ATTEMPT=$((ATTEMPT + 1))
        echo "  Short capture (${FSIZE} bytes), retry ${ATTEMPT}/3..."
        sleep 2
    done

    # Stop TX
    kill $TX_PID 2>/dev/null
    ssh "$TX_HOST" "pkill -f tx_ofdm_ota.py" 2>/dev/null
    wait $TX_PID 2>/dev/null
    sleep 2
done

echo ""
echo "--- Noise floor (no TX) | RX gain=${RX_GAIN} dB ---"
NOISE_FILE="/root/snr_sweep/rx_${LABEL}_noise.npz"
ssh "$RX_HOST" "$ENV cd ${WORK_DIR} && python3 rx_capture_ota.py \
    --gain ${RX_GAIN} \
    --settle ${RX_SETTLE} \
    --duration ${RX_DURATION} \
    --out ${NOISE_FILE}"

echo ""
echo "═══════════════════════════════════════════════════════"
echo " Done. Files on RX node (node3-20):"
echo "═══════════════════════════════════════════════════════"
ssh "$RX_HOST" "ls -lh /root/snr_sweep/rx_${LABEL}_*.npz"
