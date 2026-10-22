from onecta_modbus.onecta import RateLimit, extract_code


def test_extract_code_plain_and_nested():
    assert extract_code("http://192.168.10.20:8080/auth/callback?code=abc.1&state=S", "S") == "abc.1"
    nested = ("https://my.home-assistant.io/redirect/_change/?redirect=oauth%2F%3Fcode%3Dst2.s.X_y-1"
              "%26state%3DS")
    assert extract_code(nested, "S") == "st2.s.X_y-1"
    assert extract_code("http://x/?code=abc&state=OTHER", "S") is None
    assert extract_code("http://x/?state=S", "S") is None


def test_rate_limit_headers():
    limit = RateLimit.from_headers({"X-RateLimit-Remaining-day": "171", "X-RateLimit-Remaining-minute": "19"})
    assert (limit.day, limit.minute, limit.retry_after) == (171, 19, None)
    assert RateLimit.from_headers({}).day is None
