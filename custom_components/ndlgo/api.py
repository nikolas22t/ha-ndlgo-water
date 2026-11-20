"""Async client for the NDLGO (Nicosia water board) portal API."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp

from .const import API, TZ_NAME

TZ = ZoneInfo(TZ_NAME)
_LOGGER = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}


class NdlgoAuthError(Exception):
    """Invalid credentials."""


class NdlgoError(Exception):
    """Communication error."""


class NdlgoNotFound(NdlgoError):
    """Endpoint/resource not available (404)."""


@dataclass
class Period:
    start: datetime
    end: datetime
    m3: float
    eur: float
    installation: str


@dataclass
class AmrReading:
    time: datetime
    value: float
    cumulative: bool  # True = meter index, False = consumption of the interval


TIME_KEY = re.compile(r"date|time|dt|timestamp", re.I)
USAGE_KEY = re.compile(r"consum|usage|volume|qty|quantity|diff|delta", re.I)
INDEX_KEY = re.compile(r"reading|index|meter_val|value|counter", re.I)
DATE_FORMATS = ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def _parse_time(v) -> datetime | None:
    if not isinstance(v, str) or not v.strip():
        return None
    v = v.strip()
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        dt = None
        for fmt in DATE_FORMATS:
            try:
                dt = datetime.strptime(v, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def parse_amr(payload) -> list[AmrReading]:
    """Best-effort parser: the AMR response format is not documented yet."""
    rows = payload
    if isinstance(payload, dict):
        rows = next((v for v in payload.values() if isinstance(v, list)), [])
    out: list[AmrReading] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        t = next((_parse_time(v) for k, v in row.items() if TIME_KEY.search(k) and _parse_time(v)), None)
        if t is None:
            continue
        usage = next((_num(v) for k, v in row.items() if USAGE_KEY.search(k) and _num(v) is not None), None)
        if usage is not None:
            out.append(AmrReading(t, usage, False))
            continue
        idx = next((_num(v) for k, v in row.items() if INDEX_KEY.search(k) and _num(v) is not None), None)
        if idx is not None:
            out.append(AmrReading(t, idx, True))
    return sorted(out, key=lambda r: r.time)


class NdlgoClient:
    def __init__(self, session: aiohttp.ClientSession, username: str, password: str) -> None:
        self._s, self._u, self._p = session, username, password

    async def _req(self, path: str, jwt: str | None = None, body: dict | None = None):
        headers = dict(HEADERS)
        if jwt:
            headers["Cookie"] = "jwt=" + jwt
        try:
            async with self._s.request(
                "POST" if body is not None else "GET", API + path, json=body, headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as r:
                if r.status in (401, 403):
                    raise NdlgoAuthError
                if r.status == 404:
                    raise NdlgoNotFound(path)
                r.raise_for_status()
                return await r.json(content_type=None)
        except (NdlgoAuthError, NdlgoNotFound):
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise NdlgoError(str(err)) from err

    async def login(self) -> str:
        data = await self._req("oraclelogin", body={"username": self._u, "password": self._p})
        token = (data or {}).get("accessToken") if isinstance(data, dict) else None
        if not token:
            raise NdlgoAuthError
        return token

    async def fetch(self) -> tuple[list[Period], list[AmrReading]]:
        jwt = await self.login()
        insts = await self._req("wbninst", jwt) or []
        return await self._periods(jwt, insts), await self._amr(jwt, insts)

    async def periods(self) -> list[Period]:
        jwt = await self.login()
        return await self._periods(jwt, await self._req("wbninst", jwt) or [])

    async def _amr(self, jwt: str, insts: list) -> list[AmrReading]:
        """AMR (smart meter) readings; empty when the meter/portal has none."""
        out: list[AmrReading] = []
        for inst in insts:
            for ident in (inst.get("inst_serial_no"), inst.get("meter_no")):
                if not ident:
                    continue
                try:
                    payload = await self._req(f"wbbamrperiods/{ident}", jwt)
                except NdlgoNotFound:
                    continue
                except NdlgoError as err:
                    _LOGGER.debug("AMR fetch failed for %s: %s", ident, err)
                    continue
                readings = parse_amr(payload)
                _LOGGER.debug("AMR %s: %d readings parsed, sample=%s", ident, len(readings), str(payload)[:500])
                if readings:
                    out.extend(readings)
                    break
        return sorted(out, key=lambda r: r.time)

    async def _periods(self, jwt: str, insts: list) -> list[Period]:
        out: list[Period] = []
        for inst in insts:
            serial = str(inst["inst_serial_no"])
            for p in await self._req(f"wbnperiods/{serial}", jwt) or []:
                a, b = p["period_desc"].split("-")
                y = int(p["read_year"])
                sd, sm = map(int, a.split("/"))
                ed, em = map(int, b.split("/"))
                out.append(Period(
                    datetime(y - (sm > em), sm, sd, tzinfo=TZ), datetime(y, em, ed, tzinfo=TZ),
                    float(p["reading"]), float(p["read_amount"]), serial,
                ))
        return sorted(out, key=lambda x: x.start)
