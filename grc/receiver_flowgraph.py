#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# SPDX-License-Identifier: GPL-3.0
#
# GNU Radio Python Flow Graph
# Title: Receiver (headless, SigMF capture)
# GNU Radio version: 3.10.12.0

import datetime
import json
import signal
import sys

from gnuradio import gr
from gnuradio import blocks
from gnuradio import uhd


SIGMF_DATA_FILE = '/root/capture.sigmf-data'
SIGMF_META_FILE = '/root/capture.sigmf-meta'


class receiver_flowgraph(gr.top_block):

    def __init__(self):
        gr.top_block.__init__(self, "Receiver")

        ##################################################
        # Variables
        ##################################################
        self.samp_rate = samp_rate = 10e6
        self.rx_gain = rx_gain = 10
        self.center_freq = center_freq = 900e6

        ##################################################
        # Blocks
        ##################################################
        self.uhd_usrp_source_0 = uhd.usrp_source(
            ",".join(('addr=192.168.10.2', '')),
            uhd.stream_args(
                cpu_format="fc32",
                args='',
                channels=list(range(0, 1)),
            ),
        )
        self.uhd_usrp_source_0.set_samp_rate(samp_rate)
        self.uhd_usrp_source_0.set_center_freq(center_freq, 0)
        self.uhd_usrp_source_0.set_antenna('RX2', 0)
        self.uhd_usrp_source_0.set_gain(rx_gain, 0)

        self.blocks_file_sink_0 = blocks.file_sink(gr.sizeof_gr_complex, SIGMF_DATA_FILE, False)
        self.blocks_file_sink_0.set_unbuffered(False)

        ##################################################
        # Connections
        ##################################################
        self.connect((self.uhd_usrp_source_0, 0), (self.blocks_file_sink_0, 0))


def write_sigmf_meta(tb):
    # gr_complex (fc32) IQ samples correspond to SigMF's cf32_le datatype
    now = datetime.datetime.utcnow()
    meta = {
        "global": {
            "core:datatype": "cf32_le",
            "core:sample_rate": int(tb.samp_rate),
            "core:version": "1.0.0",
            "core:recorder": "receiver_flowgraph.py",
            "core:description": "USRP2 capture, ORBIT sb7 node1-2"
        },
        "captures": [
            {
                "core:sample_start": 0,
                "core:frequency": int(tb.center_freq),
                "core:datetime": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
            }
        ],
        "annotations": []
    }
    with open(SIGMF_META_FILE, 'w') as f:
        json.dump(meta, f, indent=2)
    print(f"Wrote {SIGMF_META_FILE}")


def main():
    tb = receiver_flowgraph()

    def sig_handler(sig=None, frame=None):
        tb.stop()
        tb.wait()
        write_sigmf_meta(tb)
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    tb.start()
    print(f"Receiving at {tb.center_freq/1e6:.1f} MHz, {tb.samp_rate/1e6:.1f} Msps -> {SIGMF_DATA_FILE}")
    print("Press Ctrl+C to stop and write SigMF metadata.")
    tb.wait()


if __name__ == '__main__':
    main()
