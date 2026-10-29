from __future__ import annotations

import pytest
import requests

from portfolio.ibkr_flex_client import MAX_STATEMENT_BYTES, FlexClient, FlexServiceError

SUCCESS = b"<FlexStatementResponse><Status>Success</Status><ReferenceCode>123</ReferenceCode><url>https://attacker.example/steal</url></FlexStatementResponse>"
PENDING = b"<FlexStatementResponse><Status>Fail</Status><ErrorCode>1019</ErrorCode></FlexStatementResponse>"
STATEMENT = b"<FlexQueryResponse><FlexStatements/></FlexQueryResponse>"


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def iter_content(self, *_):
        yield self.body


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        self.closed = True


def test_send_then_fetch_polls_and_ignores_broker_url():
    session = Session([Response(SUCCESS), Response(PENDING), Response(STATEMENT)])
    waits = []
    assert FlexClient("secret-token", "456", session=session, sleep=waits.append).fetch_statement() == STATEMENT
    assert [url.rsplit("/", 1)[1] for url, _ in session.calls] == ["SendRequest", "GetStatement", "GetStatement"]
    assert all(url.startswith("https://ndcdyn.interactivebrokers.com/") for url, _ in session.calls)
    assert session.calls[1][1]["params"]["q"] == "123"
    assert waits == [10, 10]
    assert session.closed


@pytest.mark.parametrize(
    "response",
    [
        Response(b"broken"),
        Response(STATEMENT, 503),
        requests.ConnectionError("https://url?t=secret-token"),
        Response(b"x" * (MAX_STATEMENT_BYTES + 1)),
    ],
)
def test_failures_are_bounded_and_do_not_expose_credentials(response):
    session = Session([response])
    with pytest.raises(FlexServiceError) as error:
        FlexClient("secret-token", "456", session=session, sleep=lambda _: None).fetch_statement()
    assert "secret-token" not in str(error.value)
    assert session.closed


def test_expired_token_is_not_retried_or_leaked():
    session = Session(
        [
            Response(
                b"<FlexStatementResponse><Status>Fail</Status><ErrorCode>1012</ErrorCode><ErrorMessage>secret-token</ErrorMessage></FlexStatementResponse>"
            )
        ]
    )
    with pytest.raises(FlexServiceError, match="1012") as error:
        FlexClient("secret-token", "456", session=session, sleep=lambda _: None).fetch_statement()
    assert len(session.calls) == 1
    assert "secret-token" not in str(error.value)


def test_polling_stops_after_six_attempts():
    session = Session([Response(SUCCESS)] + [Response(PENDING)] * 6)
    with pytest.raises(FlexServiceError, match="1019"):
        FlexClient("token", "456", session=session, sleep=lambda _: None).fetch_statement()
    assert len(session.calls) == 7
