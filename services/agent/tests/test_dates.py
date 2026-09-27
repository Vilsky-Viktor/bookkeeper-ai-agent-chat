import datetime
from zoneinfo import ZoneInfo

import pytest

from app.helpers import dates


class _FrozenDatetime(datetime.datetime):
    """2026-09-26 23:30 UTC — already the 27th in Bali (UTC+8), still the 26th in UTC."""

    @classmethod
    def now(cls, tz=None):
        moment = datetime.datetime(2026, 9, 26, 23, 30, tzinfo=datetime.timezone.utc)

        return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(dates.datetime, "datetime", _FrozenDatetime)


def test_today_is_the_users_date_not_the_servers():
    assert dates.user_today("Asia/Makassar") == datetime.date(2026, 9, 27)


def test_a_timezone_behind_utc():
    assert dates.user_today("America/New_York") == datetime.date(2026, 9, 26)


@pytest.mark.parametrize("timezone", [None, "", "Not/AZone", "../../etc/passwd"])
def test_missing_or_invalid_timezone_falls_back_to_utc(timezone):
    assert dates.user_today(timezone) == datetime.date(2026, 9, 26)


def test_zoneinfo_is_available_in_this_image():
    # python:3.12-slim ships tzdata; without it every user would silently get UTC.
    assert ZoneInfo("Asia/Makassar")
