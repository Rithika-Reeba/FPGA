import os
os.environ["FPGA_CALIBRATION"] = "none"   # tests use the placeholder nominal, never a board calibration
"""
Several dashboard sessions share one receiver. If they connect at the same moment, exactly ONE serial handle
may be opened, and the receiver must keep knowing about it (no leaked handle the dashboard has forgotten).
"""

import threading
import unittest
from unittest import mock

from communication.uart_receiver import FPGAUARTReceiver


class _FakePort:
    opened = []
    lock = threading.Lock()

    def __init__(self, **kwargs):
        with _FakePort.lock:
            if any(p.is_open for p in _FakePort.opened):          # a real port can only be open once
                import serial
                raise serial.SerialException("could not open port: PermissionError(13, 'Access is denied.')")
            self.is_open = True
            _FakePort.opened.append(self)

    def close(self):
        self.is_open = False


class TestConcurrentConnect(unittest.TestCase):
    def test_simultaneous_connects_leave_one_known_open_handle(self):
        _FakePort.opened = []
        rcv = FPGAUARTReceiver(port="COM99")
        with mock.patch("communication.uart_receiver.serial.Serial", _FakePort):
            threads = [threading.Thread(target=rcv.connect) for _ in range(12)]
            [t.start() for t in threads]
            [t.join() for t in threads]
        open_handles = [p for p in _FakePort.opened if p.is_open]
        self.assertEqual(len(open_handles), 1)
        self.assertTrue(rcv.is_port_open)
        self.assertIs(rcv.serial_conn, open_handles[0])          # the receiver still owns it

    def test_disconnect_closes_the_handle(self):
        _FakePort.opened = []
        rcv = FPGAUARTReceiver(port="COM99")
        with mock.patch("communication.uart_receiver.serial.Serial", _FakePort):
            rcv.connect()
            rcv.disconnect()
        self.assertFalse(any(p.is_open for p in _FakePort.opened))
        self.assertFalse(rcv.is_port_open)


if __name__ == "__main__":
    unittest.main()