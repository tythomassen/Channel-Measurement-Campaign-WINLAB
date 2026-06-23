# OFDM OTA Experiment — sb7 (USRP2) Runbook

## Basic walkthrough (high level, do these in order)
1. Reserve sb7 and image both nodes (`node1-1`, `node1-2`) with the same `.ndz` image.
2. Power on both nodes, SSH in, run `uhd_find_devices` on each — confirm both see
   their USRP2 before doing anything else. If not, see Step 0 below.
3. On your Mac: generate the TX waveform file (`ofdm_frame_gen.py`).
4. On your Mac: `scp` the TX/RX scripts + waveform onto **both** nodes.
5. On node1-1: run the TX script.
6. On node1-2: run the RX script (while TX is still running) to capture a file.
7. (Optional) View the live signal on node1-2 with the ASCII spectrum tool.
8. **Stop the manual TX** on node1-1 (Ctrl+C, or `pkill -SIGINT -f tx_ofdm_ota.py`)
   before moving on — the sweep script starts/stops its own TX process per gain
   step, and a leftover manual TX session will conflict with it (port/USRP
   already in use).
9. Run the full automated sweep from your Mac (`run_sweep_master.py`) — it
   repeats steps 5+6 across multiple gain values automatically and pulls the
   results back to your Mac.

### What each file does
| File | Runs where | What it does |
|---|---|---|
| `ofdm_frame_gen.py` | Mac | Builds the OFDM signal (preamble, pilots, QPSK data) and saves it to `tx_waveform.npz`. Run once, or whenever rate/freq changes. |
| `tx_ofdm_ota.py` | node1-1 (TX) | Loads `tx_waveform.npz` and streams it out the USRP2 in a loop until killed. |
| `rx_capture_ota.py` | node1-2 (RX) | Records raw IQ samples off the air for a fixed duration and saves them to a `.npz` file. |
| `run_sweep_master.py` | **Mac only** | Orchestrator — pushes files to both nodes via SCP, then for each gain value: SSHes into node1-1 to start TX, SSHes into node1-2 to run an RX capture, SSHes back into node1-1 to kill TX, then SCPs the resulting capture file back to your Mac. Repeats for every gain in the list. |

### Do you need anything running before starting the sweep?
**No.** `run_sweep_master.py` is fully self-contained — it starts and stops TX
itself via SSH for every gain step, and triggers RX itself the same way. You
should **not** have a manual `tx_ofdm_ota.py` or `rx_capture_ota.py` session
already running on either node when you launch it (that's what step 8 above is
for) — just run `python3 run_sweep_master.py` from your Mac and let it drive
everything.

---

## 0. One-time network fix (per node, only if `uhd_find_devices` finds nothing)
**Why this matters:** the USRP2 only talks to its node over a direct Ethernet
link on the `192.168.10.x` subnet. If that subnet is bound to the wrong network
interface (or duplicated across two interfaces), the node can't reach its own
radio and `uhd_find_devices` comes back empty — this isn't a software bug in the
experiment scripts, it's the node's network config.

Check `/etc/netplan/00-netplan.yaml` — the USRP2 subnet (`192.168.10.1/24`) must be
on `enp4s0`, not `enp1s0`. If wrong:
```bash
sed -i 's/enp1s0:/enp4s0:/' /etc/netplan/00-netplan.yaml
ip addr flush dev enp1s0
netplan apply
ping -c2 192.168.10.2        # should get replies
uhd_find_devices              # should show type: usrp2
```

## 1. On your Mac — generate the waveform
**Why:** this builds the actual OFDM signal (preamble + pilots + QPSK data symbols)
that TX will transmit, and saves it as `tx_waveform.npz`. It must be regenerated
any time you change the sample rate or carrier frequency, since those are baked
into the file.
```bash
cd ~/Desktop/WINLAB/Ofdm
python3 ofdm_frame_gen.py     # defaults: 5e6 rate, 3.5e9 freq -> tx_waveform.npz
```

