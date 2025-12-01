# MineOS Market Proxy
Caching proxy server for the MineOS App Market

<!-- BADGIE TIME -->

[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/CoolCat467/MineOS-Market-Proxy/main.svg)](https://results.pre-commit.ci/latest/github/CoolCat467/MineOS-Market-Proxy/main)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

<!-- END BADGIE TIME -->

## Purpose
Basically I wrote this one day because I didn't want to get rate limited
from spamming the main server with requests, because at the time I was
writing a script to scrape all of the publications from the main server
for backup purposes. Nice bonus that it also means repeat runs can
return faster. See the `import_records` script from
https://github.com/CoolCat467/MineOS-Market-Server

## Installation
```bash
pip install git+https://github.com/CoolCat467/MineOS-Market-Proxy.git
```

## Usage
```bash
mineos_market_proxy
```

## Technical details
Requests that have not been seen before (or all existing records are
older than 1 day) will be relayed and recorded with a timestamp record
before it, each script to its own file.

Binary records are stored in Tsoding bi format.
See https://github.com/tsoding/bi-format for more details.
