from contextlib import contextmanager
import hashlib
import http.client
from io import BytesIO
import os
from pathlib import Path
import socket
import ssl
import tempfile
import unittest
from unittest.mock import Mock, patch

import certifi
from PIL import Image

from backend.app.service import cover_service as covers


URL = "https://covers.example/art.png?token=private-secret"
PUBLIC_DNS = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443))]


def image_bytes(size=(120, 200), mode="RGB", color=(210, 60, 90), format="PNG", **kwargs):
    with Image.new(mode, size, color) as image, BytesIO() as output:
        image.save(output, format=format, **kwargs)
        return output.getvalue()


class FakeResponse:
    def __init__(self, data=b"", *, status=200, headers=None, chunks=None):
        self.status_code = status
        self.headers = headers if headers is not None else {"Content-Length": str(len(data))}
        self.data = data
        self.chunks = chunks
        self.closed = False
        self.iterated = False

    def iter_content(self, chunk_size):
        self.iterated = True
        if self.chunks is not None:
            yield from self.chunks
        else:
            for offset in range(0, len(self.data), chunk_size):
                yield self.data[offset:offset + chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return self.response


class CoverTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cache = Path(self.temporary.name) / "covers"
        self.dns = patch.object(covers.socket, "getaddrinfo", return_value=PUBLIC_DNS).start()
        self.addCleanup(patch.stopall)
        self.proxy_patcher = patch.object(covers, "_configured_proxy", return_value=None)
        self.proxy_discovery = self.proxy_patcher.start()
        self.socket_constructor = socket.socket
        # No test may accidentally reach the real network, including failure paths.
        self.socket = patch.object(covers.socket, "socket", side_effect=AssertionError("Real network forbidden")).start()

    @contextmanager
    def wire_transport(self, wire, *, proxy):
        # Use loopback TCP on every OS: socketpair() is AF_UNIX on macOS and
        # rejects HTTPConnection's TCP_NODELAY option before the HTTP read.
        # Request handling keeps real sockets, makefile(), HTTPConnection and
        # HTTPResponse; only destination connection setup is redirected.
        with patch.object(socket, "socket", self.socket_constructor):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.settimeout(2)
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    client.settimeout(2)
                    client.connect(listener.getsockname())
                    peer, _ = listener.accept()
                except Exception:
                    client.close()
                    raise
        with client, peer:
            client.settimeout(2)
            peer.settimeout(2)
            peer.sendall(wire)
            peer.shutdown(socket.SHUT_WR)
            with patch.object(covers, "_configured_proxy", return_value=(
                    covers._Proxy("127.0.0.1", 7892) if proxy else None)), \
                    patch.object(covers, "_connect_public", return_value=client), \
                    patch.object(covers.socket, "create_connection", return_value=client):
                yield client

    def load(self, data=None, **response_kwargs):
        response = FakeResponse(image_bytes() if data is None else data, **response_kwargs)
        session = FakeSession(response)
        result = covers.load_cover(URL, self.cache, session=session)
        self.assertTrue(response.closed)
        return result, session

    def assert_png(self, data, size):
        with Image.open(BytesIO(data)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.size, size)
            image.load()

    def test_exact_variants_and_letterboxing_without_cropping(self):
        result, session = self.load(image_bytes((400, 200)))
        self.assertIsInstance(result, covers.CoverData)
        self.assert_png(result.thumbnail_png, (54, 76))
        self.assert_png(result.poster_png, (180, 254))
        for data in (result.thumbnail_png, result.poster_png):
            with Image.open(BytesIO(data)) as image:
                self.assertEqual(image.getpixel((0, 0)), covers._BACKGROUND)
                self.assertEqual(image.getpixel((image.width // 2, image.height // 2)), (210, 60, 90))
        self.assertEqual(len(session.calls), 1)
        kwargs = session.calls[0][1]
        self.assertTrue(kwargs["stream"])
        self.assertTrue(kwargs["verify"])
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"], (covers.CONNECT_TIMEOUT, covers.READ_TIMEOUT))

    def test_tall_cover_has_side_bars(self):
        result, _ = self.load(image_bytes((50, 400)))
        with Image.open(BytesIO(result.poster_png)) as image:
            self.assertEqual(image.getpixel((0, 127)), covers._BACKGROUND)
            self.assertEqual(image.getpixel((90, 127)), (210, 60, 90))

    def test_transparency_is_composited_and_metadata_removed(self):
        result, _ = self.load(image_bytes((180, 254), mode="RGBA", color=(255, 0, 0, 0)))
        with Image.open(BytesIO(result.poster_png)) as image:
            self.assertEqual(image.getpixel((90, 127)), covers._BACKGROUND)
            self.assertFalse(image.info)

    def test_exif_orientation_is_applied(self):
        exif = Image.Exif()
        exif[274] = 6
        result, _ = self.load(image_bytes((200, 100), format="JPEG", exif=exif))
        with Image.open(BytesIO(result.poster_png)) as image:
            self.assertEqual(image.getpixel((0, 127)), covers._BACKGROUND)
            self.assertNotEqual(image.getpixel((90, 0)), covers._BACKGROUND)
            self.assertFalse(image.getexif())

    def test_common_raster_formats_are_normalized(self):
        for format in ("JPEG", "PNG", "WEBP", "GIF"):
            with self.subTest(format=format):
                result = covers.load_cover(
                    f"https://covers.example/{format}", self.cache,
                    session=FakeSession(FakeResponse(image_bytes(format=format))),
                )
                self.assert_png(result.poster_png, covers.POSTER_SIZE)

    def test_cache_is_a_single_normalized_hash_named_png_and_works_offline(self):
        original, _ = self.load()
        filename = hashlib.sha256(URL.encode()).hexdigest() + ".png"
        self.assertEqual([path.name for path in self.cache.iterdir()], [filename])
        self.assertEqual((self.cache / filename).read_bytes(), original.poster_png)
        self.dns.side_effect = OSError("offline")
        offline = FakeSession(error=AssertionError("HTTP on a cache hit"))
        self.assertEqual(covers.load_cover(URL, self.cache, session=offline), original)
        self.assertFalse(offline.calls)
        self.assertEqual(self.dns.call_count, 1)

    def test_corrupt_or_non_normalized_cache_is_refetched(self):
        self.cache.mkdir()
        path = self.cache / (hashlib.sha256(URL.encode()).hexdigest() + ".png")
        for bad in (b"corrupt", image_bytes((12, 12)), image_bytes(covers.POSTER_SIZE, mode="RGBA", color=(0, 0, 0, 0))):
            with self.subTest(data_length=len(bad)):
                path.write_bytes(bad)
                result, session = self.load()
                self.assertEqual(len(session.calls), 1)
                self.assertEqual(path.read_bytes(), result.poster_png)

    def test_oversized_cache_file_is_not_read(self):
        self.cache.mkdir()
        path = self.cache / (hashlib.sha256(URL.encode()).hexdigest() + ".png")
        path.write_bytes(b"x" * (covers.MAX_CACHE_ENTRY_BYTES + 1))
        result, _ = self.load()
        self.assertEqual(path.read_bytes(), result.poster_png)

    def test_unsafe_urls_are_rejected_before_dns_or_http(self):
        urls = [
            "", None, "file:///tmp/a.png", "ftp://covers.example/a", "data:image/png;base64,AAAA",
            "https://name:password@covers.example/a", "https://name@covers.example/a",
            "https://localhost/a", "https://a.localhost/a", "https://LANHOST/a",
            "https://printer.local/a", "https://a.internal/a", "https://a.lan/a",
            "http://127.0.0.1/a", "https://8.8.8.8/a", "http://10.0.0.1/a",
            "http://169.254.169.254/a", "http://[::1]/a", "https://[2606:4700:4700::1111]/a",
            "http://2130706433/a", "http://0x7f000001/a", "http://127.1/a",
            "http://0x7f.0.0.1/a", "https://covers.example:0/a",
            "https://covers.example:99999/a", "https://covers.example:/a",
            "https://covers.example/a\nsecret", "https://covers.example/a\x00secret",
            "https://covers.example/a\x7fsecret", "https://covers.example/a%0d%0aHeader:x",
            "https://covers.example/a%C2%85secret", " https://covers.example/a",
            "https://covers.example\\@evil.example/a", "https://%6cocalhost/a",
        ]
        session = FakeSession(error=AssertionError("HTTP for an unsafe URL"))
        for url in urls:
            with self.subTest(url=url), self.assertRaises(covers.CoverError):
                covers.load_cover(url, self.cache, session=session)
        self.dns.assert_not_called()
        self.assertFalse(session.calls)

    def test_nonpublic_dns_and_mixed_answers_are_rejected(self):
        addresses = [
            "127.0.0.1", "10.1.2.3", "172.16.1.1", "192.168.1.1", "169.254.169.254",
            "100.64.0.1", "0.0.0.0", "224.0.0.1", "240.0.0.1", "192.0.2.1",
            "::1", "fe80::1", "fc00::1", "ff02::1", "2001:db8::1", "::ffff:8.8.8.8",
            "64:ff9b::a00:1", "2002:0a00:0001::1",
        ]
        session = FakeSession(error=AssertionError("Unsafe DNS reached HTTP"))
        for address in addresses:
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            record = (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443))
            for records in ([record], PUBLIC_DNS + [record]):
                with self.subTest(address=address, mixed=len(records) > 1):
                    self.dns.return_value = records
                    with self.assertRaises(covers.CoverError):
                        covers.load_cover(URL, self.cache, session=session)
        self.assertFalse(session.calls)

    def test_dns_failures_and_empty_results_fail_closed(self):
        for result in ([], OSError("resolver failure with private-secret")):
            self.dns.side_effect = result if isinstance(result, Exception) else None
            self.dns.return_value = result
            with self.subTest(result=result), self.assertRaises(covers.CoverError) as error:
                covers.load_cover(URL, self.cache, session=FakeSession())
            self.assertNotIn("private-secret", str(error.exception))

    def test_redirects_and_unsuccessful_statuses_are_not_followed(self):
        for status in (301, 302, 303, 307, 308, 404, 500, 206):
            response = FakeResponse(status=status, headers={"Location": "http://127.0.0.1/secret"})
            session = FakeSession(response)
            with self.subTest(status=status), self.assertRaises(covers.CoverError):
                covers.load_cover(URL, self.cache, session=session)
            self.assertFalse(response.iterated)
            self.assertTrue(response.closed)
            self.assertEqual(len(session.calls), 1)

    def test_declared_and_streamed_download_sizes_are_bounded(self):
        responses = [
            FakeResponse(headers={"Content-Length": str(covers.MAX_DOWNLOAD_BYTES + 1)}),
            FakeResponse(headers={}, chunks=[b"x" * covers._CHUNK_SIZE] * (covers.MAX_DOWNLOAD_BYTES // covers._CHUNK_SIZE + 1)),
            FakeResponse(headers={"Content-Length": "2"}, chunks=[b"xxx"]),
        ]
        for response in responses:
            with self.subTest(headers=response.headers), self.assertRaises(covers.CoverError):
                covers.load_cover(URL, self.cache, session=FakeSession(response))
            self.assertTrue(response.closed)
        self.assertFalse(responses[0].iterated)

    def test_bad_lengths_encodings_and_incomplete_bodies_are_rejected(self):
        for headers, data in [
            ({"Content-Length": "-1"}, b"x"), ({"Content-Length": "bogus"}, b"x"),
            ({"Content-Length": "1,1"}, b"x"), ({"Content-Length": "99999999999999999"}, b"x"),
            ({"Content-Length": "100"}, b"x"), ({}, b""),
            ({"Content-Encoding": "gzip"}, b"x"), ({"Content-Encoding": "br"}, b"x"),
        ]:
            with self.subTest(headers=headers), self.assertRaises(covers.CoverError):
                self.load(data, headers=headers)

    def test_stream_without_content_length_is_supported(self):
        result, _ = self.load(headers={})
        self.assert_png(result.poster_png, covers.POSTER_SIZE)

    def test_download_deadline_is_enforced(self):
        response = FakeResponse(headers={}, chunks=[b"x", b"y"])
        with patch.object(covers.time, "monotonic", side_effect=[0, covers.DOWNLOAD_TIMEOUT + 1]):
            with self.assertRaises(covers.CoverError):
                covers.load_cover(URL, self.cache, session=FakeSession(response))
        self.assertTrue(response.closed)

    def test_network_errors_do_not_leak_url_or_exception_details(self):
        for failure in (TimeoutError(URL), ssl.SSLError(URL), http.client.HTTPException(URL)):
            with self.subTest(failure=type(failure).__name__), self.assertRaises(covers.CoverError) as error:
                covers.load_cover(URL, self.cache, session=FakeSession(error=failure))
            self.assertNotIn(URL, str(error.exception))
            self.assertNotIn("private-secret", str(error.exception))
            self.assertTrue(error.exception.__suppress_context__)

    def test_midstream_errors_close_response_and_do_not_cache(self):
        def broken_chunks():
            yield b"partial"
            raise OSError(URL)

        response = FakeResponse(headers={}, chunks=broken_chunks())
        with self.assertRaises(covers.CoverError) as error:
            covers.load_cover(URL, self.cache, session=FakeSession(response))
        self.assertTrue(response.closed)
        self.assertNotIn("private-secret", str(error.exception))
        self.assertFalse(self.cache.exists())

    def test_invalid_and_unsupported_images_are_rejected(self):
        for data in (b"<html>not an image</html>", b"\x89PNG\r\n\x1a\n", image_bytes()[:-30], image_bytes(format="BMP"), image_bytes(format="TIFF")):
            with self.subTest(length=len(data)), self.assertRaises(covers.CoverError):
                self.load(data)
        self.assertFalse(self.cache.exists())

    def test_decoded_pixel_limit_is_enforced_before_load(self):
        with patch.object(covers, "MAX_IMAGE_PIXELS", 1000):
            with self.assertRaises(covers.CoverError):
                self.load(image_bytes((40, 40)))
        self.assertFalse(self.cache.exists())

    def test_real_twelve_million_pixel_limit(self):
        data = image_bytes((4000, 3001))
        self.assertLess(len(data), covers.MAX_DOWNLOAD_BYTES)
        with self.assertRaises(covers.CoverError):
            self.load(data)

    def test_cache_count_bound_preserves_unrelated_files(self):
        self.cache.mkdir()
        unrelated = self.cache / "keep.txt"
        unrelated.write_text("user data", encoding="utf-8")
        old = self.cache / ("0" * 64 + ".png")
        old.write_bytes(image_bytes(covers.POSTER_SIZE))
        os.utime(old, (1, 1))
        with patch.object(covers, "MAX_CACHE_FILES", 2):
            for index in range(4):
                covers.load_cover(
                    f"https://covers.example/{index}", self.cache,
                    session=FakeSession(FakeResponse(image_bytes())),
                )
            self.assertLessEqual(len(list(self.cache.glob("*.png"))), 2)
        self.assertFalse(old.exists())
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "user data")
        self.assertFalse(list(self.cache.glob("*.tmp")))

    def test_cache_total_byte_bound(self):
        with patch.object(covers, "MAX_CACHE_BYTES", 1600):
            for index in range(5):
                covers.load_cover(
                    f"https://covers.example/{index}", self.cache,
                    session=FakeSession(FakeResponse(image_bytes())),
                )
            self.assertLessEqual(sum(path.stat().st_size for path in self.cache.glob("*.png")), 1600)

    def test_readonly_or_unusable_cache_does_not_prevent_loading(self):
        self.cache.write_bytes(b"not a directory")
        result, _ = self.load()
        self.assert_png(result.poster_png, covers.POSTER_SIZE)

    def test_atomic_cache_replace_and_failure_cleanup(self):
        replace = covers.os.replace
        seen = []

        def checked_replace(source, target):
            self.assertEqual(source.parent, target.parent)
            self.assertNotEqual(source, target)
            self.assert_png(source.read_bytes(), covers.POSTER_SIZE)
            seen.append(target)
            replace(source, target)

        with patch.object(covers.os, "replace", side_effect=checked_replace):
            self.load()
        self.assertEqual(len(seen), 1)
        self.assertFalse(list(self.cache.glob("*.tmp")))
        with patch.object(covers.os, "replace", side_effect=OSError("disk full")):
            result = covers.load_cover(
                URL + "2", self.cache, session=FakeSession(FakeResponse(image_bytes()))
            )
        self.assert_png(result.poster_png, covers.POSTER_SIZE)
        self.assertFalse(list(self.cache.glob("*.tmp")))

    def test_cache_symlink_is_not_read_or_followed(self):
        self.cache.mkdir()
        target = Path(self.temporary.name) / "private.png"
        target.write_bytes(image_bytes(covers.POSTER_SIZE))
        path = self.cache / (hashlib.sha256(URL.encode()).hexdigest() + ".png")
        try:
            path.symlink_to(target)
        except OSError:
            self.skipTest("Creating symlinks requires privileges on this host")
        before = target.read_bytes()
        _, session = self.load()
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse(path.is_symlink())

    def test_default_transport_pins_dns_verifies_tls_and_ignores_ambient_credentials(self):
        raw_socket = Mock()
        tls_socket = Mock()
        context = Mock()
        context.wrap_socket.return_value = tls_socket
        payload = image_bytes()
        response = Mock(status=200, headers={"Content-Length": str(len(payload))})
        response.isclosed.return_value = False
        response.read1.side_effect = [payload, b""]
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.object(covers.socket, "socket", return_value=raw_socket) as create_socket, \
                patch.object(covers.ssl, "create_default_context", return_value=context) as create_context, \
                patch.object(covers.http.client, "HTTPConnection", return_value=connection), \
                patch.dict(os.environ, {
                    "HTTPS_PROXY": "http://proxy-user:proxy-secret@127.0.0.1:9",
                    "NETRC": "do-not-read", "OPENAI_API_KEY": "api-secret",
                }):
            result = covers.load_cover(URL, self.cache)
        self.assert_png(result.poster_png, covers.POSTER_SIZE)
        create_context.assert_called_once_with()
        context.wrap_socket.assert_called_once_with(raw_socket, server_hostname="covers.example")
        raw_socket.connect.assert_called_once_with(("8.8.8.8", 443))
        create_socket.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        self.dns.assert_called_once()
        headers = connection.request.call_args.kwargs["headers"]
        self.assertFalse({"Authorization", "Proxy-Authorization", "Cookie", "X-API-Key"} & headers.keys())
        self.assertNotIn("proxy-secret", repr(connection.request.call_args))
        self.assertNotIn("api-secret", repr(connection.request.call_args))
        self.assertIs(connection.sock, tls_socket)
        response.close.assert_called_once()
        connection.close.assert_called_once()
        tls_socket.close.assert_called_once()

    def test_default_http_transport_never_creates_tls_or_re_resolves(self):
        payload = image_bytes()
        response = Mock(status=200, headers={})
        response.isclosed.return_value = False
        response.read1.side_effect = [payload, b""]
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.object(covers.socket, "socket", return_value=Mock()), \
                patch.object(covers.ssl, "create_default_context") as context, \
                patch.object(covers.http.client, "HTTPConnection", return_value=connection):
            covers.load_cover("http://covers.example/cover.png", self.cache)
        context.assert_not_called()
        self.dns.assert_called_once()

    def test_unreachable_ipv6_falls_back_to_vetted_ipv4_with_verified_tls(self):
        ipv6 = (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                ("2606:4700:4700::1111", 443, 0, 0))
        self.dns.return_value = [ipv6, ipv6] + PUBLIC_DNS
        unreachable = Mock()
        unreachable.connect.side_effect = OSError("IPv6 unavailable")
        reachable = Mock()
        secured = Mock()
        context = Mock()
        context.wrap_socket.return_value = secured
        payload = image_bytes()
        response = Mock(status=200, headers={})
        response.isclosed.return_value = False
        response.read1.side_effect = [payload, b""]
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.object(covers.socket, "socket", side_effect=[unreachable, reachable]) as create_socket, \
                patch.object(covers.ssl, "create_default_context", return_value=context) as create_context, \
                patch.object(covers.http.client, "HTTPConnection", return_value=connection):
            result = covers.load_cover(URL, self.cache)
        self.assert_png(result.poster_png, covers.POSTER_SIZE)
        self.dns.assert_called_once()
        self.assertEqual(create_socket.call_count, 2)
        unreachable.connect.assert_called_once_with(ipv6[4])
        self.assertLess(unreachable.settimeout.call_args.args[0], covers.CONNECT_TIMEOUT)
        unreachable.close.assert_called_once()
        reachable.connect.assert_called_once_with(PUBLIC_DNS[0][4])
        create_context.assert_called_once_with()
        context.wrap_socket.assert_called_once_with(reachable, server_hostname="covers.example")
        secured.close.assert_called_once()

    def test_real_socket_final_content_is_retained_after_response_closes_socket(self):
        payload = image_bytes()
        wire = (b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: "
                + str(len(payload)).encode() + b"\r\n\r\n" + payload)
        real_read1 = http.client.HTTPResponse.read1
        for proxy in (False, True):
            with self.subTest(proxy=proxy), self.wire_transport(wire, proxy=proxy) as sock:
                reads = []

                def observe_read1(response, size):
                    chunk = real_read1(response, size)
                    reads.append((chunk, response.isclosed(), sock.fileno()))
                    return chunk

                url = f"http://covers.example/close-{proxy}.png"
                with patch.object(http.client.HTTPResponse, "read1", observe_read1), \
                        patch.object(covers, "_CHUNK_SIZE", 32):
                    result = covers.load_cover(url, self.cache)
                self.assertGreater(len(reads), 1)
                self.assertEqual(b"".join(chunk for chunk, _, _ in reads), payload)
                self.assertTrue(reads[-1][0])  # Final bytes arrive with no live socket.
                self.assertEqual(reads[-1][1:], (True, -1))
                self.assert_png(result.thumbnail_png, covers.THUMBNAIL_SIZE)
                self.assert_png(result.poster_png, covers.POSTER_SIZE)
                cache_file = self.cache / (hashlib.sha256(url.encode()).hexdigest() + ".png")
                self.assertEqual(cache_file.read_bytes(), result.poster_png)

    def test_real_socket_eof_framing_and_truncation_for_both_transports(self):
        payload = image_bytes()
        cases = (
            ("eof", b"", payload),
            ("chunked", b"Transfer-Encoding: chunked\r\n",
             f"{len(payload):x}\r\n".encode() + payload + b"\r\n0\r\n\r\n"),
            ("truncated", f"Content-Length: {len(payload) + 1}\r\n".encode(), payload),
        )
        url = "http://covers.example/eof.png"
        target = covers._validate_url(url)
        for proxy in (False, True):
            for framing, headers, body in cases:
                wire = b"HTTP/1.1 200 OK\r\nConnection: close\r\n" + headers + b"\r\n" + body
                with self.subTest(proxy=proxy, framing=framing), \
                        self.wire_transport(wire, proxy=proxy):
                    if framing == "truncated":
                        with self.assertRaisesRegex(covers.CoverError, "Incomplete cover download"):
                            covers._download(url, target, None)
                    else:
                        self.assertEqual(covers._download(url, target, None), payload)

    def test_both_tls_transports_load_portable_roots_without_disabling_verification(self):
        target = covers._validate_url(URL)
        for proxy in (False, True):
            with self.subTest(proxy=proxy):
                # Model a relocated bundle with no platform CA installation.
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                self.assertEqual(context.cert_store_stats()["x509_ca"], 0)
                raw_socket, secured = Mock(), Mock()
                connection = Mock(sock=raw_socket)
                with patch.object(covers.ssl, "create_default_context", return_value=context) as create, \
                        patch.object(context, "load_verify_locations", wraps=context.load_verify_locations) as load, \
                        patch.object(context, "wrap_socket", return_value=secured) as wrap, \
                        patch.object(covers.socket, "socket", return_value=raw_socket), \
                        patch.object(covers.http.client, "HTTPConnection", return_value=connection):
                    if proxy:
                        covers._proxy_connection(target, PUBLIC_DNS, covers._Proxy("127.0.0.1", 7892))
                    else:
                        covers._connect_public(target, PUBLIC_DNS)
                create.assert_called_once_with()
                load.assert_called_once_with(cafile=certifi.where())
                self.assertGreater(context.cert_store_stats()["x509_ca"], 0)
                self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                self.assertTrue(context.check_hostname)
                wrap.assert_called_once_with(raw_socket, server_hostname=target.host)

    def test_address_fallback_has_one_shared_connect_budget(self):
        first = Mock()
        first.connect.side_effect = TimeoutError("connect timed out")
        target = covers._validate_url("http://covers.example/cover.png")
        with patch.object(covers.socket, "socket", return_value=first) as create_socket, \
                patch.object(covers.time, "monotonic", side_effect=[0, 1, covers.CONNECT_TIMEOUT + 1]):
            with self.assertRaises(covers.CoverError):
                covers._connect_public(target, PUBLIC_DNS * 2)
        create_socket.assert_called_once()
        first.settimeout.assert_called_once_with(covers._CONNECT_ATTEMPT_TIMEOUT)
        first.close.assert_called_once()

    def test_readonly_cache_hit_remains_available_offline(self):
        original, _ = self.load()
        self.dns.side_effect = OSError("offline")
        with patch.object(Path, "touch", side_effect=PermissionError("read-only cache")):
            cached = covers.load_cover(URL, self.cache, session=FakeSession(error=AssertionError("HTTP")))
        self.assertEqual(cached, original)

    def test_only_bare_unauthenticated_loopback_http_proxies_are_accepted(self):
        for value, host, port in [
            ("http://127.0.0.1:7892", "127.0.0.1", 7892),
            ("http://localhost:7892", "127.0.0.1", 7892),
            ("http://[::1]:7892", "::1", 7892),
            ("http://127.0.0.1", "127.0.0.1", 80),
        ]:
            with self.subTest(value=value):
                self.assertEqual(covers._parse_proxy(value), covers._Proxy(host, port))
        for value in [
            None, "", "127.0.0.1:7892", "https://127.0.0.1:7892",
            "socks5://127.0.0.1:7892", "http://user:secret@127.0.0.1:7892",
            "http://@127.0.0.1:7892", "http://127.0.0.1:7892/",
            "http://127.0.0.1:7892/path", "http://127.0.0.1:7892?key=secret",
            "http://127.0.0.1:7892#secret", "http://127.0.0.1:7892?",
            "http://127.0.0.1:7892#", "http://proxy.example:7892",
            "http://8.8.8.8:7892", "http://192.168.1.1:7892", "http://127.0.0.2:7892",
            "http://localhost.example:7892", "http://localhost.:7892", "http://2130706433:7892",
            "http://[::ffff:127.0.0.1]:7892", "http://%6cocalhost:7892",
            "http://127.0.0.1:7892\n", "http://127.0.0.1:7892\x00",
            "http://127.0.0.1:0", "http://127.0.0.1:65536", "http://127.0.0.1:",
        ]:
            with self.subTest(value=value):
                self.assertIsNone(covers._parse_proxy(value))
        self.dns.assert_not_called()

    def test_proxy_discovery_ignores_invalid_entries_and_uses_valid_existing_local_proxy(self):
        self.proxy_patcher.stop()
        target = covers._validate_url(URL)
        with patch.object(covers, "getproxies", return_value={
            "https": "http://user:secret@127.0.0.1:9",
            "http": "http://localhost:7892", "all": "http://proxy.example:8080",
        }) as discovery:
            self.assertEqual(covers._configured_proxy(target), covers._Proxy("127.0.0.1", 7892))
            discovery.assert_called_once_with()
        with patch.object(covers, "getproxies", return_value={"https": "http://proxy.example:8080"}):
            self.assertIsNone(covers._configured_proxy(target))
        with patch.object(covers, "getproxies", side_effect=OSError("system discovery unavailable")):
            self.assertIsNone(covers._configured_proxy(target))
        self.dns.assert_not_called()

    def test_cache_hit_does_not_discover_proxies_or_access_network(self):
        original, _ = self.load()
        self.proxy_discovery.side_effect = AssertionError("Proxy discovery on cache hit")
        self.dns.side_effect = AssertionError("DNS on cache hit")
        self.assertEqual(covers.load_cover(URL, self.cache), original)
        self.proxy_discovery.assert_not_called()

    def test_https_proxy_wire_connects_numeric_ip_uses_original_sni_and_never_sends_auth(self):
        self.proxy_discovery.return_value = covers._Proxy("127.0.0.1", 7892)
        payload = image_bytes()
        sock = Mock()
        sock.makefile.side_effect = [
            BytesIO(b"HTTP/1.1 200 Connection established\r\n\r\n"),
            BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(payload)).encode()
                    + b"\r\nConnection: close\r\n\r\n" + payload),
        ]
        context = Mock()
        context.wrap_socket.return_value = sock
        with patch.object(covers.socket, "create_connection", return_value=sock) as connect, \
                patch.object(covers.ssl, "create_default_context", return_value=context) as create_context, \
                patch.object(covers, "_connect_public", side_effect=AssertionError("Used direct route")), \
                patch.dict(os.environ, {"NETRC": "must-not-read", "OPENAI_API_KEY": "api-secret",
                                       "HTTPS_PROXY": "http://user:proxy-secret@remote.example:9"}):
            result = covers.load_cover(URL, self.cache)
        self.assert_png(result.thumbnail_png, covers.THUMBNAIL_SIZE)
        self.assert_png(result.poster_png, covers.POSTER_SIZE)
        self.assertEqual(connect.call_args.args[0], ("127.0.0.1", 7892))
        self.assertLessEqual(connect.call_args.args[1], covers._CONNECT_ATTEMPT_TIMEOUT)
        self.dns.assert_called_once()
        create_context.assert_called_once_with()
        context.wrap_socket.assert_called_once_with(sock, server_hostname="covers.example")
        wire = b"".join(call.args[0] for call in sock.sendall.call_args_list)
        self.assertIn(b"CONNECT 8.8.8.8:443 HTTP/1.1\r\n", wire)
        self.assertIn(b"Host: 8.8.8.8:443\r\n", wire)
        self.assertIn(b"GET /art.png?token=private-secret HTTP/1.1\r\n", wire)
        self.assertIn(b"Host: covers.example\r\n", wire)
        for forbidden in (b"Authorization", b"Cookie", b"api-secret", b"proxy-secret", b"X-API-Key"):
            self.assertNotIn(forbidden, wire)
        sock.close.assert_called()

    def test_http_proxy_wire_uses_absolute_numeric_ipv6_uri_and_original_host(self):
        self.proxy_discovery.return_value = covers._Proxy("::1", 7892)
        self.dns.return_value = [(socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                                  ("2606:4700:4700::1111", 8080, 0, 0))]
        payload = image_bytes()
        sock = Mock()
        sock.makefile.return_value = BytesIO(
            b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(payload)).encode()
            + b"\r\nConnection: close\r\n\r\n" + payload
        )
        with patch.object(covers.socket, "create_connection", return_value=sock) as connect, \
                patch.object(covers.ssl, "create_default_context") as context:
            result = covers.load_cover("http://covers.example:8080/art.png", self.cache)
        self.assert_png(result.poster_png, covers.POSTER_SIZE)
        context.assert_not_called()
        self.assertEqual(connect.call_args.args[0], ("::1", 7892))
        self.dns.assert_called_once()
        wire = b"".join(call.args[0] for call in sock.sendall.call_args_list)
        self.assertIn(b"GET http://[2606:4700:4700::1111]:8080/art.png HTTP/1.1\r\n", wire)
        self.assertIn(b"Host: covers.example:8080\r\n", wire)
        self.assertNotIn(b"CONNECT ", wire)
        self.assertNotIn(b"Authorization", wire)

    def test_proxy_never_bypasses_public_destination_validation(self):
        self.proxy_discovery.return_value = covers._Proxy("127.0.0.1", 7892)
        self.dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                                  ("169.254.169.254", 443))]
        with self.assertRaises(covers.CoverError):
            covers.load_cover(URL, self.cache)
        self.proxy_discovery.assert_not_called()
        self.socket.assert_not_called()

    def test_proxy_tls_failure_does_not_retry_without_verification_or_leak_details(self):
        self.proxy_discovery.return_value = covers._Proxy("127.0.0.1", 7892)
        connection = Mock(sock=Mock())
        context = Mock()
        context.wrap_socket.side_effect = ssl.SSLError(URL)
        with patch.object(covers.http.client, "HTTPConnection", return_value=connection), \
                patch.object(covers.ssl, "create_default_context", return_value=context), \
                patch.object(covers, "_connect_public", side_effect=AssertionError("Direct retry")):
            with self.assertRaises(covers.CoverError) as error:
                covers.load_cover(URL, self.cache)
        self.assertNotIn("private-secret", str(error.exception))
        context.wrap_socket.assert_called_once_with(connection.sock, server_hostname="covers.example")
        connection.request.assert_not_called()
        connection.close.assert_called_once()

    def test_hostname_connect_exception_is_exact_official_host_with_verified_original_sni(self):
        # This fixed exception is needed by hostname-routing local proxies. It
        # deliberately delegates resolution only for official Bangumi HTTPS;
        # lookalikes, suffixes and subdomains must remain numeric-IP pinned.
        self.proxy_discovery.return_value = covers._Proxy("127.0.0.1", 7892)
        for host in ("lain.bgm.tv", "lain.bgm.tv.attacker.test", "a.lain.bgm.tv", "notlain.bgm.tv"):
            with self.subTest(host=host):
                payload = image_bytes()
                sock = Mock()
                sock.makefile.side_effect = [
                    BytesIO(b"HTTP/1.1 200 Connection established\r\n\r\n"),
                    BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(payload)).encode()
                            + b"\r\nConnection: close\r\n\r\n" + payload),
                ]
                context = Mock()
                context.wrap_socket.return_value = sock
                before_dns = self.dns.call_count
                with patch.object(covers.socket, "create_connection", return_value=sock), \
                        patch.object(covers.ssl, "create_default_context", return_value=context) as create_context, \
                        patch.object(covers._LOGGER, "debug") as log:
                    result = covers.load_cover(f"https://{host}/cover.jpg", self.cache)
                self.assert_png(result.poster_png, covers.POSTER_SIZE)
                self.assertEqual(self.dns.call_count, before_dns + 1)
                create_context.assert_called_once_with()
                context.wrap_socket.assert_called_once_with(sock, server_hostname=host)
                wire = b"".join(call.args[0] for call in sock.sendall.call_args_list)
                destination = host if host == "lain.bgm.tv" else "8.8.8.8"
                self.assertIn(f"CONNECT {destination}:443 HTTP/1.1\r\n".encode(), wire)
                self.assertIn(f"Host: {host}\r\n".encode(), wire)
                self.assertNotIn(b"Authorization", wire)
                if host == "lain.bgm.tv":
                    log.assert_called_once()
                else:
                    log.assert_not_called()

    def test_official_provider_hostname_exception_does_not_apply_to_http(self):
        target = covers._validate_url("http://lain.bgm.tv/cover.jpg")
        connection = Mock(sock=Mock())
        with patch.object(covers.http.client, "HTTPConnection", return_value=connection), \
                patch.object(covers.ssl, "create_default_context") as context:
            _, resource = covers._proxy_connection(target, PUBLIC_DNS, covers._Proxy("127.0.0.1", 7892))
        connection.set_tunnel.assert_not_called()
        context.assert_not_called()
        self.assertEqual(resource, "http://8.8.8.8:80/cover.jpg")

    def test_official_provider_exception_still_rejects_nonpublic_dns_and_bad_certificates(self):
        self.proxy_discovery.return_value = covers._Proxy("127.0.0.1", 7892)
        self.dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                                  ("127.0.0.1", 443))]
        url = "https://lain.bgm.tv/cover.jpg?token=private-secret"
        with self.assertRaises(covers.CoverError):
            covers.load_cover(url, self.cache)
        self.proxy_discovery.assert_not_called()
        self.dns.return_value = PUBLIC_DNS
        connection = Mock(sock=Mock())
        context = Mock()
        context.wrap_socket.side_effect = ssl.SSLCertVerificationError("hostname mismatch")
        with patch.object(covers.http.client, "HTTPConnection", return_value=connection), \
                patch.object(covers.ssl, "create_default_context", return_value=context):
            with self.assertRaises(covers.CoverError):
                covers.load_cover(url, self.cache)
        connection.set_tunnel.assert_called_once_with("lain.bgm.tv", 443, headers={"Host": "lain.bgm.tv:443"})
        context.wrap_socket.assert_called_once_with(connection.sock, server_hostname="lain.bgm.tv")
        connection.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
