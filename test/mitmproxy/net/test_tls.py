import struct
from collections import namedtuple
from enum import Enum
from typing import List


class ExtensionType(Enum):
    """https://www.iana.org/assignments/tls-extensiontype-values/tls-extensiontype-values.xhtml"""
    server_name = 0
    application_layer_protocol_negotiation = 16


def _verify_list(data: bytes) -> bytes:
    """
    TLS extensions can be parsed without additional information, so if the extension data is a list,
    it will be prefixed with the list length. This is kind of redundant as the extension data length
    is already specified. Here, we just check that both match and return the reduced stuff.
    """
    list_len, = struct.unpack_from("!H", data, 0)
    if list_len + 2 != len(data):
        raise ValueError("Expected {} bytes, but got {}".format(list_len + 2, len(data)))
    return data[2:]


def parse_alpn(data: bytes) -> List[bytes]:
    data = _verify_list(data)

    entries = []
    while data:
        cut = struct.unpack_from("!B", data, 0)[0] + 1
        entries.append(data[1:cut])
        data = data[cut:]
    return entries


def parse_sni(data: bytes) -> str:
    data = _verify_list(data)

    name_type, host_name_len = struct.unpack_from("!BH", data, 0)
    if name_type != 0 or host_name_len + 3 != len(data):
        raise ValueError("Unexpected SNI: {}".format(repr(data)))

    return data[3:].decode("ascii")


class ClientHello(namedtuple("ClientHello", ["client_version", "alpn", "sni"])):
    __slots__ = ()

    @classmethod
    def parse(cls, data: bytes):
        client_version = data[:2]
        alpn = None
        sni = None

        i = 34
        legacy_session_id_len, = struct.unpack_from("!B", data, i)
        i += legacy_session_id_len + 1
        cipher_suites_len, = struct.unpack_from("!H", data, i)
        i += cipher_suites_len + 2
        legacy_compression_methods_len, = struct.unpack_from("!B", data, i)
        i += legacy_compression_methods_len + 1
        if i == len(data):
            extensions_len = 0
        else:
            extensions_len, = struct.unpack_from("!H", data, i)
        i += 2
        end = i + extensions_len
        while i < end:
            extension_type, extension_len = struct.unpack_from("!HH", data, i)
            i += 4
            extension_data = data[i:i + extension_len]
            if extension_type == ExtensionType.server_name.value:
                if sni:
                    raise ValueError("ClientHello contained two SNI extensions.")
                sni = parse_sni(extension_data)

            if extension_type == ExtensionType.application_layer_protocol_negotiation.value:
                if alpn:
                    raise ValueError("ClientHello contained two ALPN extensions.")
                alpn = parse_alpn(extension_data)
            i += extension_len

        return cls(client_version, alpn, sni)


def test_parse_alpn():
    data = bytes.fromhex("000c02683208687474702f312e31")
    assert parse_alpn(data) == [b"h2", b"http/1.1"]


def test_parse_sni():
    data = bytes.fromhex("000e00000b6578616d706c652e636f6d")
    assert parse_sni(data) == "example.com"


def test_parse_chrome():
    """
    Test if we properly parse a ClientHello sent by Chrome 54.
    """
    data = bytes.fromhex(
        "03033b70638d2523e1cba15f8364868295305e9c52aceabda4b5147210abc783e6e1000022c02bc02fc02cc030"
        "cca9cca8cc14cc13c009c013c00ac014009c009d002f0035000a0100006cff0100010000000010000e00000b65"
        "78616d706c652e636f6d0017000000230000000d00120010060106030501050304010403020102030005000501"
        "00000000001200000010000e000c02683208687474702f312e3175500000000b00020100000a00080006001d00"
        "170018"
    )
    c = ClientHello.parse(data)
    assert c.client_version == b'\x03\x03'
    assert c.alpn == [b"h2", b"http/1.1"]
    assert c.sni == "example.com"


def test_parse_no_extensions():
    data = bytes.fromhex(
        "03015658a756ab2c2bff55f636814deac086b7ca56b65058c7893ffc6074f5245f70205658a75475103a152637"
        "78e1bb6d22e8bbd5b6b0a3a59760ad354e91ba20d353001a0035002f000a000500040009000300060008006000"
        "61006200640100"
    )
    c = ClientHello.parse(data)
    assert c.client_version == b'\x03\x01'
    assert c.alpn is None
    assert c.sni is None
