#!/usr/bin/env python3
"""
tx_ofdm_ota.py — Transmit OFDM waveform continuously via UHD.
Loads tx_waveform.npz from ofdm_frame_gen.py and loops it.

★ Max-SNR defaults, PCIe (resource=RIO0), external 10 MHz ref.

Run on the TX X310 node (node3-1). Ctrl+C to stop.

Usage:
  python3 tx_ofdm_ota.py                                    # defaults (PCIe, external 10 MHz)
  python3 tx_ofdm_ota.py --ref internal                     # use internal oscillator
  python3 tx_ofdm_ota.py --gain 31.5
"""

import argparse, signal, sys, time
import numpy as np
import uhd

# ─── CLI ────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="TX OFDM OTA")
# sb7 sandbox: USRP2 reached over GbE at its fixed IP, not a PCIe X310
parser.add_argument("--args",     type=str,   default="addr=192.168.10.2")
parser.add_argument("--waveform", type=str,   default="tx_waveform.npz")
# USRP2/SBX gain range is still 0-31.5 dB, same as the X310/UBX-160
parser.add_argument("--gain",     type=float, default=31.5)
parser.add_argument("--rate",     type=float, default=None, help="Override sample rate")
parser.add_argument("--freq",     type=float, default=None, help="Override center freq")
# sb7 nodes are standalone — no shared 10 MHz ref/PPS cable between them
parser.add_argument("--ref",      type=str,   default="internal",
                    choices=["internal", "external", "gpsdo"],
                    help="Clock/time reference (default: internal on sb7)")
args = parser.parse_args()

# ─── Load waveform ──────────────────────────────────────────────────
data = np.load(args.waveform)
waveform = data["tx_waveform"].astype(np.complex64)
rate = args.rate if args.rate else float(data["rate"])
freq = args.freq if args.freq else float(data["freq"])
frame_len = int(data["frame_len"])

# NEW: normalize waveform to ~0.8 peak to avoid DAC clipping (max SNR)
peak = np.max(np.abs(waveform))
if peak > 0:
    waveform = waveform * (0.8 / peak)
print(f"Waveform: {len(waveform)} samples, {len(waveform)//frame_len} frames")
print(f"  Peak amplitude after normalization: {np.max(np.abs(waveform)):.3f}")
print(f"Rate: {rate/1e6:.1f} MSps, Freq: {freq/1e9:.3f} GHz, Gain: {args.gain:.1f} dB")

# ─── Setup USRP ────────────────────────────────────────────────────
usrp = uhd.usrp.MultiUSRP(args.args)

# ── NEW: GPSDO lock + time sync ────────────────────────────────────
if args.ref != "internal":
    print(f"\n--- Setting clock/time source to '{args.ref}' ---")
    usrp.set_clock_source(args.ref)
    usrp.set_time_source(args.ref)

    if args.ref == "gpsdo":
        # Wait for GPS lock (polls the mboard sensor)
        print("Waiting for GPS lock...", end="", flush=True)
        timeout = 60  # seconds
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                locked = usrp.get_mboard_sensor("gps_locked", 0).to_bool()
                if locked:
                    break
            except RuntimeError:
                pass
            print(".", end="", flush=True)
            time.sleep(1)
        else:
            print("\nWARNING: GPS lock timeout after 60s — proceeding anyway")
        if locked:
            print(f" locked in {time.time()-t0:.0f}s")

        # Sync USRP time to GPS PPS
        print("Syncing USRP time to next PPS...")
        gps_time = usrp.get_mboard_sensor("gps_time", 0)
        usrp.set_time_next_pps(uhd.types.TimeSpec(int(gps_time.to_int()) + 1))
        time.sleep(1.1)  # wait for PPS edge + margin
        print(f"  USRP time now: {usrp.get_time_now().get_real_secs():.6f}")
        print(f"  GPS  time was: {gps_time.to_int()}")

    elif args.ref == "external":
        # External 10 MHz ref — just wait for ref_locked
        print("Waiting for external ref lock...", end="", flush=True)
        timeout = 10
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                locked = usrp.get_mboard_sensor("ref_locked", 0).to_bool()
                if locked:
                    break
            except RuntimeError:
                pass
            time.sleep(0.5)
        print(f" {'locked' if locked else 'TIMEOUT'}")
else:
    print("Using internal clock (no GPSDO sync)")
# ── END GPSDO block ────────────────────────────────────────────────

usrp.set_tx_rate(rate, 0)
usrp.set_tx_freq(uhd.types.TuneRequest(freq), 0)
usrp.set_tx_gain(args.gain, 0)
time.sleep(0.5)

print(f"\nActual: rate={usrp.get_tx_rate(0)/1e6:.3f} MSps, "
      f"freq={usrp.get_tx_freq(0)/1e9:.6f} GHz, "
      f"gain={usrp.get_tx_gain(0):.1f} dB")

# Check clock source confirmation
try:
    ref_locked = usrp.get_mboard_sensor("ref_locked", 0).to_bool()
    print(f"Ref locked: {ref_locked}")
except RuntimeError:
    pass

# ─── Create TX streamer ────────────────────────────────────────────
st_args = uhd.usrp.StreamArgs("fc32", "sc16")
st_args.channels = [0]
tx_streamer = usrp.get_tx_stream(st_args)
max_samps = tx_streamer.get_max_num_samps()

# NEW: Use timed TX start for clean, deterministic startup
metadata = uhd.types.TXMetadata()
metadata.has_time_spec = True
metadata.time_spec = usrp.get_time_now() + uhd.types.TimeSpec(0.5)

# ─── Graceful shutdown ─────────────────────────────────────────────
running = True
def stop(sig, frame):
    global running
    running = False
signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)

# ─── Transmit loop ─────────────────────────────────────────────────
print("Transmitting... Ctrl+C to stop")
offset = 0
tx_count = 0
first_chunk = True

while running:
    end = min(offset + max_samps, len(waveform))
    chunk = waveform[offset:end].reshape(1, -1)
    nsent = tx_streamer.send(chunk, metadata)

    # After first chunk, clear the time spec so subsequent sends are continuous
    if first_chunk:
        metadata.has_time_spec = False
        first_chunk = False

    tx_count += nsent
    offset += nsent

    # Loop back to start
    if offset >= len(waveform):
        offset = 0

# End of burst
metadata.end_of_burst = True
tx_streamer.send(np.zeros((1, 0), dtype=np.complex64), metadata)
print(f"\nStopped. Sent {tx_count} samples ({tx_count/rate:.3f} s)")
