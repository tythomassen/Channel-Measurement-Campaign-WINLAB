#!/usr/bin/env python3
"""
ofdm_frame_gen_v2.py — Generate OFDM TX waveform for SB2 coax experiments.

Frame structure (16 symbols x 320 = 5120 samples):
  [SC2][P0][D0][D1]...[D11][P1][Guard]
   0    1   2   3       13  14    15

- Preamble (sym 0): BPSK preamble on all 192 occupied SCs, for xcorr frame sync
- P0  (sym 1): BPSK pilot on all 192 SCs, channel estimation + CFO ref
- D0-D11 (sym 2-13): QPSK data on all 192 SCs, uncoded
- P1  (sym 14): BPSK pilot on all 192 SCs, CFO tracking
- Guard (sym 15): 320 zero samples

Usage:
  python3 ofdm_frame_gen.py
  python3 ofdm_frame_gen.py --n-frames 1000 --out tx_waveform.npz
"""

import argparse
import numpy as np

parser = argparse.ArgumentParser(description="OFDM frame generator")
parser.add_argument("--fft", type=int, default=256)
parser.add_argument("--cp", type=int, default=64)
parser.add_argument("--rate", type=float, default=50e6)
parser.add_argument("--freq", type=float, default=3.5e9)
parser.add_argument("--n-frames", type=int, default=500)
parser.add_argument("--seed", type=int, default=42)
parser.add_argument("--tx-scale", type=float, default=0.9)
parser.add_argument("--out", type=str, default="tx_waveform.npz")
args = parser.parse_args()

FFT = args.fft
CP = args.cp
SYM = FFT + CP  # 320
RATE = args.rate
SEED = args.seed

rng = np.random.default_rng(SEED)

# --- Subcarrier allocation ---
# 192 occupied SCs: indices -96..-1, 1..96 (DC null)
occupied_pos = np.array(list(range(-96, 0)) + list(range(1, 97)))  # (192,)
N_OCC = len(occupied_pos)

def sc_to_bin(sc):
    return sc % FFT

occ_bins = np.array([sc_to_bin(sc) for sc in occupied_pos])


def ofdm_symbol(freq_data):
    """IFFT + prepend CP -> 320 samples."""
    td = np.fft.ifft(freq_data, n=FFT)
    return np.concatenate([td[-CP:], td]).astype(np.complex64)


# --- QPSK map ---
QPSK_MAP = np.array([1+1j, -1+1j, 1-1j, -1-1j], dtype=np.complex64) / np.sqrt(2)

# --- SC2 preamble (sym 0) ---
sc2_pn = rng.choice([-1, 1], size=N_OCC)
sc2_freq = np.zeros(FFT, dtype=np.complex64)
sc2_freq[occ_bins] = sc2_pn
sc2_td = ofdm_symbol(sc2_freq)

# --- P0 pilot (sym 1) ---
p0_pn = rng.choice([-1, 1], size=N_OCC)
p0_freq = np.zeros(FFT, dtype=np.complex64)
p0_freq[occ_bins] = p0_pn
p0_td = ofdm_symbol(p0_freq)

# --- Data symbols D0-D11 (sym 2-13) ---
N_DATA_SYM = 12
data_bits = rng.integers(0, 2, size=(N_DATA_SYM, N_OCC * 2)).astype(np.int8)  # 192 SCs * 2 bits
data_freq = np.zeros((N_DATA_SYM, FFT), dtype=np.complex64)
data_td_list = []

for d in range(N_DATA_SYM):
    idx = data_bits[d, 0::2] * 2 + data_bits[d, 1::2]  # 192 QPSK indices
    qpsk = QPSK_MAP[idx]
    freq = np.zeros(FFT, dtype=np.complex64)
    freq[occ_bins] = qpsk
    data_freq[d] = freq
    data_td_list.append(ofdm_symbol(freq))

# --- P1 pilot (sym 14) ---
p1_pn = rng.choice([-1, 1], size=N_OCC)
p1_freq = np.zeros(FFT, dtype=np.complex64)
p1_freq[occ_bins] = p1_pn
p1_td = ofdm_symbol(p1_freq)

# --- Guard (sym 15) ---
guard = np.zeros(SYM, dtype=np.complex64)

# --- Assemble frame ---
frame = np.concatenate([sc2_td, p0_td] + data_td_list + [p1_td, guard])
FRAME_LEN = 16 * SYM
assert len(frame) == FRAME_LEN, f"Frame length {len(frame)} != {FRAME_LEN}"

# --- Tile and scale ---
waveform = np.tile(frame, args.n_frames)
peak = np.max(np.abs(waveform))
waveform = (waveform * (args.tx_scale / peak)).astype(np.complex64)

papr = 10 * np.log10(np.max(np.abs(waveform)**2) / np.mean(np.abs(waveform)**2))
bits_per_frame = N_DATA_SYM * N_OCC * 2

print(f"Frame: {FRAME_LEN} samples ({FRAME_LEN / RATE * 1e3:.3f} ms)")
print(f"  Preamble(0) + P0(1) + D0-D11(2-13) + P1(14) + Guard(15)")
print(f"  {N_OCC} occupied SCs, QPSK uncoded, {bits_per_frame} bits/frame")
print(f"Waveform: {len(waveform)} samples, {args.n_frames} frames")
print(f"  TX scale: {args.tx_scale}, PAPR: {papr:.1f} dB")

# --- Save ---
np.savez_compressed(
    args.out,
    tx_waveform=waveform,
    tx_frame=frame.astype(np.complex64),
    sc2_freq=sc2_freq,
    p0_freq=p0_freq,
    p1_freq=p1_freq,
    data_freq=data_freq,
    data_bits=data_bits,
    occupied_pos=occupied_pos,
    fft=FFT,
    cp=CP,
    rate=RATE,
    freq=args.freq,
    seed=SEED,
    frame_len=FRAME_LEN,
    tx_scale=args.tx_scale,
    n_data_sym=N_DATA_SYM,
)

print(f"Saved to {args.out}")
print(f"  Keys: {list(np.load(args.out).keys())}")
