"""Bounded, UI-independent cover loading with an optional normalized PNG cache."""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import http.client
from io import BytesIO
import ipaddress
import logging
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import tempfile
import threading
import time
import unicodedata
from urllib.parse import quote, unquote, urlsplit
from urllib.request import getproxies
import warnings

import certifi
from PIL import Image, ImageOps


MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 12_000_000
MAX_CACHE_ENTRY_BYTES = 256 * 1024
MAX_CACHE_BYTES = 32 * 1024 * 1024
MAX_CACHE_FILES = 256
THUMBNAIL_SIZE = (54, 76)
POSTER_SIZE = (180, 254)
CONNECT_TIMEOUT = 5.0
_CONNECT_ATTEMPT_TIMEOUT = 2.0
READ_TIMEOUT = 5.0
DOWNLOAD_TIMEOUT = 30.0
_CHUNK_SIZE = 64 * 1024
_FORMATS = ("JPEG", "PNG", "WEBP", "GIF")
_BACKGROUND = (28, 30, 38)
_CACHE_NAME = re.compile(r"[0-9a-f]{64}\.png\Z")
_CACHE_LOCK = threading.RLock()
_LOGGER = logging.getLogger(__name__)
# Deliberate, exact-host HTTPS exception for Bangumi's official image provider.
# Some local proxies route this CDN only by hostname. Public DNS validation still
# precedes proxy discovery, but this exception delegates destination resolution
# to the trusted local proxy instead of pinning its CONNECT target to an IP.
# Verified TLS/SNI remains mandatory. Never expand this to suffix matching.
_HOSTNAME_CONNECT_HOSTS = frozenset({"lain.bgm.tv"})


class CoverError(RuntimeError):
    """A cover could not be loaded; messages deliberately omit remote URLs."""


@dataclass(frozen=True)
class CoverData:
    thumbnail_png: bytes
    poster_png: bytes


@dataclass(frozen=True)
class _Target:
    host: str
    port: int
    secure: bool
    resource: str


@dataclass(frozen=True)
class _Proxy:
    host: str
    port: int


def _parse_proxy(value) -> _Proxy | None:
    """Accept only bare, unauthenticated HTTP endpoints on exact loopback hosts."""
    if (not isinstance(value, str) or not value or len(value) > 2048
            or any(char.isspace() or unicodedata.category(char).startswith("C") for char in value)
            or any(char in value for char in "@%\\?#")):
        return None
    try:
        parts = urlsplit(value)
        if (parts.scheme != "http" or parts.path or parts.query or parts.fragment
                or parts.hostname not in ("127.0.0.1", "::1", "localhost")
                or parts.netloc.endswith(":")):
            return None
        port = parts.port if parts.port is not None else 80
        if not 1 <= port <= 65535:
            return None
        # Do not resolve even 'localhost': keep the proxy connection loopback-pinned.
        return _Proxy("127.0.0.1" if parts.hostname == "localhost" else parts.hostname, port)
    except (ValueError, UnicodeError):
        return None


def _configured_proxy(target: _Target) -> _Proxy | None:
    """Read existing proxy discovery only; never import credentials or settings."""
    try:
        configured = getproxies()
        keys = ("https", "http", "all") if target.secure else ("http", "https", "all")
        for key in keys:
            proxy = _parse_proxy(configured.get(key))
            if proxy is not None:
                return proxy
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def _validate_url(url: str) -> _Target:
    def has_control(value):
        return any(unicodedata.category(char).startswith("C") for char in value)

    if (not isinstance(url, str) or not url or len(url) > 8192
            or has_control(url) or any(char.isspace() for char in url)
            or "\\" in url or has_control(unquote(url))):
        raise CoverError("Invalid cover address.")
    try:
        parts = urlsplit(url)
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or "@" in parts.netloc or "%" in parts.netloc):
            raise ValueError
        host = parts.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        secure = parts.scheme == "https"
        port = parts.port if parts.port is not None else (443 if secure else 80)
        if not 1 <= port <= 65535 or parts.netloc.endswith(":"):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise CoverError("IP-literal cover addresses are not allowed.")
        labels = host.split(".")
        if (len(host) > 253 or len(labels) < 2
                or not re.search(r"[a-z]", labels[-1])
                or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                       for label in labels)
                or host == "localhost"
                or host.endswith((".localhost", ".local", ".internal", ".lan", ".home"))):
            raise ValueError
        resource = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
        if parts.query:
            resource += "?" + quote(parts.query, safe="/%?:@!$&'()*+,;=-._~")
        return _Target(host, port, secure, resource)
    except (ValueError, UnicodeError):
        raise CoverError("Invalid or nonpublic cover address.") from None


