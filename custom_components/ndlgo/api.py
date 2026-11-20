"""Async client for the NDLGO (Nicosia water board) portal API."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp

from .const import API, TZ_NAME

TZ = ZoneInfo(TZ_NAME)
HEADERS = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}


class NdlgoAuthError(Exception):
    """Invalid credentials."""


class NdlgoError(Exception):
    """Communication error."""


@dataclass
class Period:
    start: datetime
    end: datetime
    m3: float
    eur: float
    installation: str


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
                r.raise_for_status()
                return await r.json(content_type=None)
        except NdlgoAuthError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise NdlgoError(str(err)) from err

    async def login(self) -> str:
        data = await self._req("oraclelogin", body={"username": self._u, "password": self._p})
        token = (data or {}).get("accessToken") if isinstance(data, dict) else None
        if not token:
            raise NdlgoAuthError
        return token

    async def periods(self) -> list[Period]:
        jwt = await self.login()
        out: list[Period] = []
        for inst in await self._req("wbninst", jwt) or []:
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
