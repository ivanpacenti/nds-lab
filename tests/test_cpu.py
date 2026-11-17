from itertools import product

import pytest

from nds_lab.cpu import CPU, UnsupportedInstruction
from nds_lab.demo import format_step, run_demo
from nds_lab.memory import Memory, MemoryAccessError


def cpu_with(instruction, address=0):
    memory = Memory(64, base=address)
    memory.write32(address, instruction)
    return CPU(memory, entry_point=address)


def test_sum_program():
    cpu, steps = run_demo()
    assert cpu.registers[0] == 55
    assert cpu.registers[1] == 11
    assert cpu.pc == 24
    assert cpu.z and cpu.c
    assert steps == 42


def test_budget_bounds_execution():
    with pytest.raises(RuntimeError, match="budget"):
        run_demo(max_steps=3)


@pytest.mark.parametrize(
    "word,left,right,result,flags",
    [
        (0xE0902001, 0xFFFFFFFF, 1, 0, (False, True, True, False)),
        (0xE0902001, 0x7FFFFFFF, 1, 0x80000000, (True, False, False, True)),
        (0xE0902001, 0x80000000, 0x80000000, 0, (False, True, True, True)),
        (0xE0502001, 0, 1, 0xFFFFFFFF, (True, False, False, False)),
        (0xE0502001, 0x80000000, 1, 0x7FFFFFFF, (False, False, True, True)),
        (0xE0502001, 0x7FFFFFFF, 0xFFFFFFFF, 0x80000000, (True, False, False, True)),
        (0xE0502001, 7, 7, 0, (False, True, True, False)),
    ],
)
def test_arithmetic_flags(word, left, right, result, flags):
    cpu = cpu_with(word)
    cpu.registers[0:2] = [left, right]
    step = cpu.step()
    assert cpu.registers[2] == result
    assert step.flags == flags


def test_cmp_preserves_registers():
    cpu = cpu_with(0xE3500005)  # CMP r0, #5
    cpu.registers[0] = 5
    before = cpu.registers[:15]
    assert cpu.step().flags == (False, True, True, False)
    assert cpu.registers[:15] == before


def test_arithmetic_without_s_preserves_flags():
    cpu = cpu_with(0xE2800001)
    cpu.registers[0] = 0xFFFFFFFF
    cpu.n, cpu.z, cpu.c, cpu.v = True, False, False, True
    assert cpu.step().flags == (True, False, False, True)
    assert cpu.registers[0] == 0


@pytest.mark.parametrize(
    "word,expected,carry",
    [
        (0xE3B00005, 5, True),
        (0xE3B00102, 0x80000000, True),
        (0xE3B004FF, 0xFF000000, True),
        (0xE3B00201, 0x10000000, False),
    ],
)
def test_mov_immediate_rotation_and_flags(word, expected, carry):
    cpu = cpu_with(word)
    cpu.c = cpu.v = True
    step = cpu.step()
    assert cpu.registers[0] == expected
    assert step.flags == (bool(expected & 0x80000000), False, carry, True)


def test_register_mov_and_pc_operand():
    cpu = cpu_with(0xE1A0000F, address=0x02000000)  # MOV r0, pc
    cpu.step()
    assert cpu.registers[0] == 0x02000008
    assert cpu.pc == 0x02000004


@pytest.mark.parametrize("n,z,c,v", list(product([False, True], repeat=4)))
def test_all_conditions_through_step(n, z, c, v):
    # Independent truth-table ordering, evaluated through instruction execution.
    expected = [
        z,
        not z,
        c,
        not c,
        n,
        not n,
        v,
        not v,
        c and not z,
        not c or z,
        n == v,
        n != v,
        not z and n == v,
        z or n != v,
        True,
    ]
    for condition, should_execute in enumerate(expected):
        cpu = cpu_with((condition << 28) | 0x03A00009)  # MOV{cond} r0, #9
        cpu.n, cpu.z, cpu.c, cpu.v = n, z, c, v
        step = cpu.step()
        assert step.executed == should_execute
        assert cpu.registers[0] == (9 if should_execute else 0)
        assert cpu.pc == 4
        assert step.flags == (n, z, c, v)


@pytest.mark.parametrize(
    "word,address,target,link",
    [
        (0xEA000000, 0, 8, 0),
        (0xEAFFFFFE, 0, 0, 0),
        (0xEB000001, 0, 12, 4),
        (0xEAFFFFFC, 16, 8, 0),
        (0xEAFFFFFF, 0xFFFFFFFC, 0, 0),
    ],
)
def test_branches(word, address, target, link):
    memory = Memory(4, address)
    memory.write32(address, word)
    cpu = CPU(memory, address)
    cpu.step()
    assert cpu.pc == target
    assert cpu.registers[14] == link


@pytest.mark.parametrize(
    "word",
    [
        0xE320F000,
        0xFA000000,
        0xE3511001,
        0xE3A10001,
    ],
)
def test_unsupported_instructions_leave_state_unchanged(word):
    cpu = cpu_with(word)
    before = cpu.registers.copy()
    with pytest.raises(UnsupportedInstruction):
        cpu.step()
    assert cpu.registers == before
    assert (cpu.n, cpu.z, cpu.c, cpu.v) == (False, False, False, False)


def test_failed_condition_skips_unsupported_body():
    cpu = cpu_with(0x05800000)  # STREQ, with Z clear
    assert not cpu.step().executed
    assert cpu.pc == 4


def test_invalid_fetch_leaves_pc_unchanged():
    cpu = CPU(Memory(4), entry_point=4)
    with pytest.raises(MemoryAccessError):
        cpu.step()
    assert cpu.pc == 4


def test_step_snapshot_and_trace():
    cpu = cpu_with(0xE3A00005)
    step = cpu.step()
    cpu.registers[0] = 99
    assert step.registers[0] == 5
    text = format_step(step)
    assert "E3A00005" in text
    assert "r0=00000005" in text
    assert "r15=00000004" in text


@pytest.mark.parametrize("address", [-4, 1, 0x100000000])
def test_invalid_entry_point(address):
    with pytest.raises(ValueError):
        CPU(Memory(4), address)
