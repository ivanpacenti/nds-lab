"""Deliberately limited ARM-state interpreter, without hardware timing."""

from dataclasses import dataclass

from nds_lab.memory import Memory

MASK32 = 0xFFFFFFFF
SIGN_BIT = 1 << 31


class UnsupportedInstruction(ValueError):
    """The instruction requires behavior outside the implemented subset."""


@dataclass(frozen=True)
class StepResult:
    address: int
    instruction: int
    executed: bool
    registers: tuple[int, ...]
    flags: tuple[bool, bool, bool, bool]


class CPU:
    def __init__(self, memory: Memory, entry_point: int = 0) -> None:
        if not 0 <= entry_point <= MASK32 or entry_point % 4:
            raise ValueError("ARM entry point must be a word-aligned 32-bit address")
        self.memory = memory
        self.registers = [0] * 16
        # Stored r15 is the next fetch address. Operand reads see address + 8.
        self.registers[15] = entry_point
        self.n = self.z = self.c = self.v = False

    @property
    def pc(self) -> int:
        return self.registers[15]

    def _read_register(self, index: int) -> int:
        if index == 15:
            return (self.pc + 8) & MASK32
        return self.registers[index] & MASK32

    def _condition_passed(self, condition: int) -> bool:
        conditions = (
            self.z,  # EQ
            not self.z,  # NE
            self.c,  # CS / HS
            not self.c,  # CC / LO
            self.n,  # MI
            not self.n,  # PL
            self.v,  # VS
            not self.v,  # VC
            self.c and not self.z,  # HI
            not self.c or self.z,  # LS
            self.n == self.v,  # GE
            self.n != self.v,  # LT
            not self.z and self.n == self.v,  # GT
            self.z or self.n != self.v,  # LE
            True,  # AL
        )
        return conditions[condition]

    def _operand2(self, instruction: int) -> tuple[int, bool]:
        if instruction & (1 << 25):
            immediate = instruction & 0xFF
            rotation = ((instruction >> 8) & 0xF) * 2
            if rotation == 0:
                return immediate, self.c
            value = ((immediate >> rotation) | (immediate << (32 - rotation))) & MASK32
            return value, bool(value & SIGN_BIT)
        if instruction & 0xFF0:
            raise UnsupportedInstruction("Shifted registers are not implemented")
        return self._read_register(instruction & 0xF), self.c

    def _data_processing(self, instruction: int) -> None:
        opcode = (instruction >> 21) & 0xF
        set_flags = bool(instruction & (1 << 20))
        source = (instruction >> 16) & 0xF
        destination = (instruction >> 12) & 0xF
        if opcode not in (2, 4, 10, 13):
            raise UnsupportedInstruction("Only SUB, ADD, CMP and MOV are implemented")
        if opcode == 10 and (not set_flags or destination != 0):
            raise UnsupportedInstruction("Unsupported CMP encoding")
        if opcode == 13 and source != 0:
            raise UnsupportedInstruction("Unsupported MOV encoding")
        if opcode != 10 and destination == 15:
            raise UnsupportedInstruction("Data-processing writes to PC are unsupported")

        # Decode and validate before changing any CPU state.
        right, carry = self._operand2(instruction)
        left = self._read_register(source)
        overflow = self.v
        if opcode == 13:  # MOV
            result = right
        elif opcode == 4:  # ADD
            total = left + right
            result = total & MASK32
            carry = total > MASK32
            overflow = bool((~(left ^ right) & (left ^ result)) & SIGN_BIT)
        else:  # SUB or CMP
            result = (left - right) & MASK32
            carry = left >= right  # ARM carry means no borrow for subtraction.
            overflow = bool(((left ^ right) & (left ^ result)) & SIGN_BIT)

        if opcode != 10:
            self.registers[destination] = result
        if set_flags:
            self.n = bool(result & SIGN_BIT)
            self.z = result == 0
            self.c = carry
            self.v = overflow

    def _single_data_transfer(self, instruction: int) -> None:
        pre_index = bool(instruction & (1 << 24))
        add_offset = bool(instruction & (1 << 23))
        write_back_bit = bool(instruction & (1 << 21))
        load = bool(instruction & (1 << 20))
        base_register = (instruction >> 16) & 0xF
        data_register = (instruction >> 12) & 0xF
        write_back = not pre_index or write_back_bit

        if instruction & (1 << 25):
            raise UnsupportedInstruction("Register-offset transfers are unsupported")
        if instruction & (1 << 22):
            raise UnsupportedInstruction("Byte transfers are unsupported")
        if not pre_index and write_back_bit:
            raise UnsupportedInstruction("Unprivileged LDRT/STRT are unsupported")
        if data_register == 15:
            raise UnsupportedInstruction("Transfers to or from PC are unsupported")
        if write_back and base_register in (15, data_register):
            raise UnsupportedInstruction("Unsupported write-back register combination")

        base = self._read_register(base_register)
        offset = instruction & 0xFFF
        if not add_offset:
            offset = -offset
        updated_base = (base + offset) & MASK32
        address = updated_base if pre_index else base

        # Commit register updates only after the memory access succeeds.
        # MemoryAccessError is a lab error; hardware data aborts are future work.
        if load:
            value = self.memory.read32(address)
            self.registers[data_register] = value
        else:
            self.memory.write32(address, self._read_register(data_register))
        if write_back:
            self.registers[base_register] = updated_base

    def step(self) -> StepResult:
        address = self.pc
        instruction = self.memory.read32(address)
        condition = instruction >> 28
        if condition == 15:
            raise UnsupportedInstruction("Condition 0xF is outside this ARM subset")
        executed = self._condition_passed(condition)
        next_pc = (address + 4) & MASK32
        if executed:
            if (instruction >> 25) & 7 == 5:  # B / BL
                displacement = instruction & 0xFFFFFF
                if displacement & (1 << 23):
                    displacement -= 1 << 24
                next_pc = (address + 8 + displacement * 4) & MASK32
                if instruction & (1 << 24):
                    self.registers[14] = (address + 4) & MASK32
            elif (instruction >> 26) & 3 == 1:
                self._single_data_transfer(instruction)
            elif (instruction >> 26) & 3 == 0:
                self._data_processing(instruction)
            else:
                raise UnsupportedInstruction(
                    f"Unsupported instruction {instruction:#010x} at {address:#010x}"
                )
        self.registers[15] = next_pc
        return StepResult(
            address,
            instruction,
            executed,
            tuple(self.registers),
            (self.n, self.z, self.c, self.v),
        )
