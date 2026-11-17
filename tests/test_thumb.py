"""Thumb instruction families, branches, state exchange and stack failures."""

import pytest

from nds_lab.cpu import CPU, UnsupportedInstruction
from nds_lab.memory import Memory, MemoryAccessError


def make_cpu(word):
    memory = Memory(4096)
    memory.write16(0, word)
    return CPU(memory, thumb=True)


@pytest.mark.parametrize(
    "word,expected",
    [
        (0x4008, 0xA0),
        (0x4048, 0x5F),
        (0x4308, 0xFF),
        (0x4388, 0x0B),
        (0x43C8, 0xFFFFFF0B),
        (0x4348, 0xA2FC),
        (0x4248, 0xFFFFFF0C),
    ],
)
def test_alu(word, expected):
    cpu = make_cpu(word)
    cpu.registers[:2] = [0xAB, 0xF4]
    cpu.step()
    assert cpu.registers[0] == expected
    assert cpu.pc == 2


@pytest.mark.parametrize(
    "word,expected",
    [(0x2005, 5), (0x3005, 12), (0x3805, 2), (0x1C48, 4), (0x1E48, 2), (0x1840, 10)],
)
def test_immediate_and_register_arithmetic(word, expected):
    cpu = make_cpu(word)
    cpu.registers[:2] = [7, 3]
    cpu.step()
    assert cpu.registers[0] == expected


@pytest.mark.parametrize(
    "word,address,width,value,expected",
    [
        (0x6808, 0x100, 4, 99, 99),
        (0x7848, 0x101, 1, 0xAB, 0xAB),
        (0x8848, 0x102, 2, 0xABCD, 0xABCD),
        (0x5A88, 0x102, 2, 0xABCD, 0xABCD),
        (0x5688, 0x102, 1, 0xAB, 0xFFFFFFAB),
        (0x5E88, 0x102, 2, 0xABCD, 0xFFFFABCD),
        (0x9801, 0x104, 4, 99, 99),
        (0x4801, 8, 4, 99, 99),
    ],
)
def test_load_families(word, address, width, value, expected):
    cpu = make_cpu(word)
    cpu.registers[1:3] = [0x100, 2]
    cpu.registers[13] = 0x100
    getattr(cpu.memory, f"write{width * 8}")(address, value)
    cpu.step()
    assert cpu.registers[0] == expected


@pytest.mark.parametrize(
    "word,address,width",
    [
        (0x6008, 0x100, 4),
        (0x7048, 0x101, 1),
        (0x8048, 0x102, 2),
        (0x5288, 0x102, 2),
        (0x9001, 0x104, 4),
    ],
)
def test_store_families(word, address, width):
    cpu = make_cpu(word)
    cpu.registers[:3] = [0x12345678, 0x100, 2]
    cpu.registers[13] = 0x100
    cpu.step()
    assert getattr(cpu.memory, f"read{width * 8}")(address) == 0x12345678 & (
        (1 << (width * 8)) - 1
    )


@pytest.mark.parametrize(
    "word,z,target,executed",
    [
        (0xD001, True, 6, True),
        (0xD001, False, 2, False),
        (0xD1FE, False, 0, True),
        (0xE7FE, False, 0, True),
    ],
)
def test_branches(word, z, target, executed):
    cpu = make_cpu(word)
    cpu.z = z
    assert cpu.step().executed == executed
    assert cpu.pc == target


def test_bl_and_bx_return():
    cpu = make_cpu(0xF000)
    cpu.memory.write16(2, 0xF802)  # target = 4 + 4 = 8
    cpu.memory.write16(8, 0x4770)
    cpu.step()
    cpu.step()
    assert cpu.pc == 8 and cpu.registers[14] == 5
    cpu.step()
    assert cpu.pc == 4 and cpu.thumb


def test_stack_failure_is_atomic():
    cpu = make_cpu(0xB503)  # PUSH {r0, r1, lr}
    cpu.registers[13] = 8
    before = cpu.registers.copy()
    with pytest.raises(MemoryAccessError):
        cpu.step()
    assert cpu.registers == before
    assert cpu.memory.read16(0) == 0xB503


def test_thumb_multiple_load_with_base_in_list():
    cpu = make_cpu(0xC903)  # LDMIA r1!, {r0,r1}, loaded base wins.
    cpu.registers[1] = 0x100
    cpu.memory.write32(0x100, 11)
    cpu.memory.write32(0x104, 22)
    cpu.step()
    assert cpu.registers[:2] == [11, 22]


@pytest.mark.parametrize(
    "word,register,expected",
    [
        (0xA001, 0, 8),
        (0xA801, 0, 0x104),
        (0xB001, 13, 0x104),
        (0xB081, 13, 0xFC),
        (0x4680, 8, 7),
        (0x4480, 8, 7),
    ],
)
def test_addresses_and_high_registers(word, register, expected):
    cpu = make_cpu(word)
    cpu.registers[0] = 7
    cpu.registers[13] = 0x100
    cpu.step()
    assert cpu.registers[register] == expected


@pytest.mark.parametrize("word", [0xDF00, 0xDE00, 0xBE00, 0xB400, 0xC000, 0x4780])
def test_unsupported_thumb_is_atomic(word):
    cpu = make_cpu(word)
    before = cpu.registers.copy()
    with pytest.raises(UnsupportedInstruction):
        cpu.step()
    assert cpu.registers == before and cpu.thumb


def test_thumb_blx_register_arm9():
    memory = Memory(4096)
    memory.write16(0, 0x4780)  # BLX r0
    cpu = CPU(memory, thumb=True, architecture="armv5te")
    cpu.registers[0] = 0x40
    cpu.step()
    assert cpu.pc == 0x40 and not cpu.thumb
    assert cpu.registers[14] == 3


@pytest.mark.parametrize(
    "architecture,expected_thumb", [("armv4t", True), ("armv5te", False)]
)
def test_pop_pc_interworking(architecture, expected_thumb):
    memory = Memory(4096)
    memory.write16(0, 0xBD00)
    memory.write32(0x100, 0x40)
    cpu = CPU(memory, thumb=True, architecture=architecture)
    cpu.registers[13] = 0x100
    cpu.step()
    assert cpu.pc == 0x40 and cpu.thumb == expected_thumb
    assert cpu.registers[13] == 0x104
