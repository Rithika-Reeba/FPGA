import os
os.environ["FPGA_CALIBRATION"] = "none"   # tests use the placeholder nominal, never a board calibration
"""
If the board's USB link is lost while the dashboard has the port open (cable, connector, power dip), Windows
reports a ClearCommError on the next read. The receiver must close the dead port so that auto-connect can
open it again, instead of staying "open" and silent forever.
"""

import unittest
from unittest import mock

import serial

from communication.uart_receiver import ConnectionState, FPGAUARTReceiver


class _DeadPort:
    is_open = True

    @property
    def in_waiting(self):
        raise serial.SerialException("ClearCommError failed (PermissionError(13, 'Access is denied.', None, 5))")

    def close(self):
        self.is_open = False


class TestLostUsbLink(unittest.TestCase):
    def make_receiver(self):
        rcv = FPGAUARTReceiver(port="COM99")
        rcv.serial_conn = _DeadPort()
        rcv.state = ConnectionState.PORT_OPEN_WAITING
        return rcv

    def test_a_lost_link_closes_the_port(self):
        rcv = self.make_receiver()
        self.assertTrue(rcv.is_port_open)
        self.assertIsNone(rcv.read_packet())
        self.assertFalse(rcv.is_port_open)
        self.assertEqual(rcv.state, ConnectionState.DISCONNECTED)

    def test_the_message_says_what_happened(self):
        rcv = self.make_receiver()
        rcv.read_packet()
        self.assertIn("USB connection", rcv.last_error_msg)
        self.assertIn("COM99", rcv.last_error_msg)

    def test_a_closed_port_can_be_opened_again(self):
        rcv = self.make_receiver()
        rcv.read_packet()
        with mock.patch("communication.uart_receiver.serial.Serial") as ser:
            ser.return_value.is_open = True
            self.assertTrue(rcv.connect("COM99"))
        self.assertTrue(rcv.is_port_open)


if __name__ == "__main__":
    unittest.main()