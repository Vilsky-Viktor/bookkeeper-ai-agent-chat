"""The user's "today". The server runs in UTC, so its own date is wrong for anyone
far from UTC for part of every day (in Bali, UTC+8, until 08:00). The browser sends
its IANA timezone with each message; the date is computed here, from the server's
clock, so a client can only pick a timezone, not an arbitrary date."""

import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def user_today(timezone: str | None) -> datetime.date:
    if timezone:
        try:
            return datetime.datetime.now(ZoneInfo(timezone)).date()
        except (ZoneInfoNotFoundError, ValueError):
            pass  # unknown or malformed name: fall back to UTC

    return datetime.datetime.now(datetime.timezone.utc).date()
