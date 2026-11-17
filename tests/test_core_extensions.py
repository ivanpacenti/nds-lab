"""Instruction and boundary regressions for logical operations, widths and calls."""

import pytest

from nds_lab.alu import shift
from nds_lab.cpu import CPU, UnsupportedInstruction
from nds_lab.experiments import run_logic, run_stack, run_thumb, run_widths
from nds_lab.memory import Memory, MemoryAccessError


def cpu_with(word, *, thumb=False, architecture="armv4t"):
    memory = Memory(4096)
    memory.load(0, word.to_bytes(2 if thumb else 4, "little"))
    return CPU(memory, thumb=thumb, architecture=architecture)


@pytest.mark.parametrize(
    "kind,amount,value,expected,carry",
    [
        (0, 0, 0x80000001, 0x80000001, True),
        (0, 1, 0x80000001, 2, True),
        (0, 31, 3, 0x80000000, True),
        (0, 32, 1, 0, True),
        (0, 33, 1, 0, False),
        (1, 0, 0x80000001, 0x80000001, True),
        (1, 1, 0x80000001, 0x40000000, True),
        (1, 32, 0x80000000, 0, True),
        (1, 33, 0x80000000, 0, False),
        (2, 0, 0x80000001, 0x80000001, True),
        (2, 1, 0x80000001, 0xC0000000, True),
        (2, 32, 0x80000000, 0xFFFFFFFF, True),
        (2, 255, 0x80000000, 0xFFFFFFFF, True),
        (2, 32, 0x7FFFFFFF, 0, False),
        (3, 0, 1, 1, True),
        (3, 1, 1, 0x80000000, True),
        (3, 32, 0x80000001, 0x80000001, True),
        (3, 64, 1, 1, False),
        (3, 33, 1, 0x80000000, True),
    ],
)
def test_register_shift_boundaries(kind, amount, value, expected, carry):
    assert shift(value, kind, amount, True) == (expected, carry)


@pytest.mark.parametrize(
    "kind,expected,carry",
    [(0, 0x80000001, True), (1, 0, True), (2, 0xFFFFFFFF, True), (3, 0xC0000000, True)],
)
def test_immediate_zero_encodings(kind, expected, carry):
    assert shift(0x80000001, kind, 0, True, immediate=True) == (expected, carry)


@pytest.mark.parametrize(
    "word,expected",
    [
        (0xE0010002, 0xA0),
        (0xE0210002, 0x5F),
        (0xE1810002, 0xFF),
        (0xE1C10002, 0x0B),
        (0xE1E00002, 0xFFFFFF0B),
    ],
)
def test_logic_instruction_words(word, expected):
    cpu = cpu_with(word)
    cpu.registers[1:3] = [0xAB, 0xF4]
    cpu.n = cpu.c = cpu.v = True
    step = cpu.step()
    assert cpu.registers[0] == expected
    assert step.flags == (True, False, True, True)


@pytest.mark.parametrize(
    "word,left,right,expected,flags",
    [
        (0xE0B10002, 0xFFFFFFFF, 0, 0, (False, True, True, False)),  # ADCS
        (0xE0D10002, 5, 3, 2, (False, False, True, False)),  # SBCS with C=1
        (0xE0710002, 7, 3, 0xFFFFFFFC, (True, False, False, False)),  # RSBS
        (0xE0F10002, 7, 3, 0xFFFFFFFC, (True, False, False, False)),  # RSCS
    ],
)
def test_arithmetic_extensions(word, left, right, expected, flags):
    cpu = cpu_with(word)
    cpu.registers[1:3] = [left, right]
    cpu.c = True
    assert cpu.step().flags == flags
    assert cpu.registers[0] == expected


@pytest.mark.parametrize(
    "word,flags",
    [
        (0xE1110002, (False, True, True, True)),
        (0xE1310002, (False, False, True, True)),
        (0xE1710002, (False, False, False, False)),
    ],
)
def test_tst_teq_cmn_preserve_registers(word, flags):
    cpu = cpu_with(word)
    cpu.registers[1:3] = [1, 2]
    cpu.c = cpu.v = True
    before = cpu.registers[:15]
    assert cpu.step().flags == flags
    assert cpu.registers[:15] == before


def test_register_shift_count_uses_low_byte():
    cpu = cpu_with(0xE1B00211)  # MOVS r0, r1, LSL r2
    cpu.registers[1:3] = [1, 0x101]
    cpu.step()
    assert cpu.registers[0] == 2


@pytest.mark.parametrize("word,expected", [(0xE1A00101, 4), (0xE0000190, 3)])
def test_previously_unsupported_instructions(word, expected):
    cpu = cpu_with(word)
    cpu.registers[:2] = [3, 1]
    cpu.step()
    assert cpu.registers[0] == expected


def test_mov_pc_branches_and_aligns():
    cpu = cpu_with(0xE3A0F009)
    cpu.step()
    assert cpu.pc == 8 and not cpu.thumb


@pytest.mark.parametrize(
    "word,width,expected",
    [
        (0xE5D10001, 1, 0xAB),
        (0xE1D100D1, 1, 0xFFFFFFAB),
        (0xE1D100B2, 2, 0xABCD),
        (0xE1D100F2, 2, 0xFFFFABCD),
        (0xE19100B2, 2, 0xABCD),  # LDRH r0, [r1, r2]
    ],
)
def test_unsigned_and_signed_loads(word, width, expected):
    cpu = cpu_with(word)
    cpu.registers[1:3] = [0x100, 2]
    cpu.memory.write8(0x101, 0xAB)
    cpu.memory.write16(0x102, 0xABCD)
    assert cpu.step().flags == (False, False, False, False)
    assert cpu.registers[0] == expected


