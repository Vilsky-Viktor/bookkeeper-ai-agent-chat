"""Fixed replies (receipt outcomes, errors) the backend doesn't word itself: it sends
a key plus params, and the web app shows it in the user's language
(web/src/lib/i18n/locales/*.ts, under `ui`). Every translation lives there;
tests/test_contracts.py fails if a key here is missing from the web app."""

from typing import Literal

from pydantic import BaseModel, Field

NoticeKey = Literal[
    "receiptProposed",  # params: date
    "notAReceipt",
    "receiptUnreadable",
    "alreadySent",
    "requestFailed",
    "turnFailed",
    "turnLimitReached",
    "receiptLimitReached",
    "savedTransactions",  # params: n
]


class Notice(BaseModel):
    key: NoticeKey
    params: dict[str, str] = Field(default_factory=dict)
