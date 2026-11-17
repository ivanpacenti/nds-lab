"""Run small ARM programs with optional instruction traces."""

import argparse

from nds_lab.cpu import CPU, StepResult
from nds_lab.memory import Memory

# Each entry is one ARM instruction, stored little-endian in memory.
SUM_PROGRAM = (
    0xE3A00000,  # 00: MOV r0, #0
    0xE3A01001,  # 04: MOV r1, #1
    0xE0800001,  # 08: ADD r0, r0, r1
    0xE2811001,  # 0C: ADD r1, r1, #1
    0xE351000B,  # 10: CMP r1, #11
    0x1AFFFFFB,  # 14: BNE 0x08 (offset relative to 0x14 + 8)
)


DATA_ADDRESS = 0x100
RESULT_ADDRESS = 0x140
MEMORY_VALUES = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
MEMORY_SUM_PROGRAM = (
    0xE3A00000,  # 00: MOV r0, #0
    0xE3A01C01,  # 04: MOV r1, #0x100
    0xE3A0200A,  # 08: MOV r2, #10
    0xE4913004,  # 0C: LDR r3, [r1], #4
    0xE0800003,  # 10: ADD r0, r0, r3
    0xE2522001,  # 14: SUBS r2, r2, #1
    0x1AFFFFFB,  # 18: BNE 0x0C
    0xE5810018,  # 1C: STR r0, [r1, #0x18] (r1 is now 0x128)
)


def format_step(step: StepResult) -> str:
    flags = "".join(
        name if enabled else "-"
        for name, enabled in zip("NZCV", step.flags, strict=True)
    )
    status = "exec" if step.executed else "skip"
    registers = " ".join(
        f"r{index}={value:08X}" for index, value in enumerate(step.registers)
    )
    return (
        f"{step.address:08X}  {step.instruction:08X}  {status}  "
        f"{registers}  NZCV={flags}"
    )


def _run_program(
    memory: Memory, words: tuple[int, ...], trace: bool, max_steps: int
) -> tuple[CPU, int]:
    program = b"".join(word.to_bytes(4, "little") for word in words)
    memory.load(0, program)
    cpu = CPU(memory)
    for steps in range(1, max_steps + 1):
        step = cpu.step()
        if trace:
            print(format_step(step))
        # The runner stops at the end of this known program. This is not a DS halt.
        if cpu.pc == len(program):
            return cpu, steps
    raise RuntimeError(f"Demo exceeded its {max_steps}-instruction budget")


def run_demo(trace: bool = False, max_steps: int = 100) -> tuple[CPU, int]:
    return _run_program(Memory(4096), SUM_PROGRAM, trace, max_steps)


def run_memory_demo(trace: bool = False, max_steps: int = 100) -> tuple[CPU, int]:
    memory = Memory(4096)
    for index, value in enumerate(MEMORY_VALUES):
        memory.write32(DATA_ADDRESS + index * 4, value)
    return _run_program(memory, MEMORY_SUM_PROGRAM, trace, max_steps)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--trace", action="store_true", help="Print state after each step"
    )
    parser.add_argument(
        "--demo", choices=("sum", "memory"), default="sum", help="Choose a demo"
    )
    args = parser.parse_args()
    if args.demo == "memory":
        cpu, steps = run_memory_demo(trace=args.trace)
        result = cpu.memory.read32(RESULT_ADDRESS)
        print(
            f"Memory sum = {result}, stored at {RESULT_ADDRESS:#010x} "
            f"({steps} instructions)"
        )
        if result != sum(MEMORY_VALUES):
            raise RuntimeError("Stored result differs from the expected sum")
        return
    cpu, steps = run_demo(trace=args.trace)
    print(f"Sum 1..10 = {cpu.registers[0]} ({steps} instructions)")
    if cpu.registers[0] != 55:
        raise RuntimeError("Demo result differs from the expected sum of 55")
