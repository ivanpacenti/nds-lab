"""Thumb-1 instruction decoding for the shared educational CPU."""

from nds_lab.alu import MASK32, add_with_carry, shift, signed
from nds_lab.cpu import CPU, UnsupportedInstruction


def _alu(cpu: CPU, instruction: int) -> None:
    opcode = (instruction >> 6) & 15
    destination = instruction & 7
    source = (instruction >> 3) & 7
    left = cpu._read_register(destination)
    right = cpu._read_register(source)
    carry, overflow = cpu.c, cpu.v
    if opcode in (0, 8):  # AND / TST
        result = left & right
    elif opcode == 1:
        result = left ^ right
    elif opcode in (2, 3, 4, 7):
        kind = {2: 0, 3: 1, 4: 2, 7: 3}[opcode]
        result, carry = shift(left, kind, right & 255, cpu.c)
    elif opcode == 5:
        result, carry, overflow = add_with_carry(left, right, cpu.c)
    elif opcode == 6:
        result, carry, overflow = add_with_carry(left, ~right, cpu.c)
    elif opcode == 9:  # NEG
        result, carry, overflow = add_with_carry(0, ~right, True)
    elif opcode == 10:
        result, carry, overflow = add_with_carry(left, ~right, True)
    elif opcode == 11:
        result, carry, overflow = add_with_carry(left, right)
    elif opcode == 12:
        result = left | right
    elif opcode == 13:
        result = left * right & MASK32
    elif opcode == 14:
        result = left & ~right
    else:
        result = ~right & MASK32
    if opcode not in (8, 10, 11):
        cpu.registers[destination] = result
    cpu._set_flags(result, carry, overflow)


def _high_register(cpu: CPU, instruction: int) -> None:
    opcode = (instruction >> 8) & 3
    destination = (instruction & 7) | ((instruction >> 4) & 8)
    source = (instruction >> 3) & 15
    right = cpu._read_register(source)
    if opcode == 3:  # BX / BLX register
        if instruction & 7:
            raise UnsupportedInstruction("Invalid Thumb BX/BLX encoding")
        if instruction & 0x80:
            if cpu.architecture != "armv5te":
                raise UnsupportedInstruction("BLX requires ARMv5")
            cpu.registers[14] = ((cpu.pc + 2) | 1) & MASK32
        cpu._write_pc(right, exchange=True)
        return
    left = cpu._read_register(destination)
    if opcode == 1:
        result, carry, overflow = add_with_carry(left, ~right, True)
        cpu._set_flags(result, carry, overflow)
        return
    result = (left + right) & MASK32 if opcode == 0 else right
    if destination == 15:
        cpu._write_pc(result)
    else:
        cpu.registers[destination] = result


def _stack(cpu: CPU, instruction: int) -> None:
    pop = bool(instruction & 0x800)
    registers = [i for i in range(8) if instruction & (1 << i)]
    if instruction & 0x100:
        registers.append(15 if pop else 14)
    if not registers:
        raise UnsupportedInstruction("Empty Thumb stack list")
    stack = cpu._read_register(13)
    size = len(registers) * 4
    address = stack if pop else (stack - size) & MASK32
    cpu._multiple_transfer(registers, address, pop)
    cpu.registers[13] = (stack + (size if pop else -size)) & MASK32


