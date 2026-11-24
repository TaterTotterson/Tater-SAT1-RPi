from __future__ import annotations

import sys
import threading
import types
import unittest
from unittest.mock import patch

from tater_sat1_standalone.xmos_control import XmosControl


class FakeSpi:
    def __init__(self, responses: list[list[int]]) -> None:
        self.responses = list(responses)
        self.transfers: list[bytes] = []
        self.closed = False

    def open(self, bus: int, device: int) -> None:
        self.address = (bus, device)

    def close(self) -> None:
        self.closed = True

    def xfer2(self, packet: bytearray) -> list[int]:
        self.transfers.append(bytes(packet))
        if len(packet) == 1:
            return [0]
        response = self.responses.pop(0)
        return response + [0] * (len(packet) - len(response))


class XmosControlTests(unittest.TestCase):
    def control(self, responses: list[list[int]]) -> tuple[XmosControl, FakeSpi]:
        spi = FakeSpi(responses)
        with patch.dict(sys.modules, {"spidev": types.SimpleNamespace(SpiDev=lambda: spi)}):
            control = XmosControl()
        return control, spi

    def test_version_reader_accepts_old_and_new_framing(self) -> None:
        for response, expected in [([0, 1, 1, 1, 0, 0], "v1.1.1"),
                                   ([0x17, 0, 1, 2, 0, 4, 1], "v1.2.0-dev.1")]:
            with self.subTest(expected=expected), patch("tater_sat1_standalone.xmos_control.time.sleep"):
                control, spi = self.control([[1, 0], response])
                self.assertEqual(control.read_firmware_version(), expected)
                self.assertEqual(spi.transfers[1][:3], bytes((240, 0xD8, 6)))
                self.assertEqual(spi.transfers[2], bytes(8))
                control.close()
                self.assertTrue(spi.closed)

    def test_led_ack_gpio_and_direction_reads_do_not_leak_pending_responses(self) -> None:
        payload = list(range(32))
        control, spi = self.control([[1, 0], [1, 0], [1, 0, 0, 7, 0, 0],
                                     [1, 0], [0x17, 0, *payload]])
        with patch("tater_sat1_standalone.xmos_control.time.sleep"):
            self.assertEqual(control.exchange(200, 0, bytes((2, 1, 3))), b"")
            self.assertEqual(control.read_input_a(), 7)
            self.assertEqual(control.exchange(233, 0x80, read_length=32), bytes(payload))
        self.assertEqual(spi.transfers[1][:6], bytes((200, 0, 3, 2, 1, 3)))
        self.assertEqual(spi.transfers[2], bytes(8))
        self.assertEqual(spi.transfers[-1], bytes(34))
        self.assertEqual(spi.responses, [])

    def test_busy_request_and_response_are_retried_before_returning_data(self) -> None:
        control, spi = self.control([[7], [1, 0], [7], [0x17, 0, 41]])
        with patch("tater_sat1_standalone.xmos_control.time.sleep"):
            self.assertEqual(control.exchange(233, 0x80, read_length=1), b")")
        self.assertEqual(spi.transfers[1], spi.transfers[2])
        self.assertEqual(spi.transfers[3], spi.transfers[4])

    def test_busy_retries_are_bounded_in_both_phases(self) -> None:
        for responses in ([[7]] * 5, [[1, 0]] + [[7]] * 5):
            with self.subTest(responses=responses), patch("tater_sat1_standalone.xmos_control.time.sleep"):
                control, spi = self.control(responses)
                with self.assertRaisesRegex(RuntimeError, "remained busy"):
                    control.exchange(233, 0x80, read_length=1)
                self.assertEqual(spi.responses, [])

    def test_handler_errors_and_unexpected_write_ack_are_rejected(self) -> None:
        for response in ([5], [0x17, 5]):
            with self.subTest(response=response), patch("tater_sat1_standalone.xmos_control.time.sleep"):
                control, _spi = self.control([[1, 0], response])
                with self.assertRaisesRegex(RuntimeError, "rejected the read"):
                    control.exchange(233, 0x80, read_length=1)
        control, _spi = self.control([[1, 0], [1, 3]])
        with patch("tater_sat1_standalone.xmos_control.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "rejected the write"):
                control.exchange(200, 0, b"\0\0\0")

    def test_short_spi_response_and_stale_payload_cannot_be_gpio_status(self) -> None:
        control, spi = self.control([])
        spi.xfer2 = lambda _packet: [1, 0]
        with self.assertRaisesRegex(RuntimeError, "short"):
            control.read_input_a()
        control, _spi = self.control([[0x17, 0, 7]])
        with self.assertRaisesRegex(RuntimeError, "unexpected status"):
            control.read_input_a()

    def test_invalid_request_lengths_are_rejected_before_spi(self) -> None:
        control, spi = self.control([])
        for resource, command, payload, read_length in [
            (256, 0, b"", 0), (1, 256, b"", 0), (1, 0x80, b"", 252),
            (1, 0x80, b"data", 1), (1, 0, bytes(254), 0), (1, 0, b"", 1),
        ]:
            with self.subTest(command=command, read_length=read_length):
                with self.assertRaises(ValueError):
                    control.exchange(resource, command, payload, read_length=read_length)
        self.assertEqual(len(spi.transfers), 1)

    def test_concurrent_commands_keep_request_and_response_together(self) -> None:
        control, spi = self.control([[1, 0], [0x17, 0, 11], [1, 0], [0x17, 0, 22]])
        start = threading.Barrier(3)
        replies = []

        def read(resource: int) -> None:
            start.wait()
            replies.append(control.exchange(resource, 0x80, read_length=1))

        workers = [threading.Thread(target=read, args=(resource,)) for resource in (232, 233)]
        for worker in workers:
            worker.start()
        start.wait()
        for worker in workers:
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
        self.assertCountEqual(replies, [b"\x0b", b"\x16"])
        self.assertEqual([packet[:3] for packet in spi.transfers[1:]][1::2], [bytes(3), bytes(3)])


if __name__ == "__main__":
    unittest.main()
