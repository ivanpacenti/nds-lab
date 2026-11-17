"""Execute actual ARM words for the sum 1 + ... + 10."""

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


def run_demo(trace: bool = False, max_steps: int = 100) -> tuple[CPU, int]:
    memory = Memory(4096)
    program = b"".join(word.to_bytes(4, "little") for word in SUM_PROGRAM)
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--trace", action="store_true", help="Print state after each step"
    )
    args = parser.parse_args()
    cpu, steps = run_demo(trace=args.trace)
    print(f"Sum 1..10 = {cpu.registers[0]} ({steps} instructions)")
    if cpu.registers[0] != 55:
        raise RuntimeError("Demo result differs from the expected sum of 55")
