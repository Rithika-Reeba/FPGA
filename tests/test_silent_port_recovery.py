import os
os.environ["FPGA_CALIBRATION"] = "none"   # tests use the placeholder nominal, never a board calibration
"""
A port that was opened while the board's USB link was re-enumerating can stay open but silent forever. The receiver
reopens such a port itself (limited times), and never reopens one that is already receiving.
"""

import time
import unittest
from unittest import mock

from communication.uart_receiver import ConnectionState, FPGAUARTReceiver

LINE = b"R1=4B6AFA,R2=45E072,R3=45E072,R4=490162,T=A01,I=556,A=998,B=556,F=F,S=0,H=0,V=AAAA\r\n"


class _Port:
    opened = 0

    def __init__(self, **kw):
        _Port.opened += 1
        self.is_open = True
        self.in_waiting = 0

    def close(self):
        self.is_open = False

    def readline(self):
        return LINE


def _connected():
    _Port.opened = 0
    rcv = FPGAUARTReceiver(port="COM99")
    with mock.patch("communication.uart_receiver.serial.Serial", _Port):
        rcv.connect()
    return rcv


class TestSilentPortRecovery(unittest.TestCase):
    def test_a_silent_port_is_reopened(self):
        rcv = _connected()
        rcv.connection_start_time = time.time() - rcv.REOPEN_AFTER_S - 1
        with mock.patch("communication.uart_receiver.serial.Serial", _Port):
            rcv.read_packet()
        self.assertEqual(_Port.opened, 2)                 # the first open + one reopen
        self.assertTrue(rcv.is_port_open)

    def test_reopening_is_limited(self):
        rcv = _connected()
        with mock.patch("communication.uart_receiver.serial.Serial", _Port):
            for _ in range(6):
                rcv.connection_start_time = time.time() - rcv.REOPEN_AFTER_S - 1
                rcv.read_packet()
        self.assertEqual(_Port.opened, 1 + rcv.MAX_SILENT_REOPENS)

    def test_a_port_that_is_receiving_is_never_reopened(self):
        rcv = _connected()
        rcv.packet_count = 5
        rcv.connection_start_time = time.time() - 100
        with mock.patch("communication.uart_receiver.serial.Serial", _Port):
            rcv.read_packet()
        self.assertEqual(_Port.opened, 1)

    def test_a_fresh_connect_resets_the_allowance(self):
        rcv = _connected()
        rcv._silent_reopens = rcv.MAX_SILENT_REOPENS
        rcv.disconnect()
        with mock.patch("communication.uart_receiver.serial.Serial", _Port):
            rcv.connect()
        self.assertEqual(rcv._silent_reopens, 0)


if __name__ == "__main__":
    unittest.main()