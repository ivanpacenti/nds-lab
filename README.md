# nds-lab

A lab for building and understanding a Nintendo DS emulator in readable Python.
The current milestone executes ARM and Thumb programs, performs RAM transfers,
and directly loads ARM9/ARM7 sections from original-DS cartridge images.

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
In PyCharm, open the project and select `.venv/bin/python` after `uv sync`.
Run the `nds_lab` module with the arguments below and set a breakpoint in
`CPU.step()` to follow execution. Source comments and documentation use English.

## Experiments

Each experiment uses original, hand-encoded instructions with an explicit
instruction budget and checks its result. The instruction count includes
conditionally skipped instructions. Hardware cycle timing is future work.

| Command | What it demonstrates | Expected result |
| --- | --- | --- |
| `uv run nds-lab --demo sum` | ARM arithmetic, CMP and conditional branches | 55 in 42 instructions |
| `uv run nds-lab --demo memory` | LDR reads ten words and STR writes their sum | 55 at `0x140`, 44 instructions |
| `uv run nds-lab --demo logic` | Extract, replace and invert bitfields | r0 = `0xA5` |
| `uv run nds-lab --demo widths` | Byte/halfword stores and signed/unsigned loads | r0 = `0xAB00` |
| `uv run nds-lab --demo stack` | ARM BL, PUSH/POP aliases and BX return | r0 = 12, restored r4 and SP |
| `uv run nds-lab --demo thumb` | Thumb BL, stack and return through PC | r0 = 12, restored r4 and SP |
| `uv run nds-lab --demo nds` | Header loading and two CPUs sharing main RAM | 12 at `0x02001004` |

Append `--trace` to any command to see the instruction address, opcode, execution
status, ARM/THUMB state, all registers after each step, and N/Z/C/V flags.
The state label describes the instruction that was just executed. A dash in the
flag display means that flag is clear. Numbers in the register trace are hexadecimal.

### First program

```asm
    MOV r0, #0
    MOV r1, #1
loop:
    ADD r0, r0, r1
    ADD r1, r1, #1
    CMP r1, #11
    BNE loop
```

r0 accumulates the sum. CMP sets Z when r1 reaches 11, so BNE is skipped.
The demo runner stops when PC reaches the address after the program.
Change the limit to 6, predict the result, then update the expected result in
`main()` alongside the program.

### Reading and writing RAM

The memory demo places words 1 through 10 at `0x100` through `0x124`.

```asm
    MOV r0, #0
    MOV r1, #0x100
    MOV r2, #10
loop:
    LDR r3, [r1], #4
    ADD r0, r0, r3
    SUBS r2, r2, #1
    BNE loop
    STR r0, [r1, #0x18]
```

The LDR reads at r1 and advances r1 by four bytes. After ten iterations, r1
contains `0x128`; STR stores the sum at `0x140`. Transfers preserve the flags.

| Addressing form | Transfer address | Base after success |
| --- | --- | --- |
| `[r1, #4]` | Original r1 + 4 | Original r1 |
| `[r1, #4]!` | Original r1 + 4 | Original r1 + 4 |
| `[r1], #4` | Original r1 | Original r1 + 4 |

Offsets can subtract, and ordinary LDR/STR offsets can use a shifted register.
LDRB/LDRH zero-extend. LDRSB/LDRSH sign-extend, so byte `0xAB` becomes
`0xFFFFFFAB` with LDRSB. STRB/STRH store the low 8/16 bits.
Put a breakpoint in `CPU._single_data_transfer()` to follow the effective address.

### Functions and stack

The ARM stack demo calls a function with BL. The function saves r4 and LR with
`STMDB sp!, {r4, lr}` (PUSH), computes 7 + 5, restores the saved registers with
`LDMIA sp!, {r4, lr}` (POP), and returns using `BX lr`.
The Thumb demo performs the equivalent call with Thumb PUSH and POP instructions.
Its BL occupies two halfwords, each executed by a separate `step()`.
The experiment runner initializes SP to `0x800`; bare CPU instances start with
zeroed registers except PC.

## Supported instruction families

| Area | Implemented |
| --- | --- |
| ARM ALU | AND, EOR, SUB, RSB, ADD, ADC, SBC, RSC, TST, TEQ, CMP, CMN, ORR, MOV, BIC, MVN |
| ARM shifter | Immediate and register LSL/LSR/ASR/ROR, RRX, rotated immediates, carry edge cases |
| ARM multiply | MUL, MLA, optional N/Z updates |
| ARM transfers | LDR/STR, LDRB/STRB, LDRH/STRH, LDRSB/LDRSH, immediate and register offsets |
| ARM multiple transfers | LDM/STM IA, IB, DA, DB, optional write-back, PUSH/POP aliases |
| ARM control flow | Conditions EQ through AL, B, BL, BX, ARMv5 BLX register, ordinary ALU writes to PC, LDR/LDM to PC |
| Thumb ALU | Immediate/register arithmetic, logical operations, shifts, MUL, NEG, high-register MOV/ADD/CMP |
| Thumb memory | Word/byte/halfword transfers, signed loads, PC/SP-relative addressing, LDMIA/STMIA, PUSH/POP |
| Thumb control flow | Conditional/unconditional branches, two-halfword BL, BX, ARMv5 BLX register |

