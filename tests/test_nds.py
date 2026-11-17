"""Validate cartridge boundaries and execute both CPUs through the loader and CLI."""

import struct
import subprocess
import sys

import pytest

from nds_lab.experiments import run_nds
from nds_lab.memory import MemoryAccessError
from nds_lab.nds import NDS, ROMError, make_demo_rom


def replace_header(offset, value):
    rom = bytearray(make_demo_rom())
    struct.pack_into("<I", rom, offset, value)
    return bytes(rom)


def test_two_cpu_execution_and_memory_isolation():
    machine = run_nds()
    assert machine.title == "NDS LAB DEMO"
    assert machine.main_ram.read32(0x02001000) == 7
    assert machine.main_ram.read32(0x02001004) == 12
    assert machine.arm9.registers[0] == 7
    assert machine.arm7.registers[0] == 12
    assert machine.arm9.architecture == "armv5te"
    assert machine.arm7.architecture == "armv4t"
    machine.arm7.memory.write32(0x03000000, 42)
    assert machine.shared_wram.read32(0x03000000) == 42
    with pytest.raises(MemoryAccessError):
        machine.arm9.memory.read32(0x03000000)
    with pytest.raises(MemoryAccessError):
        machine.arm9.memory.read32(0x03800000)
    with pytest.raises(MemoryAccessError):
        machine.arm7.memory.read32(0x04000000)


def test_instances_have_independent_memory():
    first, second = NDS(make_demo_rom()), NDS(make_demo_rom())
    first.main_ram.write32(0x02001000, 77)
    assert second.main_ram.read32(0x02001000) == 0


@pytest.mark.parametrize(
    "offset,value",
    [
        (0x20, 0x100),  # Binary overlaps header
        (0x20, 0xFFFFFFFF),  # ROM offset outside image
        (0x2C, 0),
        (0x3C, 0),  # Empty binaries
        (0x2C, 0xFFFFFFFF),  # ROM size overflow
        (0x28, 0x04000000),  # MMIO destination
        (0x28, 0x023FFFFC),  # Main RAM boundary crossed
        (0x28, 0xFFFFFFFC),  # Address-space overflow
        (0x24, 0x02001000),  # Entry outside section
        (0x24, 0x02000002),  # Unaligned ARM entry
    ],
)
def test_invalid_headers(offset, value):
    with pytest.raises(ROMError):
        NDS(replace_header(offset, value))


@pytest.mark.parametrize("size", [0, 32, 511])
def test_truncated_header(size):
    with pytest.raises(ROMError):
        NDS(bytes(size))


def test_truncated_binary():
    with pytest.raises(ROMError):
        NDS(make_demo_rom()[:-1])


def test_overlapping_destinations():
    rom = bytearray(make_demo_rom())
    struct.pack_into("<I", rom, 0x34, 0x02000000)
    struct.pack_into("<I", rom, 0x38, 0x02000000)
    with pytest.raises(ROMError, match="overlap"):
        NDS(bytes(rom))


def test_dsi_rejected():
    rom = bytearray(make_demo_rom())
    rom[0x12] = 2
    with pytest.raises(ROMError):
        NDS(bytes(rom))


def test_thumb_entry_executes_through_loader():
    rom = bytearray(make_demo_rom())
    struct.pack_into("<I", rom, 0x24, 0x02000001)
    struct.pack_into("<H", rom, 0x200, 0x202A)  # MOV r0, #42
    machine = NDS(bytes(rom))
    step = machine.step("arm9")
    assert step.thumb
    assert machine.arm9.registers[0] == 42
    assert machine.arm9.pc == 0x02000002


def test_invalid_processor():
    with pytest.raises(ValueError):
        NDS(make_demo_rom()).step("invalid")


def test_loader_cli(tmp_path):
    path = tmp_path / "experiment.nds"
    path.write_bytes(make_demo_rom())
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nds_lab",
            "--rom",
            str(path),
            "--cpu",
            "arm9",
            "--steps",
            "4",
            "--trace",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "arm9:" in result.stdout
    assert "Executed 4 instructions" in result.stdout


@pytest.mark.parametrize(
    "arguments,expected",
    [
        (["--steps", "0"], "must be positive"),
        (["--steps", "-1"], "must be positive"),
        (["--rom", "/missing/nds-lab.nds"], "Error:"),
        (["--rom", "missing", "--demo", "sum"], "not allowed"),
    ],
)
def test_cli_errors(arguments, expected):
    result = subprocess.run(
        [sys.executable, "-m", "nds_lab", *arguments], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert expected in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_reports_processor_and_pc_on_unimplemented_hardware(tmp_path):
    rom = bytearray(make_demo_rom())
    struct.pack_into("<I", rom, 0x200, 0xEF000000)  # SWI
    path = tmp_path / "unsupported.nds"
    path.write_bytes(rom)
    result = subprocess.run(
        [sys.executable, "-m", "nds_lab", "--rom", str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "arm9 at 0x02000000" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("demo", ["logic", "widths", "stack", "thumb", "nds"])
def test_demo_cli(demo):
    result = subprocess.run(
        [sys.executable, "-m", "nds_lab", "--demo", demo, "--trace"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "r15=" in result.stdout
    if demo == "thumb":
        assert "THUMB" in result.stdout


def test_partial_entry_instruction():
    rom = bytearray(make_demo_rom())
    struct.pack_into("<I", rom, 0x24, 0x02000013)
    struct.pack_into("<I", rom, 0x2C, 19)
    with pytest.raises(ROMError, match="Entry instruction"):
        NDS(bytes(rom))


@pytest.mark.parametrize("address", [0x04000000, 0x023FFFFC])
def test_mapped_destination_validation(address):
    rom = bytearray(make_demo_rom())
    struct.pack_into("<I", rom, 0x24, address)
    struct.pack_into("<I", rom, 0x28, address)
    with pytest.raises(ROMError, match="unsupported memory"):
        NDS(bytes(rom))