def _public_addresses(target: _Target) -> list:
    try:
        addresses = socket.getaddrinfo(
            target.host, target.port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
        if not addresses or len(addresses) > 64:
            raise ValueError
        for family, kind, protocol, _, address in addresses:
            ip = ipaddress.ip_address(address[0])
            if (family not in (socket.AF_INET, socket.AF_INET6)
                    or kind != socket.SOCK_STREAM or protocol != socket.IPPROTO_TCP
                    or not ip.is_global or ip.is_multicast or ip.is_reserved
                    or "%" in address[0]):
                raise ValueError
            if isinstance(ip, ipaddress.IPv6Address) and (
                ip.ipv4_mapped is not None or ip.sixtofour is not None
                or ip.teredo is not None
                or ip in ipaddress.ip_network("64:ff9b::/96")
                or ip in ipaddress.ip_network("64:ff9b:1::/48")
            ):
                raise ValueError
        return addresses
    except (OSError, ValueError, TypeError, IndexError):
        raise CoverError("Cover host did not resolve to public addresses.") from None


def _connect_public(target: _Target, addresses: list):
    """Try vetted addresses, sharing one budget across TCP and TLS attempts."""
    deadline = time.monotonic() + CONNECT_TIMEOUT
    context = ssl.create_default_context() if target.secure else None
    if context is not None:
        # Frozen apps cannot rely on the build machine's OpenSSL CA paths.
        # Supplement platform trust without disabling certificate/hostname checks.
        context.load_verify_locations(cafile=certifi.where())
        context.set_alpn_protocols(["http/1.1"])
    # Give the other address family an early chance, even when DNS lists many
    # unreachable IPv6 addresses before a working IPv4 destination (or vice versa).
    first_family = addresses[0][0]
    addresses = (addresses[:1]
                 + [item for item in addresses[1:] if item[0] != first_family]
                 + [item for item in addresses[1:] if item[0] == first_family])
    for family, kind, protocol, _, address in addresses:
        now = time.monotonic()
        remaining = deadline - now
        if remaining <= 0:
            break
        attempt_deadline = min(deadline, now + _CONNECT_ATTEMPT_TIMEOUT)
        sock = None
        try:
            sock = socket.socket(family, kind, protocol)
            sock.settimeout(attempt_deadline - now)
            sock.connect(address)
            if context is not None:
                remaining = attempt_deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                sock.settimeout(remaining)
                sock = context.wrap_socket(sock, server_hostname=target.host)
            return sock
        except OSError:
            if sock is not None:
                sock.close()
    raise CoverError("Unable to connect to cover host.") from None


def _headers(target: _Target) -> dict[str, str]:
    host = target.host
    if target.port != (443 if target.secure else 80):
        host += f":{target.port}"
    return {
        "Host": host,
        "Accept": "image/png,image/jpeg,image/webp,image/gif",
        "Accept-Encoding": "identity",
        "User-Agent": "ZFZS-Covers/1.0",
        "Connection": "close",
    }


@contextmanager
def _direct_response(target: _Target, addresses: list):
    """No proxy/netrc/ambient auth; pinned sockaddrs prevent DNS rebinding."""
    connection = http.client.HTTPConnection(target.host, target.port, timeout=READ_TIMEOUT)
    sock = _connect_public(target, addresses)
    try:
        sock.settimeout(READ_TIMEOUT)
        connection.sock = sock
        connection.request("GET", target.resource, headers=_headers(target))
        response = connection.getresponse()
        try:
            yield response, sock
        finally:
            response.close()
    finally:
        connection.close()
        sock.close()


def _proxy_connection(target: _Target, addresses: list, proxy: _Proxy):
    """Pin CONNECT to public IPs except the documented official-provider case."""
    deadline = time.monotonic() + CONNECT_TIMEOUT
    hostname_connect = target.secure and target.host in _HOSTNAME_CONNECT_HOSTS
    if hostname_connect:
        _LOGGER.debug(
            "Using hostname CONNECT for trusted provider lain.bgm.tv; "
            "public DNS validation and verified TLS are still required."
        )
    context = ssl.create_default_context() if target.secure else None
    if context is not None:
        context.load_verify_locations(cafile=certifi.where())
        context.set_alpn_protocols(["http/1.1"])
    first_family = addresses[0][0]
    ordered = (addresses[:1]
               + [item for item in addresses[1:] if item[0] != first_family]
               + [item for item in addresses[1:] if item[0] == first_family])
    if hostname_connect:
        ordered = ordered[:1]  # One hostname tunnel, not duplicate IP attempts.
    for _, _, _, _, address in ordered:
        now = time.monotonic()
        if now >= deadline:
            break
        attempt_deadline = (deadline if hostname_connect
                            else min(deadline, now + _CONNECT_ATTEMPT_TIMEOUT))
        connection = http.client.HTTPConnection(proxy.host, proxy.port, timeout=attempt_deadline - now)
        try:
            connect_host = target.host if hostname_connect else address[0]
            authority = (f"[{connect_host}]:{target.port}" if ":" in connect_host
                         else f"{connect_host}:{target.port}")
            if target.secure:
                connection.set_tunnel(connect_host, target.port, headers={"Host": authority})
            connection.connect()
            sock = connection.sock
            if context is not None:
                remaining = attempt_deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                sock.settimeout(remaining)
                connection.sock = context.wrap_socket(sock, server_hostname=target.host)
            resource = target.resource if target.secure else f"http://{authority}{target.resource}"
            return connection, resource
        except (OSError, http.client.HTTPException):
            connection.close()
    raise CoverError("Unable to connect through local cover proxy.") from None


@contextmanager
def _proxy_response(target: _Target, addresses: list, proxy: _Proxy):
    connection, resource = _proxy_connection(target, addresses, proxy)
    sock = connection.sock
    try:
        sock.settimeout(READ_TIMEOUT)
        connection.request("GET", resource, headers=_headers(target))
        response = connection.getresponse()
        try:
            yield response, sock
        finally:
            response.close()
    finally:
        connection.close()
        sock.close()


def _read_response(status, headers, chunks) -> bytes:
    # Redirects are intentionally refused, even when their destination is public.
    if status != 200:
        raise CoverError("Cover server returned an unsuccessful response.")
    encoding = headers.get("Content-Encoding", "identity").strip().lower()
    if encoding not in ("", "identity"):
        raise CoverError("Encoded cover responses are not supported.")
    length = headers.get("Content-Length")
    if length is not None:
        if not re.fullmatch(r"[0-9]{1,10}", str(length)):
            raise CoverError("Invalid cover response size.")
        length = int(length)
        if length > MAX_DOWNLOAD_BYTES:
            raise CoverError("Cover download is too large.")
    data = bytearray()
    deadline = time.monotonic() + DOWNLOAD_TIMEOUT
    for chunk in chunks:
        if time.monotonic() > deadline:
            raise CoverError("Cover download timed out.")
        if not isinstance(chunk, bytes) or len(data) + len(chunk) > MAX_DOWNLOAD_BYTES:
            raise CoverError("Cover download is too large or invalid.")
        data.extend(chunk)
    if not data or (length is not None and len(data) != length):
        raise CoverError("Incomplete cover download.")
    return bytes(data)


def _download(url: str, target: _Target, session) -> bytes:
    addresses = _public_addresses(target)
    try:
        if session is not None:
            # The caller owns injected sessions. This requests-compatible seam is
            # intended for offline tests, not for inheriting app/API sessions.
            response = session.get(
                url, stream=True, allow_redirects=False, verify=True,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                headers={"Accept-Encoding": "identity"},
            )
            try:
                return _read_response(
                    response.status_code, response.headers,
                    response.iter_content(chunk_size=_CHUNK_SIZE),
                )
            finally:
                response.close()
        proxy = _configured_proxy(target)
        transport = (_proxy_response(target, addresses, proxy) if proxy is not None
                     else _direct_response(target, addresses))
        with transport as (response, sock):
            def chunks():
                deadline = time.monotonic() + DOWNLOAD_TIMEOUT
                # A final Content-Length read can close the response AND socket.
                # Stop before setting a timeout on that now-closed socket.
                while not response.isclosed():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise CoverError("Cover download timed out.")
                    sock.settimeout(min(READ_TIMEOUT, remaining))
                    chunk = response.read1(min(_CHUNK_SIZE, MAX_DOWNLOAD_BYTES + 1))
                    if not chunk:
                        break
                    yield chunk

            return _read_response(response.status, response.headers, chunks())
    except CoverError:
        raise
    except Exception:
        # Exception strings/chains can contain signed URLs or credentials.
        raise CoverError("Unable to download cover image.") from None


def _png(image: Image.Image) -> bytes:
    with BytesIO() as output:
        image.save(output, format="PNG")
        return output.getvalue()


def _letterbox(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.pad(image, size, method=Image.Resampling.LANCZOS, color=_BACKGROUND)


def _decode(data: bytes, *, cached: bool = False) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data), formats=("PNG",) if cached else _FORMATS) as image:
                width, height = image.size
                if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                    raise ValueError
                if cached and (image.size != POSTER_SIZE or image.mode != "RGB"
                               or getattr(image, "n_frames", 1) != 1):
                    raise ValueError
                image.verify()
            with Image.open(BytesIO(data), formats=("PNG",) if cached else _FORMATS) as image:
                image.load()  # Only the first frame of animated covers is used.
                oriented = ImageOps.exif_transpose(image)
                # Composite transparent pixels against the same letterbox color.
                rgba = oriented.convert("RGBA")
                rgb = Image.new("RGB", rgba.size, _BACKGROUND)
                rgb.paste(rgba, mask=rgba.getchannel("A"))
                rgba.close()
                if oriented is not image:
                    oriented.close()
                return rgb
    except Exception:
        raise CoverError("Invalid, unsupported, or oversized cover image.") from None


