"""Satellite1 SPI exchanges for XMOS control protocols 0x10 and 0x11."""

from __future__ import annotations

import threading
import time


class XmosControl:
    """Own complete request/response exchanges on one SPI connection."""

    _READ_BIT = 0x80
    _PAYLOAD_AVAILABLE = 0x17
    _IGNORED = 7
    _ATTEMPTS = 5

    def __init__(self, bus: int = 0, device: int = 0, speed_hz: int = 1_000_000) -> None:
        import spidev

        self._spi = spidev.SpiDev()
        self._spi.open(bus, device)
        self._spi.max_speed_hz = speed_hz
        self._spi.mode = 3
        self._spi.bits_per_word = 8
        self._lock = threading.Lock()
        self._spi.xfer2(bytearray(1))

    def close(self) -> None:
        self._spi.close()

    def _transfer_when_ready(self, packet: bytearray, operation: str) -> list[int]:
        for attempt in range(self._ATTEMPTS):
            response = self._spi.xfer2(packet)
            if len(response) != len(packet):
                raise RuntimeError(f"SAT1 XMOS returned a short {operation} response")
            if response[0] != self._IGNORED:
                return response
            if attempt + 1 < self._ATTEMPTS:
                time.sleep(0.1)
        raise RuntimeError(f"SAT1 XMOS remained busy during {operation}")

    def exchange(self, resource: int, command: int, payload: bytes = b"", *, read_length: int = 0) -> bytes:
        read = bool(command & self._READ_BIT)
        if not 0 <= resource <= 255 or not 0 <= command <= 255:
            raise ValueError("XMOS resource and command must fit in one byte")
        if read_length < 0 or (read and (payload or read_length > 251)):
            raise ValueError("invalid XMOS read length or payload")
        if not read and (read_length or len(payload) > 253):
            raise ValueError("invalid XMOS write length")
        wire_length = read_length + 1 if read else len(payload)
        packet = bytearray(max(8, wire_length + 3))
        packet[:3] = bytes((resource, command, wire_length))
        if not read:
            packet[3 : 3 + len(payload)] = payload
        with self._lock:
            response = self._transfer_when_ready(packet, "command")
            if resource == 0 and command == 0 and not payload:
                if response[:2] != [1, 0]:
                    raise RuntimeError("SAT1 XMOS returned an unexpected status register")
                return bytes(response[2:6])
            time.sleep(0.001)
            # A NOP clocks the pending response, including write acknowledgements.
            response_length = (read_length if read else len(payload)) + 2
            response = self._transfer_when_ready(bytearray(max(8, response_length)), "payload")
            if not read:
                if response[:2] != [1, 0]:
                    raise RuntimeError("SAT1 XMOS rejected the write command")
                return b""
            status_offset = 1 if response[0] == self._PAYLOAD_AVAILABLE else 0
            if response[status_offset] != 0:
                raise RuntimeError("SAT1 XMOS rejected the read command")
            return bytes(response[status_offset + 1 : status_offset + 1 + read_length])

    def read_input_a(self) -> int:
        return self.exchange(0, 0)[1]

    def read_firmware_version(self) -> str:
        major, minor, patch, prerelease, counter = self.exchange(240, 88 | self._READ_BIT, read_length=5)
        if not any((major, minor, patch)) or prerelease > 4:
            raise RuntimeError("SAT1 XMOS returned an invalid firmware version")
        suffix = ("", "alpha", "beta", "rc", "dev")[prerelease]
        return f"v{major}.{minor}.{patch}" + (f"-{suffix}.{counter}" if suffix else "")


def main() -> None:
    control = XmosControl()
    try:
        print(control.read_firmware_version())
    finally:
        control.close()


if __name__ == "__main__":
    main()
