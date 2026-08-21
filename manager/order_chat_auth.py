from secrets import compare_digest


class OperatorChatAuthenticator:
    def __init__(self, expected_secret: str):
        self._expected_secret = expected_secret

    def matches(self, candidate: str | None) -> bool:
        if candidate is None:
            return False
        return compare_digest(candidate, self._expected_secret)
