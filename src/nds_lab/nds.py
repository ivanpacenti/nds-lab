"""Direct-load DS experiments with two CPUs and a deliberately small RAM map."""

import struct
from dataclasses import dataclass

from nds_lab.cpu import CPU, StepResult
from nds_lab.memory import Memory, MemoryAccessError


class ROMError(ValueError):
    """A cartridge cannot be loaded by this direct-load laboratory."""


class AddressSpace:
    """Route accesses to explicitly mapped RAM regions; reject unmapped hardware."""

    def __init__(self, regions: tuple[Memory, ...]) -> None:
        self.regions = regions

    def _region(self, address: int, width: int, alignment: int = 1) -> Memory:
        for region in self.regions:
            if region.base <= address < region.base + region.size:
                region.validate(address, width, alignment)
                return region
        raise MemoryAccessError(f"Unmapped address {address:#010x}")

    def validate(self, address: int, width: int, alignment: int = 1) -> None:
        self._region(address, width, alignment)

    def load(self, address: int, data: bytes) -> None:
        self._region(address, len(data)).load(address, data)

    def read8(self, address: int) -> int:
        return self._region(address, 1).read8(address)

    def read16(self, address: int) -> int:
        return self._region(address, 2, 2).read16(address)

    def read32(self, address: int) -> int:
        return self._region(address, 4, 4).read32(address)

    def write8(self, address: int, value: int) -> None:
        self._region(address, 1).write8(address, value)

    def write16(self, address: int, value: int) -> None:
        self._region(address, 2, 2).write16(address, value)

    def write32(self, address: int, value: int) -> None:
        self._region(address, 4, 4).write32(address, value)


@dataclass(frozen=True)
class Segment:
    rom_offset: int
    entry: int
    address: int
    size: int

    @property
    def thumb(self) -> bool:
        return bool(self.entry & 1)

    @property
    def entry_address(self) -> int:
        return self.entry & ~1

    @classmethod
    def parse(cls, rom: bytes, offset: int) -> "Segment":
        segment = cls(*struct.unpack_from("<4I", rom, offset))
        if segment.size == 0 or segment.rom_offset < 0x200:
            raise ROMError("Each CPU needs a nonempty binary after the header")
        if segment.rom_offset + segment.size > len(rom):
            raise ROMError("CPU binary extends beyond the cartridge image")
        if segment.address + segment.size > 1 << 32:
            raise ROMError("CPU binary wraps the address space")
        if segment.entry_address % (2 if segment.thumb else 4):
            raise ROMError("Misaligned CPU entry point")
        if (
            not segment.address
            <= segment.entry_address
            < segment.address + segment.size
        ):
            raise ROMError("Direct-load entry point must lie inside its CPU binary")
        width = 2 if segment.thumb else 4
        if segment.entry_address + width > segment.address + segment.size:
            raise ROMError("Entry instruction extends beyond its CPU binary")
        return segment


class NDS:
    """Two independent register sets sharing main RAM, with bounded manual stepping."""

    def __init__(self, rom: bytes) -> None:
        if len(rom) < 0x200:
            raise ROMError("DS header must contain at least 512 bytes")
        if rom[0x12] != 0:
            raise ROMError("Only original DS images are supported by this loader")
        arm9_segment = Segment.parse(rom, 0x20)
        arm7_segment = Segment.parse(rom, 0x30)
        self.title = rom[:12].split(b"\0", 1)[0].decode("ascii", errors="replace")
        self.main_ram = Memory(4 * 1024 * 1024, 0x02000000)
        # Fixed WRAMCNT=3-like allocation: all shared WRAM belongs to ARM7.
        self.shared_wram = Memory(32 * 1024, 0x03000000)
        self.arm7_wram = Memory(64 * 1024, 0x03800000)
        arm9_memory = AddressSpace((self.main_ram,))
        arm7_memory = AddressSpace((self.main_ram, self.shared_wram, self.arm7_wram))
        pairs = ((arm9_segment, arm9_memory), (arm7_segment, arm7_memory))
        try:
            for segment, memory in pairs:
                memory.validate(segment.address, segment.size)
        except MemoryAccessError as error:
            raise ROMError(f"CPU binary targets unsupported memory: {error}") from error
        if max(arm9_segment.address, arm7_segment.address) < min(
            arm9_segment.address + arm9_segment.size,
            arm7_segment.address + arm7_segment.size,
        ):
            raise ROMError("CPU binaries overlap in RAM")
        for segment, memory in pairs:
            memory.load(
                segment.address,
                rom[segment.rom_offset : segment.rom_offset + segment.size],
            )
        self.arm9 = CPU(
            arm9_memory,
            arm9_segment.entry_address,
            thumb=arm9_segment.thumb,
            architecture="armv5te",
        )
        self.arm7 = CPU(
            arm7_memory,
            arm7_segment.entry_address,
            thumb=arm7_segment.thumb,
            architecture="armv4t",
        )

    def step(self, processor: str) -> StepResult:
        if processor == "arm9":
            return self.arm9.step()
        if processor == "arm7":
            return self.arm7.step()
        raise ValueError("Processor must be arm9 or arm7")


def make_demo_rom() -> bytes:
    """Build an original synthetic .nds container for this direct-load runner.

    This fixture omits the logo, checksums, and boot firmware setup needed for
    hardware boot. Its sections use the standard DS header layout.
    """
    arm9_words = (
        0xE3A00007,  # MOV r0, #7
        0xE59F1004,  # LDR r1, [pc, #4] -> literal at +16
        0xE5810000,  # STR r0, [r1]
        0xEAFFFFFE,  # B .
        0x02001000,
    )
    arm7_words = (
        0xE59F100C,  # LDR r1, [pc, #12] -> literal at +20
        0xE5910000,  # LDR r0, [r1]
        0xE2800005,  # ADD r0, r0, #5
        0xE5810004,  # STR r0, [r1, #4]
        0xEAFFFFFE,  # B .
        0x02001000,
    )
    arm9 = b"".join(word.to_bytes(4, "little") for word in arm9_words)
    arm7 = b"".join(word.to_bytes(4, "little") for word in arm7_words)
    header = bytearray(0x200)
    header[:12] = b"NDS LAB DEMO"
    struct.pack_into("<4I", header, 0x20, 0x200, 0x02000000, 0x02000000, len(arm9))
    struct.pack_into(
        "<4I", header, 0x30, 0x200 + len(arm9), 0x03800000, 0x03800000, len(arm7)
    )
    return bytes(header) + arm9 + arm7
