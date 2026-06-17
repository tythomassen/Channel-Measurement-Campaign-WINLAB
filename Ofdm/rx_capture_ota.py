#!/usr/bin/env python3
"""
rx_capture_ota.py — Capture raw IQ samples via UHD, save to .npz.
All OFDM processing happens offline in ofdm_postprocess.py.

★ Settling-time flush, max-SNR defaults, PCIe (resource=RIO0), external 10 MHz ref.

Run on the RX X310 node (node3-20). Captures a fixed duration.

Usage:
  python3 rx_capture_ota.py                                # defaults (PCIe, external 10 MHz)
  python3 rx_capture_ota.py --ref internal                 # use internal oscillator
  python3 rx_capture_ota.py --settle 0.5 --duration 1.0    # 0.5s flush, 1s capture
  python3 rx_capture_ota.py --gain 25 --out rx_p01.npz     # lower gain if clipping
"""

import argparse, sys, time
import numpy as np
import uhd

# ─── CLI ────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="RX capture OTA")
parser.add_argument("--args",     type=str,   default="type=x300,resource=RIO0")
parser.add_argument("--rate",     type=float, default=50e6)
parser.add_argument("--freq",     type=float, default=3.5e9)
# CHANGED: gain 31 → 31.5 (UBX-160 max — back off if clipping, see print below)
parser.add_argument("--gain",     type=float, default=31.5)
parser.add_argument("--duration", type=float, default=2.0,  help="Capture duration (s)")
# NEW: settling time — flush this many seconds of samples before recording
parser.add_argument("--settle",   type=float, default=0.5,
                    help="Settling time (s): samples received then discarded before capture")
parser.add_argument("--out",      type=str,   default="rx_capture.npz")
# NEW: clock/time reference source
parser.add_argument("--ref",      type=str,   default="external",
                    choices=["internal", "external", "gpsdo"],
                    help="Clock/time reference (default: external)")
args = parser.parse_args()

nsamps_settle = int(args.rate * args.settle)
nsamps_capture = int(args.rate * args.duration)
nsamps_total = nsamps_settle + nsamps_capture
print(f"Settle: {nsamps_settle} samples ({args.settle}s) — will be discarded")
print(f"Capture: {nsamps_capture} samples ({args.duration}s) — will be saved")
print(f"Total RX: {nsamps_total} samples ({args.settle + args.duration}s)")
print(f"Rate: {args.rate/1e6:.1f} MSps, Freq: {args.freq/1e9:.3f} GHz, "
      f"Gain: {args.gain:.1f} dB")

# ─── Setup USRP ────────────────────────────────────────────────────
usrp = uhd.usrp.MultiUSRP(args.args)

# ── NEW: GPSDO lock + time sync (same block as TX) ─────────────────
if args.ref != "internal":
    print(f"\n--- Setting clock/time source to '{args.ref}' ---")
    usrp.set_clock_source(args.ref)
    usrp.set_time_source(args.ref)

    if args.ref == "gpsdo":
        print("Waiting for GPS lock...", end="", flush=True)
        timeout = 60
        t0 = time.time()
        locked = False
        while time.time() - t0 < timeout:
            try:
                locked = usrp.get_mboard_sensor("gps_locked", 0).to_bool()
                if locked:
                    break
            except RuntimeError:
                pass
            print(".", end="", flush=True)
            time.sleep(1)
        if locked:
            print(f" locked in {time.time()-t0:.0f}s")
        else:
            print("\nWARNING: GPS lock timeout after 60s — proceeding anyway")

        # Sync USRP time to GPS PPS
        print("Syncing USRP time to next PPS...")
        gps_time = usrp.get_mboard_sensor("gps_time", 0)
        usrp.set_time_next_pps(uhd.types.TimeSpec(int(gps_time.to_int()) + 1))
        time.sleep(1.1)
        print(f"  USRP time now: {usrp.get_time_now().get_real_secs():.6f}")
        print(f"  GPS  time was: {gps_time.to_int()}")

    elif args.ref == "external":
        print("Waiting for external ref lock...", end="", flush=True)
        timeout = 10
        t0 = time.time()
        locked = False
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

usrp.set_rx_rate(args.rate, 0)
usrp.set_rx_freq(uhd.types.TuneRequest(args.freq), 0)
usrp.set_rx_gain(args.gain, 0)
usrp.set_rx_bandwidth(args.rate, 0)
time.sleep(0.5)

print(f"\nActual: rate={usrp.get_rx_rate(0)/1e6:.3f} MSps, "
      f"freq={usrp.get_rx_freq(0)/1e9:.6f} GHz, "
      f"gain={usrp.get_rx_gain(0):.1f} dB")

try:
    ref_locked = usrp.get_mboard_sensor("ref_locked", 0).to_bool()
    print(f"Ref locked: {ref_locked}")
