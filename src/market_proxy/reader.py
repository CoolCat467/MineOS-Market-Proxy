"""Bi-Reader - Tsoding bi format reader.

See https://github.com/tsoding/bi-format for more details.
"""

# Programmed by CoolCat467

from __future__ import annotations

# Bi-Reader - Tsoding bi format reader.
# Copyright (C) 2024-2025  CoolCat467
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

__title__ = "Bi-Reader"
__author__ = "CoolCat467"
__version__ = "0.1.0"
__license__ = "GNU General Public License Version 3"


from io import BytesIO
from typing import (
    IO,
    TYPE_CHECKING,
    Final,
    NamedTuple,
    NoReturn,
    TypeAlias,
    TypeVar,
)

from market_proxy.result import Result

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable, Iterator
    from types import TracebackType

    from typing_extensions import Self

F = TypeVar("F", bound="type[Field]")


FIELD_TYPES: Final[dict[bytes, type[Field]]] = {}


def register_type(identifier: bytes) -> Callable[[F], F]:
    """Register field type."""

    def register_type_class_decorator(cls: F) -> F:
        assert identifier not in FIELD_TYPES
        FIELD_TYPES[identifier] = cls
        return cls

    return register_type_class_decorator


def type_bytes(instance: Field) -> bytes:
    """Return type bytes for field instance."""
    reverse = {v: k for k, v in FIELD_TYPES.items()}
    return reverse[type(instance)]


@register_type(b"i")
class IntegerField(NamedTuple):
    """Integer Field Object."""

    name: bytes
    value: int

    @classmethod
    def from_reader(
        cls: type[Self],
        name: bytes,
        reader: BiReader,
    ) -> Self:
        """Return instance of this class from stream and name."""
        value_result = reader.read_until(b"\n")
        if not value_result:
            reader.fail("Expected newline, reached EOF.")
        return cls(name, int(value_result.unwrap()))

    def to_stream(self) -> bytes:
        """Serialize this object to bytes for writing to stream."""
        fill = b" ".join(
            (type_bytes(self), self.name, str(self.value).encode("ascii")),
        )
        return b":" + fill + b"\n"


@register_type(b"b")
class BlobField(NamedTuple):
    """Binary Blob Field Object."""

    name: bytes
    content: bytes

    @classmethod
    def from_reader(
        cls: type[Self],
        name: bytes,
        reader: BiReader,
    ) -> Self:
        """Return instance of this class from stream and name."""
        size_result = reader.read_until(b"\n")
        if not size_result:
            reader.fail("Expected newline, reached EOF.")
        size = int(size_result.unwrap())
        read_content = reader.read(size)
        reader.expect_fail(b"\n")
        return cls(name, read_content)

    def to_stream(self) -> bytes:
        """Serialize this object to bytes for writing to stream."""
        fill = b" ".join(
            (
                type_bytes(self),
                self.name,
                str(len(self.content)).encode("ascii"),
            ),
        )
        return b":" + fill + b"\n" + self.content + b"\n"


Field: TypeAlias = IntegerField | BlobField


def unhandled_types() -> set[type]:
    """Return set of types registered with `register_type` but missing from Field union."""
    return set(FIELD_TYPES.values()) - set(Field.__args__)


def combine_end(data: Iterable[object], final: str = "and") -> str:
    """Join values of text, and have final with the last one properly."""
    as_list = list(map(str, data))
    if len(as_list) >= 2:
        as_list[-1] = f"{final} {as_list[-1]}"
    if len(as_list) > 2:
        return ", ".join(as_list)
    return " ".join(as_list)


assert not unhandled_types(), (
    f"Registered type(s) missing from `Field` alias: {combine_end(unhandled_types())}"
)


class BiReader(NamedTuple):
    """Bi Format Reader."""

    stream: IO[bytes]

    def read(self, count: int) -> bytes:
        """Return count bytes read from stream."""
        return self.stream.read(count)

    def expect(self, chars: bytes) -> Result[bytes]:
        """Return read chars. Success if matches expected."""
        value = self.read(len(chars))
        return Result(value == chars, value)

    def fail(self, text: str) -> NoReturn:
        """Raise ValueError."""
        extra = ""
        if hasattr(self.stream, "name"):
            extra = f" while reading from {self.stream.name!r}"
        raise ValueError(f"{text}{extra}")

    def expect_fail(self, chars: bytes) -> bytes:
        """Return bytes that match chars or fail."""
        result = self.expect(chars)
        if not result:
            got = result.unwrap().decode("utf-8")
            self.fail(f"Expected {chars.decode('utf-8')!r}, but got {got!r}")
        return result.unwrap()

    def read_until(self, expect_char: bytes) -> Result[bytearray]:
        """Read until reached expect_char or EOF. Failed if EOF."""
        read = bytearray()
        char = b""
        while self.stream.readable():
            char = self.read(1)
            if not char or char == expect_char:
                break
            read.append(char[0])
        return Result(char == expect_char, read)

    def read_name(self) -> bytes:
        """Read until space or EOF. If EOF fail. Return name."""
        name_result = self.read_until(b" ")
        if not name_result:
            self.fail("Expected b' ', but reached EOF.")
        return bytes(name_result.unwrap())

    def read_stream(self) -> Generator[Field, None, None]:
        """Yield fields or raise ValueError."""
        while self.stream.readable():
            start_result = self.expect(b":")
            if not start_result:
                if not start_result.unwrap():
                    break
                got = start_result.unwrap().decode("utf-8")
                self.fail(f"Expected b':', but got {got}")
            field_type_header = self.read(1)
            field_type = FIELD_TYPES.get(field_type_header)
            if field_type is None:
                self.fail(
                    f"Expected {combine_end(FIELD_TYPES, 'or')}, but got {field_type_header.decode('utf-8')!r}",
                )
            self.expect_fail(b" ")
            name = self.read_name()
            yield field_type.from_reader(name, self)

    def __iter__(self) -> Iterator[Field]:  # type: ignore[override]
        """Yield fields from stream."""
        return self.read_stream()

    def __enter__(self) -> Self:
        """Implement context manager enter."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Implement context manager exit."""
        return


def run() -> None:
    """Run program."""
    data = b""":i count 3
:b hello 12
Hello, World
:b foo 7
Foo bar
:b test 163
Test test test

You can have new lines in here.
You can actually store binary data in here.
You can nest another bi file in here, thus
making the format Tree-like.
:b Person/json 69
{
    "Name": "John Doe",
    "Age": 69,
    "Occupation": "Webdev"
}
"""
    with BytesIO(data) as fp:
        with BiReader(fp) as reader:
            for item in reader:
                print(item)


if __name__ == "__main__":
    print(f"{__title__} v{__version__}\nProgrammed by {__author__}.\n")
    run()
