"""Market Proxy - MineOS App Market Proxy Server.

Copyright (C) 2024-2025  CoolCat467

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

from __future__ import annotations

__title__ = "MineOS Market Proxy"
__author__ = "CoolCat467"
__license__ = "GNU General Public License Version 3"
__version__ = "1.0.0"


import functools
import socket
import sys
import time
import traceback
from collections import ChainMap
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from os import getenv, makedirs, path
from typing import TYPE_CHECKING, Any, Final, TypeVar, cast

import httpx
import trio
from hypercorn.config import Config
from hypercorn.trio import serve
from quart import request
from quart.templating import stream_template
from quart_trio import QuartTrio
from werkzeug.exceptions import HTTPException

if sys.version_info < (3, 11):
    import tomli as tomllib
    from exceptiongroup import BaseExceptionGroup
else:
    import tomllib

from market_proxy import reader

if TYPE_CHECKING:
    from typing_extensions import ParamSpec

    PS = ParamSpec("PS")

HOME: Final = trio.Path(getenv("HOME", path.expanduser("~")))
XDG_DATA_HOME: Final = trio.Path(
    getenv("XDG_DATA_HOME", HOME / ".local" / "share"),
)
XDG_CONFIG_HOME: Final = trio.Path(getenv("XDG_CONFIG_HOME", HOME / ".config"))

FILE_TITLE: Final = __title__.lower().replace(" ", "-").replace("-", "_")
CONFIG_PATH: Final = XDG_CONFIG_HOME / FILE_TITLE
DATA_PATH: Final = XDG_DATA_HOME / FILE_TITLE
MAIN_CONFIG: Final = CONFIG_PATH / "config.toml"

HOST: Final = "http://mineos.buttex.ru/MineOSAPI/2.04"

AGENT: Final = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/64.0.3282.119 Safari/537.36"
)

T = TypeVar("T")


def combine_end(data: Iterable[str], final: str = "and") -> str:
    """Return comma separated string of list of strings with last item phrased properly."""
    data = list(data)
    if len(data) >= 2:
        data[-1] = f"{final} {data[-1]}"
    if len(data) > 2:
        return ", ".join(data)
    return " ".join(data)


async def send_error(
    page_title: str,
    error_body: str,
    return_link: str | None = None,
) -> AsyncIterator[str]:
    """Stream error page."""
    return await stream_template(
        "error_page.html.jinja",
        page_title=page_title,
        error_body=error_body,
        return_link=return_link,
    )


async def get_exception_page(
    code: int,
    name: str,
    desc: str,
    return_link: str | None = None,
) -> tuple[AsyncIterator[str], int]:
    """Return Response for exception."""
    resp_body = await send_error(
        page_title=f"{code} {name}",
        error_body=desc,
        return_link=return_link,
    )
    return (resp_body, code)


def pretty_exception_name(exc: BaseException) -> str:
    """Make exception into pretty text (split by spaces)."""
    exc_str, reason = repr(exc).split("(", 1)
    reason = reason[1:-2]
    words = []
    last = 0
    for idx, char in enumerate(exc_str):
        if char.islower():
            continue
        word = exc_str[last:idx]
        if not word:
            continue
        words.append(word)
        last = idx
    words.append(exc_str[last:])
    error = " ".join(w for w in words if w not in {"Error", "Exception"})
    return f"{error} ({reason})"


def pretty_exception(
    function: Callable[PS, Awaitable[T]],
) -> Callable[PS, Awaitable[T | tuple[AsyncIterator[str], int]]]:
    """Make exception pages pretty."""

    @functools.wraps(function)
    async def wrapper(  # type: ignore[misc]
        *args: PS.args,
        **kwargs: PS.kwargs,
    ) -> T | tuple[AsyncIterator[str], int]:
        code = 500
        name = "Exception"
        desc = (
            "The server encountered an internal error and "
            + "was unable to complete your request. "
            + "Either the server is overloaded or there is an error "
            + "in the application."
        )
        try:
            return await function(*args, **kwargs)
        except Exception as exception:
            # traceback.print_exception changed in 3.10
            traceback.print_exception(exception)

            if isinstance(exception, HTTPException):
                code = exception.code or code
                desc = exception.description or desc
                name = exception.name or name
            else:
                exc_name = pretty_exception_name(exception)
                name = f"Internal Server Error ({exc_name})"

        return await get_exception_page(
            code,
            name,
            desc,
        )

    return wrapper


# Stolen from WOOF (Web Offer One File), Copyright (C) 2004-2009 Simon Budig,
# available at http://www.home.unix-ag.org/simon/woof
# with modifications

# Utility function to guess the IP (as a string) where the server can be
# reached from the outside. Quite nasty problem actually.


def find_ip() -> str:
    """Guess the IP where the server can be found from the network."""
    # we get a UDP-socket for the TEST-networks reserved by IANA.
    # It is highly unlikely, that there is special routing used
    # for these networks, hence the socket later should give us
    # the IP address of the default route.
    # We're doing multiple tests, to guard against the computer being
    # part of a test installation.

    candidates: list[str] = []
    for test_ip in ("192.0.2.0", "198.51.100.0", "203.0.113.0"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect((test_ip, 80))
        ip_addr: str = sock.getsockname()[0]
        sock.close()
        if ip_addr in candidates:
            return ip_addr
        candidates.append(ip_addr)

    return candidates[0]


app: Final = QuartTrio(  # pylint: disable=invalid-name
    __name__,
    static_folder="static",
    template_folder="templates",
)


@pretty_exception
@app.route("/MineOSAPI/2.04/<script>", methods=("POST", "GET"))
async def handle_root(script: str) -> bytes:
    """Send root file."""
    client = app.config["HTTPX_CLIENT"]

    method = request.method

    multi_dict = await request.form
    form = multi_dict.to_dict()
    data = dict(ChainMap(form, request.args))

    if data:
        method = "POST"

    script_title = script.removesuffix(".php")

    record = "&".join(f"{k}={data[k]}" for k in sorted(data))
    record_bin = record.encode("utf-8")

    script_record = DATA_PATH / f"{script_title}.bi"

    if not await script_record.exists():
        async with await script_record.open("wb") as afp:
            await afp.aclose()

    current_time = int(time.time())
    timestamp = current_time
    # Ignore if older than 1 day
    decay_time = 1 * 60 * 60 * 24
    # TODO: Delete expired records
    with open(script_record, "rb") as fp:  # noqa: ASYNC230
        with reader.BiReader(fp) as bi_reader:
            for item in bi_reader:
                if (
                    isinstance(item, reader.BlobField)
                    and item.name == record_bin
                ):
                    age = current_time - timestamp
                    if age > decay_time:
                        print(f"{script_record} - Exists but {age = }")
                        continue
                    return item.content
                if (
                    isinstance(item, reader.IntegerField)
                    and item.name == b"timestamp"
                ):
                    timestamp = item.value

    print(f"{record = }")
    url = f"{HOST}/{script}"

    headers = {
        "User-Agent": AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    if method == "GET":
        response = await client.get(url=url, headers=headers)
    else:
        response = await client.post(url=url, data=data, headers=headers)
    result = await response.aread()
    assert isinstance(result, bytes)

    timestamp_field = reader.IntegerField(b"timestamp", int(time.time()))
    blob = reader.BlobField(record_bin, result)

    async with await script_record.open("ab") as afp:
        # Write timestamp before field
        # TODO: Delete expired records
        await afp.write(timestamp_field.to_stream())
        await afp.write(blob.to_stream())
    return result


try:
    import market_api

    def pretty_format(text: str) -> str:
        """Pretty format text."""
        obj = cast(
            "dict[str, Any]",
            market_api.lua_parser.parse_lua_table(text),
        )
        value = market_api.pretty_format_response(obj)
        assert isinstance(value, str)
        return value

except ImportError:

    def pretty_format(text: str) -> str:
        """Pretty format text."""
        return text


async def serve_async(app: QuartTrio, config_obj: Config) -> None:
    """Serve app within a nursery."""
    if not await DATA_PATH.exists():
        await DATA_PATH.mkdir()
    async with httpx.AsyncClient() as client:
        app.config["HTTPX_CLIENT"] = client
        await serve(app, config_obj)
        app.config["HTTPX_CLIENT"] = None


def server_market(
    secure_bind_port: int | None = None,
    insecure_bind_port: int | None = None,
    ip_addr: str | None = None,
    hypercorn: dict[str, object] | None = None,
) -> None:
    """Asynchronous Entry Point."""
    if secure_bind_port is None and insecure_bind_port is None:
        raise ValueError(
            "Port must be specified with `port` and or `ssl_port`!",
        )

    if not ip_addr:
        ip_addr = find_ip()

    if not hypercorn:
        hypercorn = {}

    logs_path = DATA_PATH / "logs"
    if not path.exists(logs_path):
        makedirs(logs_path)

    print(f"Logs Path: {str(logs_path)!r}")
    print(f"Records Path: {str(DATA_PATH)!r}\n")

    try:
        # Hypercorn config setup
        config: dict[str, object] = {
            "accesslog": "-",
            "errorlog": logs_path / time.strftime("log_%Y_%m_%d.log"),
        }
        # Load things from user controlled toml file for hypercorn
        config.update(hypercorn)
        # Override a few particularly important details if set by user
        config.update(
            {
                "worker_class": "trio",
            },
        )
        # Make sure address is in bind

        if insecure_bind_port is not None:
            raw_bound = config.get("insecure_bind", [])
            if not isinstance(raw_bound, Iterable):
                raise ValueError(
                    "main.bind must be an iterable object (set in config file)!",
                )
            bound = set(raw_bound)
            bound |= {f"{ip_addr}:{insecure_bind_port}"}
            config["insecure_bind"] = bound

            # If no secure port, use bind instead
            if secure_bind_port is None:
                config["bind"] = config["insecure_bind"]
                config["insecure_bind"] = []

            insecure_locations = combine_end(
                f"http://{addr}" for addr in sorted(bound)
            )
            print(f"Serving on {insecure_locations} insecurely")

        if secure_bind_port is not None:
            raw_bound = config.get("bind", [])
            if not isinstance(raw_bound, Iterable):
                raise ValueError(
                    "main.bind must be an iterable object (set in config file)!",
                )
            bound = set(raw_bound)
            bound |= {f"{ip_addr}:{secure_bind_port}"}
            config["bind"] = bound

            secure_locations = combine_end(
                f"https://{addr}" for addr in sorted(bound)
            )
            print(f"Serving on {secure_locations} securely")

        app.config["EXPLAIN_TEMPLATE_LOADING"] = False

        # We want pretty html, no jank
        app.jinja_options = {
            "trim_blocks": True,
            "lstrip_blocks": True,
        }

        app.add_url_rule("/<path:filename>", "static", app.send_static_file)

        config_obj = Config.from_mapping(config)

        print("(CTRL + C to quit)")

        trio.run(serve_async, app, config_obj)
    except BaseExceptionGroup as exc:
        caught = False
        for ex in exc.exceptions:
            if isinstance(ex, KeyboardInterrupt):
                print("Shutting down from keyboard interrupt")
                caught = True
                break
        if not caught:
            raise


def run() -> None:
    """Run scanner server."""
    if not path.exists(CONFIG_PATH):
        makedirs(CONFIG_PATH)
    if not path.exists(MAIN_CONFIG):
        with open(MAIN_CONFIG, "w", encoding="utf-8") as fp:
            fp.write(
                """[main]
