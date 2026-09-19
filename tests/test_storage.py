import pytest

from pipeline.ingest.storage import StorageError, SupabaseStorage


class Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class Session:
    def __init__(self, get_resp, post_resp=None):
        self.headers = {}
        self.get_resp = get_resp
        self.post_resp = post_resp or Resp(200, {})
        self.posted = []

    def get(self, url, timeout):
        return self.get_resp

    def post(self, url, json=None, timeout=None, **_):
        self.posted.append((url, json))
        return self.post_resp


def make(get_resp, post_resp=None):
    s = SupabaseStorage("https://example.supabase.co", "fake-key-for-tests")
    s.session = Session(get_resp, post_resp)
    return s


def test_public_bucket_stops_the_run():
    # A nyers adat licenc miatt nem lehet nyilvános (spec/05, 2.4).
    with pytest.raises(StorageError, match="NYILVÁNOS"):
        make(Resp(200, {"id": "market-data-raw", "public": True})).ensure_private_bucket("market-data-raw")


def test_missing_bucket_is_created_private():
    s = make(Resp(400, {"statusCode": "404", "error": "Bucket not found"}))
    s.ensure_private_bucket("market-data-raw")
    url, body = s.session.posted[0]
    assert url.endswith("/storage/v1/bucket")
    assert body == {"id": "market-data-raw", "name": "market-data-raw", "public": False}


def test_error_message_never_contains_the_response_body():
    s = make(Resp(500, {"secret": "should-not-leak"}))
    with pytest.raises(StorageError) as err:
        s.ensure_private_bucket("x")
    assert "should-not-leak" not in str(err.value)