@pytest.mark.parametrize(
    "word,address,width",
    [(0xE5C10001, 0x101, 1), (0xE1C100B2, 0x102, 2), (0xE18100B2, 0x102, 2)],
)
def test_stores_truncate_and_preserve_neighbors(word, address, width):
    cpu = cpu_with(word)
    cpu.registers[:3] = [0x12345678, 0x100, 2]
    cpu.memory.write32(0x100, 0xFFFFFFFF)
    cpu.step()
    assert cpu.memory.read8(0x100) == 255
    assert cpu.memory.read8(address) == 0x78
    if width == 2:
        assert cpu.memory.read8(address + 1) == 0x56


def test_shifted_register_address():
    cpu = cpu_with(0xE7910102)  # LDR r0, [r1, r2, LSL #2]
    cpu.registers[1:3] = [0x100, 3]
    cpu.memory.write32(0x10C, 99)
    cpu.step()
    assert cpu.registers[0] == 99


@pytest.mark.parametrize("word", [0xE1F100B1, 0xE1E100B1])
def test_halfword_alignment_failure_is_atomic(word):
    cpu = cpu_with(word)
    cpu.registers[1] = 0x100
    before = cpu.registers.copy()
    with pytest.raises(MemoryAccessError):
        cpu.step()
    assert cpu.registers == before


@pytest.mark.parametrize("architecture,thumb", [("armv4t", False), ("armv5te", True)])
def test_ldr_pc_architecture_difference(architecture, thumb):
    cpu = cpu_with(0xE591F000, architecture=architecture)
    cpu.registers[1] = 0x100
    cpu.memory.write32(0x100, 0x21)
    cpu.step()
    assert cpu.pc == 0x20
    assert cpu.thumb == thumb


def test_bx_switches_both_directions():
    cpu = cpu_with(0xE12FFF10)  # BX r0
    cpu.registers[0] = 0x21
    cpu.memory.write16(0x20, 0x4708)  # BX r1
    cpu.registers[1] = 0x40
    assert not cpu.step().thumb
    assert cpu.pc == 0x20 and cpu.thumb
    assert cpu.step().thumb
    assert cpu.pc == 0x40 and not cpu.thumb


@pytest.mark.parametrize(
    "mode,start,updated",
    [
        (0x00800000, 0x100, 0x108),
        (0x01800000, 0x104, 0x108),
        (0, 0xFC, 0xF8),
        (0x01000000, 0xF8, 0xF8),
    ],
)
@pytest.mark.parametrize("load", [False, True])
def test_block_addressing_modes(mode, start, updated, load):
    word = 0xE8200005 | mode | (int(load) << 20) | (1 << 16)
    cpu = cpu_with(word)
    cpu.registers[:3] = [11, 0x100, 22]
    cpu.memory.write32(start, 33)
    cpu.memory.write32(start + 4, 44)
    cpu.step()
    assert cpu.registers[1] == updated
    if load:
        assert (cpu.registers[0], cpu.registers[2]) == (33, 44)
    else:
        assert (cpu.memory.read32(start), cpu.memory.read32(start + 4)) == (11, 22)


@pytest.mark.parametrize("word", [0xE8A10005, 0xE8B10005])
def test_block_failure_and_retry(word):
    cpu = cpu_with(word)
    cpu.registers[:3] = [11, 4092, 22]
    before = cpu.registers.copy()
    with pytest.raises(MemoryAccessError):
        cpu.step()
    assert cpu.registers == before
    assert cpu.memory.read32(4092) == 0
    cpu.registers[1] = 0x100
    cpu.step()
    assert cpu.registers[1] == 0x108


@pytest.mark.parametrize("runner", [run_logic, run_widths, run_stack, run_thumb])
def test_experiments(runner):
    runner()


@pytest.mark.parametrize(
    "word",
    [
        0xE1B0F00E,
        0xE8F10001,
        0xE8B10002,
        0xE8800000,
        0xE1C100D0,
        0xE1A00F11,
        0xE7910012,
    ],
)
def test_unsupported_encodings_remain_atomic(word):
    cpu = cpu_with(word)
    before = cpu.registers.copy()
    with pytest.raises(UnsupportedInstruction):
        cpu.step()
    assert cpu.registers == before


def test_arm_blx_register_links_before_switching_state():
    cpu = cpu_with(0xE12FFF30, architecture="armv5te")
    cpu.registers[0] = 0x21
    cpu.step()
    assert cpu.registers[14] == 4
    assert cpu.pc == 0x20 and cpu.thumb


def test_halfword_post_indexing_and_sign_extension():
    cpu = cpu_with(0xE0D100F2)  # LDRSH r0, [r1], #2
    cpu.registers[1] = 0x100
    cpu.memory.write16(0x100, 0x8000)
    cpu.step()
    assert cpu.registers[0] == 0xFFFF8000
    assert cpu.registers[1] == 0x102


def test_byte_register_offset_store():
    cpu = cpu_with(0xE7C10002)  # STRB r0, [r1, r2]
    cpu.registers[:3] = [0x12345678, 0x100, 3]
    cpu.step()
    assert cpu.memory.read8(0x103) == 0x78


def test_mla():
    cpu = cpu_with(0xE0203291)  # MLA r0, r1, r2, r3
    cpu.registers[1:4] = [7, 6, 1]
    cpu.step()
    assert cpu.registers[0] == 43


def test_pc_operand_during_register_shift():
    cpu = cpu_with(0xE1A0021F)  # MOV r0, pc, LSL r2
    cpu.registers[2] = 1
    cpu.step()
    assert cpu.registers[0] == 24
