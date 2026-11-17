"""Bounded little-endian memory, with explicit alignment checks."""


class MemoryAccessError(ValueError):
    """An access lies outside this region or violates its alignment."""


class Memory:
    def __init__(self, size: int, base: int = 0) -> None:
        if size <= 0 or base < 0 or base + size > 1 << 32:
            raise ValueError("Memory must fit in the 32-bit address space")
        self.base = base
        self._data = bytearray(size)

    def _offset(self, address: int, width: int, alignment: int = 1) -> int:
        offset = address - self.base
        if offset < 0 or offset + width > len(self._data):
            raise MemoryAccessError(f"Out-of-bounds access at {address:#x}")
        if address % alignment:
            raise MemoryAccessError(
                f"Unaligned {alignment}-byte access at {address:#x}"
            )
        return offset

    def load(self, address: int, data: bytes) -> None:
        offset = self._offset(address, len(data))
        self._data[offset : offset + len(data)] = data

    def read8(self, address: int) -> int:
        return self._data[self._offset(address, 1)]

    def read16(self, address: int) -> int:
        offset = self._offset(address, 2, 2)
        return int.from_bytes(self._data[offset : offset + 2], "little")

    def read32(self, address: int) -> int:
        offset = self._offset(address, 4, 4)
        return int.from_bytes(self._data[offset : offset + 4], "little")

    def write8(self, address: int, value: int) -> None:
        self._data[self._offset(address, 1)] = value & 0xFF

    def write16(self, address: int, value: int) -> None:
        self._offset(address, 2, 2)
        self.load(address, (value & 0xFFFF).to_bytes(2, "little"))

    def write32(self, address: int, value: int) -> None:
        self._offset(address, 4, 4)
        self.load(address, (value & 0xFFFFFFFF).to_bytes(4, "little"))