except RuntimeError:
    pass

# ─── Create RX streamer ────────────────────────────────────────────
st_args = uhd.usrp.StreamArgs("fc32", "sc16")
st_args.channels = [0]
rx_streamer = usrp.get_rx_stream(st_args)
max_samps = rx_streamer.get_max_num_samps()
metadata = uhd.types.RXMetadata()

# ─── Pre-allocate buffer (only for the capture portion) ────────────
samples = np.zeros(nsamps_capture, dtype=np.complex64)

# ─── Start stream (request settle + capture samples total) ─────────
stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.num_done)
stream_cmd.num_samps = nsamps_total
stream_cmd.stream_now = True
rx_streamer.issue_stream_cmd(stream_cmd)

# ─── Phase 1: SETTLING — receive and discard ───────────────────────
num_flushed, overflows_settle = 0, 0
print(f"\nSettling ({args.settle}s)...", end="", flush=True)
t0 = time.time()
while num_flushed < nsamps_settle:
    n_want = min(max_samps, nsamps_settle - num_flushed)
    buf = np.zeros((1, n_want), dtype=np.complex64)
    n = rx_streamer.recv(buf, metadata)
    if metadata.error_code == uhd.types.RXMetadataErrorCode.none:
        num_flushed += n
    elif metadata.error_code == uhd.types.RXMetadataErrorCode.overflow:
        num_flushed += n; overflows_settle += 1
    elif metadata.error_code == uhd.types.RXMetadataErrorCode.timeout:
        print(" TIMEOUT during settle"); break
    else:
        print(f" Error during settle: {metadata.strerror()}"); break
dt_settle = time.time() - t0
print(f" done ({num_flushed} samples flushed in {dt_settle:.3f}s, "
      f"{overflows_settle} overflows)")

# Check settling power + clipping
# (grab the last buffer from settling for a quick peek)
settle_peak = np.max(np.abs(buf[0,:n]))
settle_pwr  = 10 * np.log10(np.mean(np.abs(buf[0,:n])**2) + 1e-20)
print(f"  Settle peek — peak |sample|: {settle_peak:.4f}, "
      f"mean power: {settle_pwr:.1f} dB")
if settle_peak > 0.95:
    print(f"  ⚠ CLIPPING LIKELY (peak={settle_peak:.3f}) — reduce --gain by 3-6 dB")

# ─── Phase 2: CAPTURE — receive and save ───────────────────────────
num_rx, overflows = 0, 0
print(f"Capturing ({args.duration}s)...", end="", flush=True)
t0 = time.time()
while num_rx < nsamps_capture:
    n_want = min(max_samps, nsamps_capture - num_rx)
    buf = np.zeros((1, n_want), dtype=np.complex64)
    n = rx_streamer.recv(buf, metadata)
    if metadata.error_code == uhd.types.RXMetadataErrorCode.none:
        samples[num_rx:num_rx+n] = buf[0,:n]; num_rx += n
    elif metadata.error_code == uhd.types.RXMetadataErrorCode.overflow:
        samples[num_rx:num_rx+n] = buf[0,:n]; num_rx += n; overflows += 1
    elif metadata.error_code == uhd.types.RXMetadataErrorCode.timeout:
        print(" TIMEOUT"); break
    else:
        print(f" Error: {metadata.strerror()}"); break
dt = time.time() - t0
samples = samples[:num_rx]
print(f" done")

# ─── Stats ──────────────────────────────────────────────────────────
power_db = 10 * np.log10(np.mean(np.abs(samples)**2) + 1e-20)
peak_val = np.max(np.abs(samples))
print(f"\nCaptured {num_rx} samples in {dt:.3f}s ({num_rx/dt/1e6:.1f} MSps)")
print(f"Overflows: {overflows} (settle: {overflows_settle})")
print(f"Mean power: {power_db:.1f} dB, Peak |sample|: {peak_val:.4f}")
if peak_val > 0.95:
    print(f"⚠ ADC clipping detected (peak={peak_val:.3f})! Lower --gain by 3-6 dB.")
    print(f"  Current gain: {args.gain:.1f} dB → try --gain {max(0, args.gain-6):.1f}")
if overflows > 0:
    print(f"WARNING: {overflows} overflows during capture — data may have gaps")

# ─── Save ───────────────────────────────────────────────────────────
np.savez(
    args.out,
    samples=samples,
    rate=args.rate,
    freq=args.freq,
    gain=args.gain,
    num_overflows=overflows,
    settle_time=args.settle,
    ref_source=args.ref,
    timestamp=time.strftime("%Y%m%d_%H%M%S"),
)
size_mb = samples.nbytes / 1e6
print(f"\nSaved to {args.out} ({size_mb:.1f} MB)")
