"""Unit tests for app/photo_color.py — tiny in-memory images, no network. Run: cd backend && pytest"""
import io
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import photo_color  # noqa: E402
from app.photo_color import edge_color, fetch_image_bytes  # noqa: E402


def _png(color, size=(40, 30), mode="RGBA") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, "PNG")
    return buf.getvalue()


def _jpeg(color, size=(40, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG", quality=95)
    return buf.getvalue()


def test_white():
    assert edge_color(_png((255, 255, 255, 255))) == "#FFFFFF"


def test_light_grey():
    assert edge_color(_png((242, 242, 242, 255))) == "#F2F2F2"


def test_black_rgb_mode():
    assert edge_color(_png((0, 0, 0), mode="RGB")) == "#000000"


def test_jpeg_close_to_source():
    got = edge_color(_jpeg((200, 100, 50)))
    assert got is not None and got.startswith("#") and len(got) == 7 and got == got.upper()
    r, g, b = (int(got[i:i + 2], 16) for i in (1, 3, 5))
    assert abs(r - 200) < 6 and abs(g - 100) < 6 and abs(b - 50) < 6


def test_median_ignores_a_minority_subject():
    img = Image.new("RGB", (100, 100), (250, 250, 250))
    img.paste((0, 0, 0), (30, 30, 70, 70))  # subject in the middle, corners untouched
    buf = io.BytesIO()
    img.save(buf, "PNG")
    assert edge_color(buf.getvalue()) == "#FAFAFA"


def test_transparent_png_is_none():
    assert edge_color(_png((255, 255, 255, 0))) is None


def test_one_transparent_corner_is_none():
    img = Image.new("RGBA", (50, 50), (255, 255, 255, 255))
    img.paste((0, 0, 0, 0), (0, 0, 5, 5))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    assert edge_color(buf.getvalue()) is None


def test_garbage_is_none():
    assert edge_color(b"not an image at all") is None
    assert edge_color(b"") is None


def test_one_pixel_image():
    assert edge_color(_png((10, 20, 30, 255), size=(1, 1))) == "#0A141E"


def test_oversized_image_is_none(monkeypatch):
    monkeypatch.setattr(photo_color.Image, "MAX_IMAGE_PIXELS", 100)
    assert edge_color(_png((255, 255, 255, 255), size=(200, 200))) is None


class _FakeResp:
    def __init__(self, status=200, headers=None, body=b""):
        self.status_code, self.headers, self._body = status, headers or {}, body
        self.is_redirect = status in (301, 302, 303, 307, 308)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_bytes(self):
        yield self._body


class _FakeClient:
    routes: dict = {}
    seen: list = []

    def __init__(self, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def stream(self, method, url):
        _FakeClient.seen.append(url)
        return _FakeClient.routes[url]


def _patch_client(monkeypatch, routes):
    _FakeClient.routes, _FakeClient.seen = routes, []
    monkeypatch.setattr(photo_color.httpx, "Client", _FakeClient)


def test_fetch_ok(monkeypatch):
    _patch_client(monkeypatch, {"https://x.test/a.jpg": _FakeResp(body=b"abc")})
    assert fetch_image_bytes("https://x.test/a.jpg") == b"abc"


def test_fetch_rejects_other_schemes():
    assert fetch_image_bytes("file:///etc/passwd") is None
    assert fetch_image_bytes("ftp://x.test/a.jpg") is None


def test_fetch_oversized_body_is_none(monkeypatch):
    _patch_client(monkeypatch, {"https://x.test/a.jpg": _FakeResp(body=b"x" * 50)})
    assert fetch_image_bytes("https://x.test/a.jpg", max_bytes=10) is None


def test_fetch_declared_oversize_is_none(monkeypatch):
    _patch_client(monkeypatch, {"https://x.test/a.jpg": _FakeResp(headers={"content-length": "999"}, body=b"x")})
    assert fetch_image_bytes("https://x.test/a.jpg", max_bytes=10) is None


def test_fetch_non_200_is_none(monkeypatch):
    _patch_client(monkeypatch, {"https://x.test/a.jpg": _FakeResp(status=404)})
    assert fetch_image_bytes("https://x.test/a.jpg") is None


def test_fetch_follows_redirect_and_guard_checks_each_hop(monkeypatch):
    _patch_client(monkeypatch, {
        "https://x.test/a.jpg": _FakeResp(302, {"location": "http://10.0.0.1/secret.jpg"}),
        "http://10.0.0.1/secret.jpg": _FakeResp(body=b"secret"),
    })
    guard = lambda u: "10.0.0.1" not in u  # noqa: E731
    assert fetch_image_bytes("https://x.test/a.jpg", url_guard=guard) is None
    assert _FakeClient.seen == ["https://x.test/a.jpg"]  # the private hop was never requested
    assert fetch_image_bytes("https://x.test/a.jpg") == b"secret"  # without a guard the hop is followed


def test_fetch_too_many_redirects(monkeypatch):
    routes = {f"https://x.test/{i}": _FakeResp(302, {"location": f"https://x.test/{i + 1}"}) for i in range(10)}
    _patch_client(monkeypatch, routes)
    assert fetch_image_bytes("https://x.test/0") is None


def test_fetch_exception_is_none(monkeypatch):
    _patch_client(monkeypatch, {})  # KeyError inside stream()
    assert fetch_image_bytes("https://x.test/missing") is None
