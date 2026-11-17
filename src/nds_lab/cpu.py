"""Educational ARM/Thumb interpreter with explicit unsupported hardware boundaries."""

from dataclasses import dataclass

from nds_lab.alu import MASK32, SIGN_BIT, add_with_carry, shift, signed
from nds_lab.memory import MemoryBus


class UnsupportedInstruction(ValueError):
    """The instruction requires behavior outside the implemented subset."""


@dataclass(frozen=True)
class StepResult:
    address: int
    instruction: int
    executed: bool
    registers: tuple[int, ...]
    flags: tuple[bool, bool, bool, bool]
    thumb: bool = False


class CPU:
    def __init__(
        self,
        memory: MemoryBus,
        entry_point: int = 0,
        *,
        thumb: bool = False,
        architecture: str = "armv4t",
    ) -> None:
        if architecture not in ("armv4t", "armv5te"):
            raise ValueError("Expected armv4t or armv5te")
        self.architecture = architecture
        self.thumb = thumb
        if not 0 <= entry_point <= MASK32 or entry_point % (2 if thumb else 4):
            raise ValueError(
                "Entry point must be aligned for the selected instruction state"
            )
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
            return (self.pc + (4 if self.thumb else 8)) & MASK32
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
            return shift(immediate, 3, rotation, self.c)
        register_shift = bool(instruction & (1 << 4))
        kind = (instruction >> 5) & 3
        value = self._read_register(instruction & 0xF)
        if register_shift:
            if instruction & (1 << 7):
                raise UnsupportedInstruction("Invalid register-shift encoding")
            shift_register = (instruction >> 8) & 0xF
            if shift_register == 15:
                raise UnsupportedInstruction(
                    "PC as shift-count register is unsupported"
                )
            amount = self._read_register(shift_register) & 0xFF
            if instruction & 0xF == 15:
                value = (value + 4) & MASK32  # ARM register-shift reads PC + 12.
        else:
            amount = (instruction >> 7) & 0x1F
        return shift(value, kind, amount, self.c, immediate=not register_shift)

    def _set_flags(self, result: int, carry: bool, overflow: bool) -> None:
        self.n = bool(result & SIGN_BIT)
        self.z = result == 0
        self.c = carry
        self.v = overflow

    def _write_pc(self, value: int, *, exchange: bool = False) -> None:
        if exchange:
            self.thumb = bool(value & 1)
        self._next_pc = value & (MASK32 - (1 if self.thumb else 3))

    def _data_processing(self, instruction: int) -> None:
        opcode = (instruction >> 21) & 0xF
        set_flags = bool(instruction & (1 << 20))
        source = (instruction >> 16) & 0xF
        destination = (instruction >> 12) & 0xF
        test = 8 <= opcode <= 11
        if test and (not set_flags or destination != 0):
            raise UnsupportedInstruction("Unsupported test instruction encoding")
        if opcode in (13, 15) and source != 0:
            raise UnsupportedInstruction("Unsupported MOV/MVN encoding")
        if not test and destination == 15 and set_flags:
            raise UnsupportedInstruction("SPSR exception returns are unsupported")
        right, carry = self._operand2(instruction)
        left = self._read_register(source)
        overflow = self.v
        if opcode in (0, 8):
            result = left & right
        elif opcode in (1, 9):
            result = left ^ right
        elif opcode in (2, 10):
            result, carry, overflow = add_with_carry(left, ~right, True)
        elif opcode == 3:
            result, carry, overflow = add_with_carry(right, ~left, True)
        elif opcode in (4, 11):
            result, carry, overflow = add_with_carry(left, right)
        elif opcode == 5:
            result, carry, overflow = add_with_carry(left, right, self.c)
        elif opcode == 6:
            result, carry, overflow = add_with_carry(left, ~right, self.c)
        elif opcode == 7:
            result, carry, overflow = add_with_carry(right, ~left, self.c)
        elif opcode == 12:
            result = left | right
        elif opcode == 13:
            result = right
        elif opcode == 14:
            result = left & ~right
        else:
            result = ~right & MASK32
        if not test:
            if destination == 15:
                self._write_pc(result)
            else:
                self.registers[destination] = result
        if set_flags:
            self._set_flags(result, carry, overflow)

    def _transfer(
        self,
        address: int,
        register: int,
        load: bool,
        width: int,
        sign_extend: bool = False,
    ) -> None:
        if load:
            value = getattr(self.memory, f"read{width * 8}")(address)
            if sign_extend:
                value = signed(value, width * 8) & MASK32
            if register == 15:
                self._write_pc(value, exchange=self.architecture == "armv5te")
            else:
                self.registers[register] = value
        else:
            getattr(self.memory, f"write{width * 8}")(
                address, self._read_register(register)
            )

    def _single_data_transfer(
        self, instruction: int, *, halfword: bool = False
    ) -> None:
        pre_index = bool(instruction & (1 << 24))
        add_offset = bool(instruction & (1 << 23))
        write_back_bit = bool(instruction & (1 << 21))
        load = bool(instruction & (1 << 20))
        base_register = (instruction >> 16) & 0xF
        data_register = (instruction >> 12) & 0xF
        write_back = not pre_index or write_back_bit
        sign_extend = False
        if halfword:
            operation = (instruction >> 5) & 3
            if operation == 0 or (not load and operation != 1):
                raise UnsupportedInstruction("Unsupported extra transfer encoding")
            width = 1 if operation == 2 else 2
            sign_extend = operation in (2, 3)
            if instruction & (1 << 22):
                offset = ((instruction >> 4) & 0xF0) | (instruction & 0xF)
            else:
                if instruction & 0xF00 or instruction & 0xF == 15:
                    raise UnsupportedInstruction("Invalid halfword offset register")
                offset = self._read_register(instruction & 0xF)
        else:
            width = 1 if instruction & (1 << 22) else 4
            if instruction & (1 << 25):
                if instruction & (1 << 4) or instruction & 0xF == 15:
                    raise UnsupportedInstruction("Invalid transfer offset register")
                offset, _ = shift(
                    self._read_register(instruction & 0xF),
                    (instruction >> 5) & 3,
                    (instruction >> 7) & 31,
                    self.c,
                    immediate=True,
                )
            else:
                offset = instruction & 0xFFF
        if not pre_index and write_back_bit:
            raise UnsupportedInstruction("Unprivileged transfers are unsupported")
        if data_register == 15 and (width != 4 or not load):
            raise UnsupportedInstruction("This transfer involving PC is unsupported")
        if write_back and base_register in (15, data_register):
            raise UnsupportedInstruction("Unsupported write-back register combination")
        base = self._read_register(base_register)
        if not add_offset:
            offset = -offset
        updated_base = (base + offset) & MASK32
        address = updated_base if pre_index else base
        self._transfer(address, data_register, load, width, sign_extend)
        if write_back:
            self.registers[base_register] = updated_base

    def _multiple_transfer(self, registers: list[int], start: int, load: bool) -> None:
        # Validate the whole RAM transaction before changing memory or registers.
        addresses = [(start + index * 4) & MASK32 for index in range(len(registers))]
        for address in addresses:
            self.memory.validate(address, 4, 4)
        if load:
            values = [self.memory.read32(address) for address in addresses]
            for register, value in zip(registers, values, strict=True):
                if register == 15:
                    self._write_pc(value, exchange=self.architecture == "armv5te")
                else:
                    self.registers[register] = value
        else:
            values = [self._read_register(register) for register in registers]
            for address, value in zip(addresses, values, strict=True):
                self.memory.write32(address, value)

    def _block_transfer(self, instruction: int) -> None:
        pre = bool(instruction & (1 << 24))
        up = bool(instruction & (1 << 23))
        write_back = bool(instruction & (1 << 21))
        load = bool(instruction & (1 << 20))
        base_register = (instruction >> 16) & 15
        registers = [i for i in range(16) if instruction & (1 << i)]
        if not registers or instruction & (1 << 22) or base_register == 15:
            raise UnsupportedInstruction("Empty/user-mode/PC-base block transfer")
        if write_back and base_register in registers:
            raise UnsupportedInstruction("Block write-back overlaps register list")
        if not load and 15 in registers:
            raise UnsupportedInstruction("Storing PC in a block is unsupported")
        base = self._read_register(base_register)
        size = len(registers) * 4
        start = base + (4 if pre else 0) if up else base - size + (0 if pre else 4)
        self._multiple_transfer(registers, start & MASK32, load)
        if write_back:
            self.registers[base_register] = (base + (size if up else -size)) & MASK32

    def _multiply(self, instruction: int) -> None:
        destination = (instruction >> 16) & 15
        accumulator = (instruction >> 12) & 15
        source = (instruction >> 8) & 15
        multiplier = instruction & 15
        accumulate = bool(instruction & (1 << 21))
        if 15 in (destination, source, multiplier) or (
            accumulate and accumulator == 15
        ):
            raise UnsupportedInstruction("Multiply involving PC is unsupported")
        if not accumulate and accumulator != 0:
            raise UnsupportedInstruction("Invalid MUL encoding")
        value = self._read_register(source) * self._read_register(multiplier)
        if accumulate:
            value += self._read_register(accumulator)
        value &= MASK32
        self.registers[destination] = value
        if instruction & (1 << 20):
            self._set_flags(value, self.c, self.v)

    def _execute_arm(self, instruction: int) -> None:
        if instruction & 0x0FFFFFF0 == 0x012FFF10:  # BX
            self._write_pc(self._read_register(instruction & 15), exchange=True)
        elif instruction & 0x0FFFFFF0 == 0x012FFF30:  # BLX register (ARM9)
            if self.architecture != "armv5te":
                raise UnsupportedInstruction("BLX requires ARMv5")
            target = self._read_register(instruction & 15)
            self.registers[14] = (self.pc + 4) & MASK32
            self._write_pc(target, exchange=True)
        elif instruction & 0x0FC000F0 == 0x00000090:
            self._multiply(instruction)
        elif instruction & 0x0E000090 == 0x00000090:
            self._single_data_transfer(instruction, halfword=True)
        elif (instruction >> 25) & 7 == 5:
            displacement = signed(instruction, 24) * 4
            if instruction & (1 << 24):
                self.registers[14] = (self.pc + 4) & MASK32
            self._next_pc = (self.pc + 8 + displacement) & MASK32
        elif (instruction >> 25) & 7 == 4:
            self._block_transfer(instruction)
        elif (instruction >> 26) & 3 == 1:
            self._single_data_transfer(instruction)
        elif (instruction >> 26) & 3 == 0:
            self._data_processing(instruction)
        else:
            raise UnsupportedInstruction(
                f"Unsupported ARM instruction {instruction:#010x}"
            )

    def step(self) -> StepResult:
        address = self.pc
        was_thumb = self.thumb
        self._next_pc = (address + (2 if was_thumb else 4)) & MASK32
        if was_thumb:
            from nds_lab.thumb import execute_thumb

            instruction = self.memory.read16(address)
            executed = execute_thumb(self, instruction)
        else:
            instruction = self.memory.read32(address)
            condition = instruction >> 28
            if condition == 15:
                raise UnsupportedInstruction(
                    "Unconditional ARMv5 encodings are unsupported"
                )
            executed = self._condition_passed(condition)
            if executed:
                self._execute_arm(instruction)
        self.registers[15] = self._next_pc
        return StepResult(
            address,
            instruction,
            executed,
            tuple(self.registers),
            (self.n, self.z, self.c, self.v),
            was_thumb,
        )