## 2. On your Mac — push files to both nodes
**Why:** SSH lets you *run* commands on a node, but the actual script/waveform
files have to already exist on that node's disk first. This copies the TX/RX
Python scripts and the waveform from your Mac, through the sb7 console (jump
host), onto both nodes' `/root/ota_ofdm/` directory. Both nodes need a copy —
node1-1 needs the scripts+waveform to transmit, node1-2 needs the RX script to
capture.
```bash
JUMP=tyler_thomassen@console.sb7.cosmos-lab.org

for NODE in node1-1 node1-2; do
  ssh -A -J $JUMP root@${NODE}.sb7.cosmos-lab.org "mkdir -p /root/ota_ofdm"
  scp -J $JUMP tx_ofdm_ota.py rx_capture_ota.py tx_waveform.npz \
      root@${NODE}.sb7.cosmos-lab.org:/root/ota_ofdm/
done
```

## 3. On node1-1 (TX)
**Why:** this SSHes into the transmit node and runs the script that loads
`tx_waveform.npz` and streams it out continuously through the USRP2 until you
stop it. `PYTHONPATH` has to be set every fresh shell — without it, `import uhd`
fails because the UHD Python bindings aren't on the default path on this image.
```bash
ssh -A -J tyler_thomassen@console.sb7.cosmos-lab.org root@node1-1.sb7.cosmos-lab.org
export PYTHONPATH=/usr/local/lib/python3.8/site-packages
cd /root/ota_ofdm
python3 tx_ofdm_ota.py --gain 20      # Ctrl+C to stop
```

## 4. On node1-2 (RX) — run in a separate terminal while TX is running
**Why:** this SSHes into the receive node and records raw IQ samples off the air
for a fixed duration into a `.npz` file. It only captures something meaningful if
TX (step 3) is actively running at the same time — run this in a second terminal,
not after stopping TX.
```bash
ssh -A -J tyler_thomassen@console.sb7.cosmos-lab.org root@node1-2.sb7.cosmos-lab.org
export PYTHONPATH=/usr/local/lib/python3.8/site-packages
cd /root/ota_ofdm
python3 rx_capture_ota.py --gain 20 --duration 2 --out test_capture.npz
```

## 5. On your Mac — full automated gain sweep (does steps 3+4 across multiple gains)
**Why:** doing steps 3+4 by hand for every gain value is slow and error-prone.
This script automates the whole loop — for each TX gain in the list, it starts
TX, waits, triggers an RX capture, stops TX, then `scp`s the resulting file back
to your Mac — repeating for every gain value with no manual SSHing required.
```bash
cd ~/Desktop/WINLAB/Ofdm
python3 run_sweep_master.py
```
Sweeps `GAINS = [0, 5, 10, 15, 20, 25, 30]`, deploys files itself, starts/stops TX
per step, captures on RX, and scp's each `rx_capture_cf3.5e9_gXX.npz` back to this
folder. Files land directly in `~/Desktop/WINLAB/Ofdm/` — delete them when done if
you don't need them locally (data still lives on the nodes in `/root/ota_ofdm/`).

## Key defaults (sb7 / USRP2, not the original X310 defaults)
- Rate: `5e6` (USRP2 over 1GbE can't sustain the original 50e6)
- Device args: `addr=192.168.10.2` (not `type=x300,resource=RIO0`)
- Ref: `internal` (sb7 nodes don't share a 10 MHz ref cable)
- RX gain stays fixed at 31.5 dB in the sweep — only TX gain varies. Watch for
  `⚠ ADC clipping detected` in RX output above ~15-20 dB TX gain; that data is
  distorted, not clean.

## Quick spectrum check (optional, visual sanity check while TX is running)
**Why:** before trusting the automated capture pipeline, it's worth visually
confirming the signal is actually on the air at the right frequency. This pulls
up a live ASCII spectrum display on the RX node so you can see the OFDM signal's
energy directly, instead of just trusting log output.
On node1-2:
```bash
cd /usr/lib/uhd/examples
./rx_ascii_art_dft --freq 3.5e9 --gain 20 --rate 5e6 --frame-rate 10 --ref-lvl -30 --dyn-rng 70
```
Look for a ~3.75 MHz wide block of energy centered at 3.5 GHz (not a single spike —
that's what OFDM looks like, unlike a single-tone test signal).
