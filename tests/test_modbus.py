import asyncio
import struct

from onecta_modbus.modbus import GATEWAY_TARGET_FAILED, ModbusError, start_server


class FakeHandler:
    def __init__(self):
        self.writes = []

    def read(self, unit, table, address, count):
        if unit != 1:
            raise ModbusError(GATEWAY_TARGET_FAILED)
        base = 1000 if table == "holding" else 2000
        return [base + address + i for i in range(count)]

    def write(self, unit, address, words):
        self.writes.append((unit, address, words))


async def roundtrip(port, unit, pdu, transaction=7):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(struct.pack(">HHHB", transaction, 0, len(pdu) + 1, unit) + pdu)
    await writer.drain()
    header = await reader.readexactly(7)
    tid, protocol, length, resp_unit = struct.unpack(">HHHB", header)
    body = await reader.readexactly(length - 1)
    writer.close()
    assert (tid, protocol, resp_unit) == (transaction, 0, unit)
    return body


def run(coro):
    return asyncio.run(coro)


async def with_server(test):
    handler = FakeHandler()
    server = await start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        return await test(handler, port)
    finally:
        server.close()
        await server.wait_closed()


def test_read_input_and_holding():
    async def test(handler, port):
        body = await roundtrip(port, 1, struct.pack(">BHH", 4, 49, 2))
        assert body == struct.pack(">BBHH", 4, 4, 2049, 2050)
        body = await roundtrip(port, 1, struct.pack(">BHH", 3, 5, 1))
        assert body == struct.pack(">BBH", 3, 2, 1005)
    run(with_server(test))


def test_write_single_and_multiple():
    async def test(handler, port):
        pdu = struct.pack(">BHH", 6, 100, 205)
        assert await roundtrip(port, 1, pdu) == pdu
        body = await roundtrip(port, 1, struct.pack(">BHHBHH", 16, 3, 2, 4, 1, 0xFFFE))
        assert body == struct.pack(">BHH", 16, 3, 2)
        assert handler.writes == [(1, 100, [205]), (1, 3, [1, 0xFFFE])]
    run(with_server(test))


def test_exceptions():
    async def test(handler, port):
        assert await roundtrip(port, 9, struct.pack(">BHH", 4, 0, 1)) == bytes([0x84, GATEWAY_TARGET_FAILED])
        assert await roundtrip(port, 1, struct.pack(">BHH", 1, 0, 1)) == bytes([0x81, 0x01])
        assert await roundtrip(port, 1, struct.pack(">BHH", 3, 0, 200)) == bytes([0x83, 0x03])
    run(with_server(test))


def test_several_requests_on_one_connection():
    async def test(handler, port):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        for tid in (1, 2, 3):
            pdu = struct.pack(">BHH", 4, tid, 1)
            writer.write(struct.pack(">HHHB", tid, 0, len(pdu) + 1, 1) + pdu)
        await writer.drain()
        for tid in (1, 2, 3):
            header = await reader.readexactly(7)
            assert struct.unpack(">H", header[:2])[0] == tid
            await reader.readexactly(struct.unpack(">H", header[4:6])[0] - 1)
        writer.close()
    run(with_server(test))
