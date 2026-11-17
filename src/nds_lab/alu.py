"""32-bit arithmetic and the ARM barrel shifter shared by ARM and Thumb."""

MASK32 = 0xFFFFFFFF
SIGN_BIT = 1 << 31


def signed(value: int, bits: int) -> int:
    value &= (1 << bits) - 1
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def add_with_carry(
    left: int, right: int, carry: bool = False
) -> tuple[int, bool, bool]:
    left &= MASK32
    right &= MASK32
    total = left + right + int(carry)
    result = total & MASK32
    signed_total = signed(left, 32) + signed(right, 32) + int(carry)
    return result, total > MASK32, not -(1 << 31) <= signed_total < (1 << 31)


def shift(
    value: int, kind: int, amount: int, carry: bool, *, immediate: bool = False
) -> tuple[int, bool]:
    """Apply LSL/LSR/ASR/ROR (0..3), including immediate zero encodings."""
    value &= MASK32
    if immediate and amount == 0:
        if kind in (1, 2):
            amount = 32
        elif kind == 3:  # RRX
            return (int(carry) << 31) | (value >> 1), bool(value & 1)
    if amount == 0:
        return value, carry
    if kind == 0:
        if amount > 32:
            return 0, False
        return (value << amount) & MASK32, bool((value >> (32 - amount)) & 1)
    if kind == 1:
        if amount > 32:
            return 0, False
        return value >> amount, bool((value >> (amount - 1)) & 1)
    if kind == 2:
        amount = min(amount, 32)
        return (signed(value, 32) >> amount) & MASK32, bool((value >> (amount - 1)) & 1)
    if kind == 3:
        rotation = amount % 32
        result = ((value >> rotation) | (value << (32 - rotation))) & MASK32
        return result, bool(result & SIGN_BIT)
    raise ValueError("Unknown shift kind")