# Port server should run on.
# You might want to consider changing this to 80
port = 3004

# Port for SSL secured server to run on
#ssl_port = 443

# Helpful stack exchange website question on how to allow non root processes
# to bind to lower numbered ports
# https://superuser.com/questions/710253/allow-non-root-process-to-bind-to-port-80-and-443
# Answer I used: https://superuser.com/a/1482188/1879931

[hypercorn]
# See https://hypercorn.readthedocs.io/en/latest/how_to_guides/configuring.html#configuration-options
use_reloader = false
# SSL configuration details
#certfile = "/home/<your_username>/letsencrypt/config/live/<your_domain_name>.duckdns.org/fullchain.pem"
#keyfile = "/home/<your_username>/letsencrypt/config/live/<your_domain_name>.duckdns.org/privkey.pem"
""",
            )

    print(f"Reading configuration file {str(MAIN_CONFIG)!r}...\n")

    with open(MAIN_CONFIG, "rb") as fp:
        config = tomllib.load(fp)

    main_section = config.get("main", {})

    insecure_bind_port = main_section.get("port", None)
    secure_bind_port = main_section.get("ssl_port", None)

    hypercorn: dict[str, object] = config.get("hypercorn", {})

    ip_address: str | None = None
    if "--local" in sys.argv[1:]:
        ip_address = "127.0.0.1"

    server_market(
        secure_bind_port=secure_bind_port,
        insecure_bind_port=insecure_bind_port,
        ip_addr=ip_address,
        hypercorn=hypercorn,
    )


if __name__ == "__main__":
    run()
