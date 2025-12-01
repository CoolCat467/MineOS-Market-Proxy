from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

import pytest

from market_proxy.reader import (
    BiReader,
    BlobField,
    IntegerField,
    combine_end,
    unhandled_types,
)
from market_proxy.result import Result

if TYPE_CHECKING:
    from collections.abc import Iterable


def test_unhandled_types_is_empty() -> None:
    # All registered types must be covered by Field alias
    assert not unhandled_types()


@pytest.mark.parametrize(
    ("items", "final", "expected"),
    [
        ([], "and", ""),  # no items
        (["a"], "and", "a"),  # single
        (["a", "b"], "or", "a or b"),  # two items, custom final
        (["x", "y", "z"], "and", "x, y, and z"),  # >2 items
        ([1, 2, 3], "or", "1, 2, or 3"),
    ],
)
def test_combine_end(
    items: Iterable[object],
    final: str,
    expected: str,
) -> None:
    assert combine_end(items, final) == expected


def make_reader(data: bytes) -> BiReader:
    return BiReader(BytesIO(data))


def test_read_and_expect_success_and_failure() -> None:
    rd = make_reader(b"ABCDE")
    # read exact bytes
    assert rd.read(2) == b"AB"
    # expect correct
    ok = rd.expect(b"CD")
    assert isinstance(ok, Result)
    assert ok.success is True
    assert ok.value == b"CD"
    # expect incorrect
    fail = rd.expect(b"XY")
    assert fail.success is False
    assert fail.value == b"E"  # because only 'E' remains
    # reading past end returns b''
    assert rd.read(10) == b""


def test_expect_fail_raises_on_mismatch() -> None:
    # mismatch at first try
    rd = make_reader(b"foo")
    with pytest.raises(ValueError, match="Expected 'bar'"):
        rd.expect_fail(b"bar")
    # correct match does not raise
    rd2 = make_reader(b"baz")
    out = rd2.expect_fail(b"baz")
    assert out == b"baz"


def test_read_until_stops_on_byte_and_eof() -> None:
    # stops at newline
    rd = make_reader(b"hello\nworld")
    res = rd.read_until(b"\n")
    assert res.success is True
    assert res.unwrap() == bytearray(b"hello")
    # when EOF before terminator
    rd2 = make_reader(b"abc")
    res2 = rd2.read_until(b"\n")
    assert res2.success is False
    assert res2.unwrap() == bytearray(b"abc")


def test_read_name_success_and_eof_failure() -> None:
    rd = make_reader(b"name rest")
    name = rd.read_name()
    assert name == b"name"
    # EOF without space
    rd2 = make_reader(b"noname")
    with pytest.raises(ValueError, match="Expected b' ',"):
        rd2.read_name()


def test_integer_field_to_and_from_stream() -> None:
    # construct an IntegerField, serialize, then parse via BiReader
    field = IntegerField(name=b"count", value=42)
    serialized = field.to_stream()
    # serialized must match pattern ":i name value\n"
    assert serialized.startswith(b":i count 42\n")

    reader = make_reader(serialized)
    # skip colon
    assert reader.expect(b":").success
    # read 'i', lookup class
    assert reader.read(1) == b"i"
    reader.expect_fail(b" ")
    name = reader.read_name()
    parsed = IntegerField.from_reader(name, reader)
    assert parsed == field


def test_blob_field_to_and_from_stream() -> None:
    content = b"jerald"
    field = BlobField(name=b"blob", content=content)
    serialized = field.to_stream()
    # header line
    header, rest = serialized.split(b"\n", 1)
    assert header == b":b blob " + str(len(content)).encode()
    # body must contain content + newline
    assert rest == content + b"\n"

    # now parse
    reader = make_reader(serialized)
    # skip colon
    assert reader.expect(b":").success
    # type byte
    assert reader.read(1) == b"b"
    reader.expect_fail(b" ")
    name = reader.read_name()
    parsed = BlobField.from_reader(name, reader)
    assert parsed == field


def test_read_stream_iterates_multiple_fields() -> None:
    # build two integer fields
    f1 = IntegerField(name=b"a", value=1).to_stream()
    f2 = IntegerField(name=b"b", value=2).to_stream()
    stream_bytes = f1 + f2
    reader = make_reader(stream_bytes)
    collected = list(iter(reader))
    assert collected == [IntegerField(b"a", 1), IntegerField(b"b", 2)]


def test_read_stream_unknown_type_raises() -> None:
    # craft ":z name\n" where 'z' is unregistered
    data = b":z foo\n"
    reader = make_reader(data)
    with pytest.raises(ValueError, match=r"Expected .* but got 'z'"):
        list(reader)


def test_context_manager_no_exceptions() -> None:
    stream = BytesIO(b"")
    with BiReader(stream) as br:
        # nothing to iterate
        assert list(br) == []
    # exiting again is no-op
    br.__exit__(None, None, None)
