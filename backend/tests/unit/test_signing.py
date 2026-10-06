"""T5: HMAC-signed download links (AM-7, VERIFIED row 8)."""

from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from app.storage.signing import content_disposition, sign_download, verify_download

SECRET = "s" * 40
KEY = "documents/00000000-0000-0000-0000-000000000001/00000000-0000-0000-0000-000000000002"
NOW = 1_800_000_000


def link(**kw):
    args = dict(secret=SECRET, base_url="https://api.example.com/", bucket="cloudvault-sim", key=KEY,
                version_id="ver123", filename="résumé report.pdf", now=NOW, ttl_seconds=120)
    args.update(kw)
    return sign_download(**args)


def verify(url, now=NOW, secret=SECRET, **override):
    u = urlsplit(url)
    path = u.path.removeprefix("/api/sim-s3/")
    bucket, key = path.split("/", 1)
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    fields = dict(bucket=unquote(bucket), key=unquote(key), version_id=q.get("versionId"),
                  filename=q.get("filename"), expires=q.get("expires"), sig=q.get("signature"))
    fields.update(override)
    return verify_download(secret=secret, now=now, **fields)


def test_link_shape():
    signed = link()
    u = urlsplit(signed.url)
    assert (u.scheme, u.netloc) == ("https", "api.example.com")
    assert u.path == f"/api/sim-s3/cloudvault-sim/{KEY}"
    q = parse_qs(u.query)
    assert q["versionId"] == ["ver123"] and q["filename"] == ["résumé report.pdf"]
    assert q["expires"] == [str(NOW + 120)]
    assert (signed.expires_in, signed.expires_at) == (120, NOW + 120)


def test_valid_until_expiry_inclusive():
    url = link().url
    assert verify(url)
    assert verify(url, now=NOW + 120)
    assert not verify(url, now=NOW + 121)  # expired: S3 refuses at request time


@pytest.mark.parametrize(
    "override",
    [
        {"version_id": "other"},
        {"filename": "evil.html"},
        {"key": KEY[:-1] + "3"},
        {"bucket": "other-bucket"},
        {"expires": str(NOW + 10_000)},
        {"sig": "AAAA"},
        {"sig": None},
        {"expires": "soon"},
        {"version_id": None},
    ],
)
def test_tampered_or_incomplete_links_rejected(override):
    assert not verify(link().url, **override)


def test_other_secret_rejected():
    assert not verify(link().url, secret="t" * 40)


def test_content_disposition_utf8_and_fallback():
    value = content_disposition('résumé "q".pdf')
    assert value.startswith('attachment; filename="r_sum_ _q_.pdf"')
    assert "filename*=UTF-8''r%C3%A9sum%C3%A9%20%22q%22.pdf" in value
