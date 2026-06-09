import numpy as np
import matplotlib.pyplot as plt

FILE = '/Users/tylerthomassen/Downloads/iq_capture_20260609_145413.dat'
SAMPLE_RATE = 1e6
CENTER_FREQ = 900e6

# Read interleaved float32 I/Q samples
raw = np.fromfile(FILE, dtype=np.float32)
samples = raw[0::2] + 1j * raw[1::2]

# --- Plot 1: Waveform (first 1000 samples) ---
fig, axes = plt.subplots(2, 1, figsize=(12, 8))

t = np.arange(1000) / SAMPLE_RATE * 1e6  # microseconds
axes[0].plot(t, samples[:1000].real, label='I')
axes[0].plot(t, samples[:1000].imag, label='Q')
axes[0].set_xlabel('Time (us)')
axes[0].set_ylabel('Amplitude')
axes[0].set_title('IQ Waveform (first 1000 samples)')
axes[0].legend()
axes[0].grid(True)

# --- Plot 2: Power Spectrum ---
axes[1].psd(samples, NFFT=1024, Fs=SAMPLE_RATE/1e6, Fc=CENTER_FREQ/1e6)
axes[1].set_xlabel('Frequency (MHz)')
axes[1].set_title('Power Spectral Density')
axes[1].grid(True)

fig.suptitle(
    "ORBIT Testbed — sb7 IQ Capture\n"
    "TX: node1-1 @ 900 MHz, 10 dBgain, cosine 1 MHz baseband  |  "
    "RX: node1-2 @ 900 MHz, 1 Msps, 10 dB gain  |  Duration: 10s",
    fontsize=10, y=1.01
)

plt.tight_layout()
plt.savefig('/Users/tylerthomassen/Downloads/iq_plot.png', dpi=150, bbox_inches='tight')
plt.show()
print("Plot saved to ~/Downloads/iq_plot.png")