def execute_thumb(cpu: CPU, instruction: int) -> bool:
    """Execute one 16-bit instruction; return whether its condition passed."""
    destination = instruction & 7
    source = (instruction >> 3) & 7
    if instruction & 0xF800 == 0x1800:  # ADD/SUB register or three-bit immediate
        right = (instruction >> 6) & 7
        if not instruction & 0x400:
            right = cpu._read_register(right)
        subtract = bool(instruction & 0x200)
        result, carry, overflow = add_with_carry(
            cpu._read_register(source), ~right if subtract else right, subtract
        )
        cpu.registers[destination] = result
        cpu._set_flags(result, carry, overflow)
    elif instruction & 0xE000 == 0:  # Immediate LSL/LSR/ASR
        result, carry = shift(
            cpu._read_register(source),
            (instruction >> 11) & 3,
            (instruction >> 6) & 31,
            cpu.c,
            immediate=True,
        )
        cpu.registers[destination] = result
        cpu._set_flags(result, carry, cpu.v)
    elif instruction & 0xE000 == 0x2000:  # MOV/CMP/ADD/SUB immediate
        opcode = (instruction >> 11) & 3
        destination = (instruction >> 8) & 7
        right = instruction & 255
        carry, overflow = cpu.c, cpu.v
        if opcode == 0:
            result = right
        else:
            subtract = opcode in (1, 3)
            result, carry, overflow = add_with_carry(
                cpu._read_register(destination), ~right if subtract else right, subtract
            )
        if opcode != 1:
            cpu.registers[destination] = result
        cpu._set_flags(result, carry, overflow)
    elif instruction & 0xFC00 == 0x4000:
        _alu(cpu, instruction)
    elif instruction & 0xFC00 == 0x4400:
        _high_register(cpu, instruction)
    elif instruction & 0xF800 == 0x4800:  # PC-relative literal load
        address = ((cpu.pc + 4) & ~3) + (instruction & 255) * 4
        cpu._transfer(address & MASK32, (instruction >> 8) & 7, True, 4)
    elif instruction & 0xF000 == 0x5000:  # Register-offset transfers
        opcode = (instruction >> 9) & 7
        offset = cpu._read_register((instruction >> 6) & 7)
        address = (cpu._read_register(source) + offset) & MASK32
        width = (4, 2, 1, 1, 4, 2, 1, 2)[opcode]
        cpu._transfer(address, destination, opcode >= 3, width, opcode in (3, 7))
    elif instruction & 0xE000 == 0x6000:  # Word/byte immediate transfers
        width = 1 if instruction & 0x1000 else 4
        address = (
            cpu._read_register(source) + ((instruction >> 6) & 31) * width
        ) & MASK32
        cpu._transfer(address, destination, bool(instruction & 0x800), width)
    elif instruction & 0xF000 == 0x8000:  # Halfword immediate transfers
        address = (cpu._read_register(source) + ((instruction >> 6) & 31) * 2) & MASK32
        cpu._transfer(address, destination, bool(instruction & 0x800), 2)
    elif instruction & 0xF000 == 0x9000:  # SP-relative word transfers
        address = (cpu._read_register(13) + (instruction & 255) * 4) & MASK32
        cpu._transfer(address, (instruction >> 8) & 7, bool(instruction & 0x800), 4)
    elif instruction & 0xF000 == 0xA000:  # ADD address from PC/SP
        base = cpu._read_register(13) if instruction & 0x800 else (cpu.pc + 4) & ~3
        cpu.registers[(instruction >> 8) & 7] = (
            base + (instruction & 255) * 4
        ) & MASK32
    elif instruction & 0xFF00 == 0xB000:  # ADD/SUB SP
        offset = (instruction & 127) * 4
        if instruction & 0x80:
            offset = -offset
        cpu.registers[13] = (cpu._read_register(13) + offset) & MASK32
    elif instruction & 0xF600 == 0xB400:
        _stack(cpu, instruction)
    elif instruction & 0xF000 == 0xC000:  # LDMIA/STMIA
        base_register = (instruction >> 8) & 7
        load = bool(instruction & 0x800)
        registers = [i for i in range(8) if instruction & (1 << i)]
        if not registers or (not load and base_register in registers):
            raise UnsupportedInstruction("Unsupported Thumb multiple-transfer list")
        base = cpu._read_register(base_register)
        cpu._multiple_transfer(registers, base, load)
        if not load or base_register not in registers:
            cpu.registers[base_register] = (base + len(registers) * 4) & MASK32
    elif instruction & 0xF000 == 0xD000:
        condition = (instruction >> 8) & 15
        if condition >= 14:
            raise UnsupportedInstruction("Thumb SWI/reserved condition is unsupported")
        if not cpu._condition_passed(condition):
            return False
        cpu._next_pc = (cpu.pc + 4 + signed(instruction, 8) * 2) & MASK32
    elif instruction & 0xF800 == 0xE000:
        cpu._next_pc = (cpu.pc + 4 + signed(instruction, 11) * 2) & MASK32
    elif instruction & 0xF800 == 0xF000:  # First half of Thumb BL
        cpu.registers[14] = (cpu.pc + 4 + (signed(instruction, 11) << 12)) & MASK32
    elif instruction & 0xF800 == 0xF800:  # Second half of Thumb BL
        target = (cpu._read_register(14) + (instruction & 0x7FF) * 2) & MASK32
        cpu.registers[14] = ((cpu.pc + 2) | 1) & MASK32
        cpu._write_pc(target)
    else:
        raise UnsupportedInstruction(
            f"Unsupported Thumb instruction {instruction:#06x}"
        )
    return True