def _prune_cache(cache_dir: Path) -> None:
    """Evict only this service's hash-named files; leave unrelated data alone."""
    entries = []
    for path in cache_dir.iterdir():
        if not _CACHE_NAME.fullmatch(path.name):
            continue
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                continue
            if info.st_size > MAX_CACHE_ENTRY_BYTES:
                path.unlink()
                continue
            entries.append((info.st_mtime_ns, path.name, path, info.st_size))
        except OSError:
            continue
    total = sum(entry[3] for entry in entries)
    count = len(entries)
    for _, _, path, size in sorted(entries):
        if count <= MAX_CACHE_FILES and total <= MAX_CACHE_BYTES:
            break
        path.unlink(missing_ok=True)
        total -= size
        count -= 1


def _read_cache(path: Path) -> bytes | None:
    with _CACHE_LOCK:
        try:
            _prune_cache(path.parent)
            if not stat.S_ISREG(path.lstat().st_mode):
                return None
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            with os.fdopen(os.open(path, flags), "rb") as source:
                if os.fstat(source.fileno()).st_size > MAX_CACHE_ENTRY_BYTES:
                    return None
                data = source.read(MAX_CACHE_ENTRY_BYTES + 1)
            if len(data) > MAX_CACHE_ENTRY_BYTES:
                return None
            with _decode(data, cached=True):
                pass
            try:
                path.touch()
            except OSError:
                pass  # Valid read-only entries must still work offline.
            return data
        except CoverError:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        except OSError:
            pass
    return None


