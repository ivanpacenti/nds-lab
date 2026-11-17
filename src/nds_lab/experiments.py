"""Small original machine-code programs demonstrating each core milestone."""

from nds_lab.cpu import CPU
from nds_lab.demo import format_step
from nds_lab.memory import Memory
from nds_lab.nds import NDS, make_demo_rom


def _run(words: tuple[int, ...], *, trace: bool, thumb: bool = False) -> CPU:
    memory = Memory(4096)
    width = 2 if thumb else 4
    memory.load(0, b"".join(word.to_bytes(width, "little") for word in words))
    cpu = CPU(memory, thumb=thumb)
    cpu.registers[13] = 0x800
    for _ in range(100):
        step = cpu.step()
        if trace:
            print(format_step(step))
        if cpu.pc == len(words) * width:
            return cpu
    raise RuntimeError("Experiment exceeded its instruction budget")


def run_logic(trace: bool = False) -> CPU:
    cpu = _run(
        (
            0xE3A000AB,  # MOV r0, #0xAB
            0xE200100F,  # AND r1, r0, #15 -> low nibble 11
            0xE1A02220,  # MOV r2, r0, LSR #4 -> high nibble 10
            0xE3C0000F,  # BIC r0, r0, #15
            0xE3800005,  # ORR r0, r0, #5 -> 0xA5
            0xE220300F,  # EOR r3, r0, #15 -> 0xAA
            0xE1E04003,  # MVN r4, r3 -> 0xFFFFFF55
        ),
        trace=trace,
    )
    if cpu.registers[:5] != [0xA5, 11, 10, 0xAA, 0xFFFFFF55]:
        raise RuntimeError("Bitfield experiment failed")
    return cpu


def run_widths(trace: bool = False) -> CPU:
    cpu = _run(
        (
            0xE3A01C01,  # MOV r1, #0x100
            0xE3A000AB,  # MOV r0, #0xAB
            0xE5C10001,  # STRB r0, [r1, #1]
            0xE5D12001,  # LDRB r2, [r1, #1]
            0xE1D130D1,  # LDRSB r3, [r1, #1]
            0xE1A00400,  # MOV r0, r0, LSL #8 -> 0xAB00
            0xE1C100B2,  # STRH r0, [r1, #2]
            0xE1D140B2,  # LDRH r4, [r1, #2]
            0xE1D150F2,  # LDRSH r5, [r1, #2]
        ),
        trace=trace,
    )
    if cpu.registers[2:6] != [0xAB, 0xFFFFFFAB, 0xAB00, 0xFFFFAB00]:
        raise RuntimeError("Memory-width experiment failed")
    return cpu


def run_stack(trace: bool = False) -> CPU:
    cpu = _run(
        (
            0xE3A00007,  # 00: MOV r0, #7
            0xEB000000,  # 04: BL 0x0C
            0xEA000004,  # 08: B 0x20 (end)
            0xE92D4010,  # 0C: PUSH {r4, lr} = STMDB sp!, {r4, lr}
            0xE1A04000,  # 10: MOV r4, r0
            0xE2840005,  # 14: ADD r0, r4, #5
            0xE8BD4010,  # 18: POP {r4, lr} = LDMIA sp!, {r4, lr}
            0xE12FFF1E,  # 1C: BX lr
        ),
        trace=trace,
    )
    if cpu.registers[0] != 12 or cpu.registers[4] != 0 or cpu.registers[13] != 0x800:
        raise RuntimeError("Stack experiment failed")
    return cpu


def run_thumb(trace: bool = False) -> CPU:
    cpu = _run(
        (
            0x2007,  # 00: MOV r0, #7
            0xF000,  # 02: BL prefix
            0xF801,  # 04: BL suffix -> 0x08
            0xE004,  # 06: B 0x12 (end)
            0xB510,  # 08: PUSH {r4, lr}
            0x1C04,  # 0A: MOV r4, r0 (ADDS r4, r0, #0)
            0x3005,  # 0C: ADD r0, #5
            0xBC10,  # 0E: POP {r4}
            0xBD00,  # 10: POP {pc}
        ),
        trace=trace,
        thumb=True,
    )
    if cpu.registers[0] != 12 or cpu.registers[4] != 0 or cpu.registers[13] != 0x800:
        raise RuntimeError("Thumb experiment failed")
    return cpu


def run_nds(trace: bool = False) -> NDS:
    machine = NDS(make_demo_rom())
    # Explicit execution order for this experiment, with no timing claims.
    for processor, steps in (("arm9", 3), ("arm7", 4)):
        for _ in range(steps):
            step = machine.step(processor)
            if trace:
                print(f"{processor}: {format_step(step)}")
    if machine.main_ram.read32(0x02001004) != 12:
        raise RuntimeError("Two-CPU shared-memory experiment failed")
    return machine
