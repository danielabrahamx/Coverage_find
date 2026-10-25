from coverage_detective.data.zetaris import _coerce


def test_coerce_numbers_and_identifiers():
    assert _coerce("7") == 7
    assert _coerce("-1.5") == -1.5
    assert _coerce("6.7414498E7") == 67414498.0
    assert _coerce("null") is None and _coerce(None) is None
    assert _coerce("1202032212120330") == "1202032212120330"  # 16-digit quadkey
    assert _coerce("0313131311301000") == "0313131311301000"  # leading zero
    assert _coerce("8719532ceffffff") == "8719532ceffffff"
    assert _coerce("2026Q3") == "2026Q3"


def test_token_expiry_from_jwt():
    import base64
    import json

    from coverage_detective.data.zetaris import _token_expiry

    payload = base64.urlsafe_b64encode(json.dumps({"exp": 1761400000}).encode()).decode().rstrip("=")
    assert _token_expiry(f"header.{payload}.sig") == 1761400000
    assert _token_expiry("not-a-jwt") == 0.0
