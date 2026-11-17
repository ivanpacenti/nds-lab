import pytest

from nds_lab.memory import Memory, MemoryAccessError


def test_little_endian_and_widths():
    memory = Memory(16, base=0x02000000)
    memory.write32(0x02000000, 0x12345678)
    assert [memory.read8(0x02000000 + i) for i in range(4)] == [0x78, 0x56, 0x34, 0x12]
    assert memory.read16(0x02000000) == 0x5678
    assert memory.read32(0x02000000) == 0x12345678
    memory.write16(0x02000004, 0x12345)
    memory.write8(0x02000006, 0x1AB)
    assert memory.read16(0x02000004) == 0x2345
    assert memory.read8(0x02000006) == 0xAB
    memory.write32(0x02000008, -1)
    assert memory.read32(0x02000008) == 0xFFFFFFFF


@pytest.mark.parametrize("address", [-1, 16, 0xFFFFFFFF])
def test_out_of_bounds(address):
    memory = Memory(16)
    with pytest.raises(MemoryAccessError):
        memory.read8(address)


@pytest.mark.parametrize("method", ["read16", "read32"])
def test_alignment(method):
    with pytest.raises(MemoryAccessError):
        getattr(Memory(16), method)(1)


def test_failed_write_is_atomic():
    memory = Memory(8)
    memory.load(0, b"abcdefgh")
    for address, data in [(7, b"XY"), (-1, b"Z")]:
        with pytest.raises(MemoryAccessError):
            memory.load(address, data)
    with pytest.raises(MemoryAccessError):
        memory.write32(6, 0)
    assert bytes(memory.read8(i) for i in range(8)) == b"abcdefgh"


@pytest.mark.parametrize("size,base", [(0, 0), (-1, 0), (4, -1), (8, 0xFFFFFFFC)])
def test_invalid_region(size, base):
    with pytest.raises(ValueError):
        Memory(size, base)