`registers[15]` stores the next fetch address. Operand reads see current address
plus 8 in ARM state and plus 4 in Thumb state. ARM register-controlled shifts
read Rm=PC as current address plus 12. Literal loads align the Thumb PC base.
BX selects ARM/Thumb from target bit zero. ARMv4T loads to PC retain the current
instruction state; ARMv5TE loads to PC use bit zero to select the state.
The `architecture` option selects these implemented differences only; further
ARMv5TE features remain to be implemented.

Operations on PC with the S bit, privileged register transfers, exception
returns, empty multiple-transfer lists, ARM block write-back with the base in
the list, and stores of PC are rejected. Thumb LDM with the base in the list
keeps the loaded base value; Thumb STM with the base in its list is rejected.
Unprivileged LDRT/STRT, SWI, long multiplies, coprocessor instructions, ARMv5
BLX immediate, Thumb BLX immediate, and DSP extensions are future work.

The RAM model requires halfword/word alignment. Errors preserve architectural
registers, flags, and memory. Block transfers prevalidate every address before
committing any access. These are laboratory error semantics; implementing
hardware data-abort exceptions and unaligned CPU behavior is future work.

## Direct-loading a DS image

```bash
uv run nds-lab --rom path/to/experiment.nds --cpu arm9 --steps 100 --trace
uv run nds-lab --rom path/to/experiment.nds --cpu both --steps 100 --trace
```

The loader reads the standard ARM9 and ARM7 descriptors at header offsets
`0x20` and `0x30`. Each descriptor provides ROM offset, entry point, destination
RAM address and binary size. It validates section bounds, entry alignment,
destination mappings and RAM overlap before copying either binary.
A set entry bit zero selects Thumb for direct-load experiments.

| Region | Address range | Access |
| --- | --- | --- |
| Main RAM, 4 MiB | `0x02000000`–`0x023FFFFF` | ARM9 and ARM7 share the same bytes |
| Shared WRAM, 32 KiB | `0x03000000`–`0x03007FFF` | Fixed allocation to ARM7 |
| ARM7 WRAM, 64 KiB | `0x03800000`–`0x0380FFFF` | ARM7 only |

The fixed WRAM allocation corresponds to a WRAMCNT=3-like setup. Dynamic
WRAMCNT switching, mirrors, TCM, BIOS and all MMIO regions remain unimplemented.
Unmapped accesses fail explicitly. ARM9 uses the implemented ARMv5TE behaviors;
ARM7 uses ARMv4T behaviors. CPU register sets are independent.

`--cpu both` alternates one instruction from each CPU for a total of `--steps`
instructions. This is a bounded debugging policy. Clock ratios, instruction
latency and synchronization require a future scheduler. On an unsupported
instruction or memory access, the CLI reports the CPU and PC and exits with an
error. Successful budget exhaustion simply ends the debugging run.

The `nds` demo creates a synthetic original container entirely in memory.
It executes three ARM9 instructions followed by four ARM7 instructions, allowing
ARM7 to read ARM9's value 7 and store 12. Its header omits logo/checksum/firmware
boot setup, so the fixture is intended for this direct-load runner. The loader
currently validates structural bounds rather than CRCs or authenticity.

Commercial-game execution requires substantial further work, including complete
instruction coverage, BIOS/firmware startup, interrupts, timers, DMA, IPC,
cartridge access, graphics, audio, input, save hardware and accurate scheduling.
iOS integration is a later milestone.

## Code map

- `alu.py` handles arithmetic flags and the shared barrel shifter.
- `cpu.py` implements ARM decoding, CPU state and shared transfer operations.
- `thumb.py` decodes Thumb instructions using the same CPU operations.
- `memory.py` provides bounded little-endian RAM and the CPU memory interface.
- `nds.py` provides the RAM bus, header loader and two CPU instances.
- `demo.py` provides the CLI and original sum demos.
- `experiments.py` contains the bitfield, width, stack, Thumb and DS programs.
- `tests/` contains instruction, boundary, loader and CLI regression tests.

## Checks

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Technical references

- [Arm instruction set reference](https://documentation-service.arm.com/static/5ed11a2dca06a95ce53f8f99)
- [ARM7TDMI technical reference manual](https://documentation-service.arm.com/static/5f4786a179ff4c392c0ff819)
- [GBATEK DS memory and cartridge documentation](https://mgba-emu.github.io/gbatek/)
