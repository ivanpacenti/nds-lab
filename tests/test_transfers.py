"""Exercise real ARM encodings and memory-transfer failure boundaries."""

import subprocess
import sys

import pytest

from nds_lab.cpu import CPU, UnsupportedInstruction
from nds_lab.demo import DATA_ADDRESS, MEMORY_VALUES, RESULT_ADDRESS, run_memory_demo
from nds_lab.memory import Memory, MemoryAccessError


@pytest.mark.parametrize(
    "word,address,final_base,load",
    [
        (0xE5910004, 0x104, 0x100, True),  # LDR r0, [r1, #4]
        (0xE5110004, 0xFC, 0x100, True),  # LDR r0, [r1, #-4]
        (0xE5B10004, 0x104, 0x104, True),  # LDR r0, [r1, #4]!
        (0xE5310004, 0xFC, 0xFC, True),  # LDR r0, [r1, #-4]!
        (0xE4910004, 0x100, 0x104, True),  # LDR r0, [r1], #4
        (0xE4110004, 0x100, 0xFC, True),  # LDR r0, [r1], #-4
        (0xE5810004, 0x104, 0x100, False),
        (0xE5010004, 0xFC, 0x100, False),
        (0xE5A10004, 0x104, 0x104, False),
        (0xE5210004, 0xFC, 0xFC, False),
        (0xE4810004, 0x100, 0x104, False),
        (0xE4010004, 0x100, 0xFC, False),
    ],
)
def test_addressing_modes(word, address, final_base, load):
    memory = Memory(512)
    memory.write32(0, word)
    memory.write32(address, 0x89ABCDEF)
    cpu = CPU(memory)
    cpu.registers[0] = 0x12345678
    cpu.registers[1] = 0x100
    cpu.n, cpu.z, cpu.c, cpu.v = True, False, True, True
    step = cpu.step()
    assert cpu.registers[1] == final_base
    assert cpu.pc == 4
    assert step.flags == (True, False, True, True)
    if load:
        assert cpu.registers[0] == 0x89ABCDEF
        assert memory.read32(address) == 0x89ABCDEF
    else:
        assert cpu.registers[0] == 0x12345678
        assert memory.read32(address) == 0x12345678
        assert [memory.read8(address + i) for i in range(4)] == [0x78, 0x56, 0x34, 0x12]


@pytest.mark.parametrize("word", [0xE5911000, 0xE5811000])
def test_base_can_equal_data_register_without_writeback(word):
    memory = Memory(64)
    memory.write32(0, word)
    memory.write32(32, 99)
    cpu = CPU(memory)
    cpu.registers[1] = 32
    cpu.step()
    if word == 0xE5911000:
        assert cpu.registers[1] == 99
    else:
        assert memory.read32(32) == 32
        assert cpu.registers[1] == 32


def test_pc_relative_literal_load():
    memory = Memory(32)
    memory.write32(0, 0xE59F0004)  # LDR r0, [pc, #4] reads address 12.
    memory.write32(12, 0xDEADBEEF)
    cpu = CPU(memory)
    cpu.step()
    assert cpu.registers[0] == 0xDEADBEEF
    assert cpu.pc == 4


@pytest.mark.parametrize("word", [0x05910000, 0x05810000])
def test_false_condition_skips_even_invalid_address(word):
    memory = Memory(16)
    memory.write32(0, word)
    cpu = CPU(memory)
    cpu.registers[1] = 0xFFFFFFFC
    assert not cpu.step().executed
    assert cpu.pc == 4
    assert cpu.registers[1] == 0xFFFFFFFC
    assert memory.read32(0) == word


@pytest.mark.parametrize("word", [0xE5B10004, 0xE5A10004, 0xE4910004, 0xE4810004])
@pytest.mark.parametrize("base", [1, 64])
def test_memory_failure_preserves_state(word, base):
    memory = Memory(64)
    memory.write32(0, word)
    cpu = CPU(memory)
    cpu.registers[0:2] = [0x12345678, base]
    cpu.n = cpu.c = True
    before = cpu.registers.copy()
    contents = bytes(memory.read8(i) for i in range(64))
    with pytest.raises(MemoryAccessError):
        cpu.step()
    assert cpu.registers == before
    assert (cpu.n, cpu.z, cpu.c, cpu.v) == (True, False, True, False)
    assert bytes(memory.read8(i) for i in range(64)) == contents


@pytest.mark.parametrize(
    "word",
    [
        0xE4B10004,  # LDRT
        0xE4A10004,  # STRT
        0xE581F000,  # STR pc
        0xE5BF0004,  # PC base with write-back
        0xE49F0004,  # PC base with post-indexing
        0xE5B11004,  # LDR base equals destination with write-back
        0xE4811004,  # STR base equals source with post-indexing
    ],
)
def test_rejected_transfers_have_no_side_effects(word):
    memory = Memory(64)
    memory.write32(0, word)
    cpu = CPU(memory)
    cpu.registers[1] = 32
    before = cpu.registers.copy()
    with pytest.raises(UnsupportedInstruction):
        cpu.step()
    assert cpu.registers == before
    assert memory.read32(0) == word
    assert memory.read32(32) == 0


def test_address_wraparound():
    memory = Memory(16)
    memory.write32(0, 0xE5B10004)  # LDR r0, [r1, #4]!
    cpu = CPU(memory)
    cpu.registers[1] = 0xFFFFFFFC
    cpu.step()
    assert cpu.registers[0] == 0xE5B10004
    assert cpu.registers[1] == 0


def test_full_immediate_offset():
    memory = Memory(8192)
    memory.write32(0, 0xE5910FFF)  # LDR r0, [r1, #4095]
    memory.write32(4096, 77)
    cpu = CPU(memory)
    cpu.registers[1] = 1
    cpu.step()
    assert cpu.registers[0] == 77


def test_memory_demo_stores_sum_and_preserves_input():
    cpu, steps = run_memory_demo()
    assert cpu.memory.read32(RESULT_ADDRESS) == 55
    assert cpu.registers[:4] == [55, 0x128, 0, 10]
    assert steps == 44
    assert cpu.pc == 32
    assert (
        tuple(cpu.memory.read32(DATA_ADDRESS + i * 4) for i in range(10))
        == MEMORY_VALUES
    )


def test_memory_demo_honors_budget():
    with pytest.raises(RuntimeError, match="budget"):
        run_memory_demo(max_steps=3)


@pytest.mark.parametrize(
    "demo,expected",
    [
        ("sum", "Sum 1..10 = 55 (42 instructions)"),
        ("memory", "Memory sum = 55, stored at 0x00000140 (44 instructions)"),
    ],
)
def test_cli(demo, expected):
    result = subprocess.run(
        [sys.executable, "-m", "nds_lab", "--demo", demo, "--trace"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.splitlines()[-1] == expected
    assert "r15=" in result.stdout
