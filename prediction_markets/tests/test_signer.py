"""RSA-PSS 签名器：待签名原文格式 + 签名可被公钥验证（自洽）。"""
from prediction_markets import kalshi_auth


def test_signed_message_format():
    # path 去 query，method 大写，顺序 = ts+METHOD+path
    msg = kalshi_auth.signed_message("1700000000000", "get",
                                     "/trade-api/v2/portfolio/orders?limit=5")
    assert msg == "1700000000000GET/trade-api/v2/portfolio/orders"


def test_ws_sign_path():
    msg = kalshi_auth.signed_message("1700000000000", "GET", kalshi_auth.WS_SIGN_PATH)
    assert msg == "1700000000000GET/trade-api/ws/v2"


def test_sign_and_verify_roundtrip():
    # 生成一次性 RSA 私钥，签名后用公钥按同参数验证 —— 证明签名参数与 Kalshi 规范一致
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives import hashes
    import base64

    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ts = "1700000000000"
    headers = kalshi_auth.build_headers("test-key-id", priv, "GET", "/trade-api/ws/v2", timestamp=ts)
    assert headers["KALSHI-ACCESS-KEY"] == "test-key-id"
    assert headers["KALSHI-ACCESS-TIMESTAMP"] == ts

    sig = base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"])
    message = kalshi_auth.signed_message(ts, "GET", "/trade-api/ws/v2").encode()
    # 若参数不符会抛 InvalidSignature
    priv.public_key().verify(
        sig, message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )


TESTS = [test_signed_message_format, test_ws_sign_path, test_sign_and_verify_roundtrip]