def _write_cache(path: Path, data: bytes) -> None:
    temporary = None
    with _CACHE_LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if len(data) > MAX_CACHE_ENTRY_BYTES:
                return
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".cover-", suffix=".tmp", delete=False
            ) as output:
                temporary = Path(output.name)
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            _prune_cache(path.parent)
        except OSError:
            pass  # A read-only/full cache must not prevent displaying a cover.
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass


def load_cover(url: str, cache_dir: Path, *, session=None) -> CoverData:
    """Return exact RGB PNG variants; cache hits never perform DNS or HTTP.

    Cache entries contain only a normalized 180x254 RGB PNG, named by SHA256
    of the complete URL. Deriving thumbnails from that poster makes hits and
    misses identical. Cache I/O is best-effort; invalid input/downloads raise
    CoverError. No UI objects or user-database state are involved.
    """
    target = _validate_url(url)
    path = Path(cache_dir) / (hashlib.sha256(url.encode("utf-8")).hexdigest() + ".png")
    poster_png = _read_cache(path)
    if poster_png is None:
        with _decode(_download(url, target, session)) as image:
            with _letterbox(image, POSTER_SIZE) as poster:
                poster_png = _png(poster)
        _write_cache(path, poster_png)
    with _decode(poster_png, cached=True) as poster:
        with _letterbox(poster, THUMBNAIL_SIZE) as thumbnail:
            return CoverData(thumbnail_png=_png(thumbnail), poster_png=poster_png)
