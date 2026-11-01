"""The packet checksum (C=): good lines pass, a flipped character is rejected, old firmware without C= still parses."""
import unittest

from hardware.host.health_reader import parse_line

BODY = "R1=4296E0,R2=427F70,R3=428B28,R4=428358,T=A07,I=54E,A=99C,B=550,F=F,S=0,H=0,V=896F"


def with_checksum(body):
    c = 0
    for b in body.encode("ascii"):
        c ^= b
    return "%s,C=%02X" % (body, c)


class PacketChecksum(unittest.TestCase):
    def test_good_checksum_parses(self):
        self.assertIsNotNone(parse_line(with_checksum(BODY)))

    def test_flipped_character_is_rejected(self):
        good = with_checksum(BODY)
        bad = good.replace("R2=427F70", "R2=427F71")
        self.assertIsNone(parse_line(bad))

    def test_wrong_checksum_is_rejected(self):
        self.assertIsNone(parse_line(BODY + ",C=00"))

    def test_old_firmware_without_checksum_still_parses(self):
        self.assertIsNotNone(parse_line(BODY))

    def test_values_unchanged_by_checksum(self):
        self.assertEqual(parse_line(with_checksum(BODY)), parse_line(BODY))


if __name__ == "__main__":
    unittest.main()
