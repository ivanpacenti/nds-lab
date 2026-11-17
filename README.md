# nds-lab

A lab for building and understanding a Nintendo DS emulator, starting with
a small, readable ARM interpreter in Python.

## Getting started

Requires Python 3.12 or later and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/ivanpacenti/nds-lab.git
cd nds-lab
uv sync
uv run nds-lab
uv run nds-lab --trace
```

Expected output

```text
Sum 1..10 = 55 (42 instructions)
```

You can also run `uv run python -m nds_lab`.
In PyCharm, open the project folder and select `.venv/bin/python` as the
interpreter after running `uv sync`. Set a breakpoint in `CPU.step()` and
run the `nds_lab` module to step through each instruction.

## First experiment

The demo loads six real ARM instructions, manually encoded in `demo.py`.

```asm
    MOV r0, #0
    MOV r1, #1
loop:
    ADD r0, r0, r1
    ADD r1, r1, #1
    CMP r1, #11
    BNE loop
```

`r0` accumulates the sum, and `r1` holds the next number to add.
`CMP` updates the flags. When `r1` reaches 11, the Z flag becomes true and
`BNE` is skipped. The runner stops at the address immediately after the program.
This stopping point is a convention implemented by the demo runner.
The count of 42 includes the final skipped branch and measures visited
instructions. Hardware cycle counting is a future extension.

The trace shows the address and opcode, `exec` or `skip`, all registers after
the step, and the N/Z/C/V flags. A dash represents a cleared flag.

## Reading the code

- `src/nds_lab/memory.py` implements a little-endian memory region.
- `src/nds_lab/cpu.py` fetches, decodes, and executes one instruction per `step()`.
- `src/nds_lab/demo.py` contains the program and execution trace.
- `tests/` checks the complete program and instruction edge cases.

The value stored in `registers[15]` points to the next instruction to fetch.
When an instruction uses PC as an operand, it receives the current instruction
address plus 8, as specified for these instructions in ARM state. B/BL use the
same reference point. BL stores the return address in r14.

## Implemented subset

- 32-bit registers and N, Z, C, V flags.
- MOV, ADD, SUB, CMP with rotated ARM immediates or unshifted registers.
- Flag-setting variants and conditions from EQ through AL.
- B and BL with positive or negative offsets.
- 8-bit, 16-bit, and 32-bit memory reads and writes through the Python API.

Unsupported instructions raise `UnsupportedInstruction` when their condition
passes. Decoding errors preserve registers and flags. Failed conditions advance
PC without executing the instruction body.

This version is a partial educational interpreter. Future work includes Thumb,
CPU load/store instructions, register shifts, arithmetic writes to PC,
privileged modes, exceptions, and complete CPSR/SPSR support.
Memory accesses require alignment for 16-bit and 32-bit operations. Hardware
behavior for unaligned accesses, the DS memory map, simultaneous ARM7/ARM9
execution, timing, graphics, audio, peripherals, `.nds` loading, and iOS
integration are later milestones. Running DS games requires further development.

## Checks

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

For the next exercise, change the CMP immediate limit from 11 to 6 and try
to predict the final sum and instruction count before running the demo.
The final check in `main()` expects 55, so update it alongside the program.
The next core extension will be LDR/STR to read and write memory directly
from ARM instructions.

## Technical reference

Decoding follows the 32-bit ARM instruction format described in Arm's
documentation. The reference helps verify instruction semantics. This project's
code is written specifically for the lab.

- [Arm instruction set, data processing](https://documentation-service.arm.com/static/5ed11a2dca06a95ce53f8f99)
