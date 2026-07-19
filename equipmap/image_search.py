"""장비 모델 이미지를 웹(Google CSE / DuckDuckGo / Wikimedia)에서 찾아 저장."""

from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from io import BytesIO
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode, urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageOps, UnidentifiedImageError


COMMONS_API = "https://commons.wikimedia.org/w/api.php"
GOOGLE_CSE_API = "https://www.googleapis.com/customsearch/v1"
USER_AGENT = (
    "Mozilla/5.0 (compatible; EquipMap/1.0; "
    "+https://localhost; equipment layout application)"
)
MAX_DOWNLOAD_BYTES = 12 * 1024 * 1024
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/jpg"}


class ImageSearchError(RuntimeError):
    """검색 결과나 유효한 이미지를 얻지 못한 경우."""


@dataclass(frozen=True)
class SavedEquipmentImage:
    filename: str
    source_url: str
    title: str
    source_label: str = ""


def google_images_search_url(query: str) -> str:
    return (
        "https://www.google.com/search?"
        + urlencode({"tbm": "isch", "q": query.strip()})
    )


def _request_bytes(url: str, *, timeout: float = 15) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_DOWNLOAD_BYTES:
            raise ImageSearchError("검색된 이미지 파일이 너무 큽니다.")
        content = response.read(MAX_DOWNLOAD_BYTES + 1)
    if len(content) > MAX_DOWNLOAD_BYTES:
        raise ImageSearchError("검색된 이미지 파일이 너무 큽니다.")
    return content


def _request_json(url: str, *, timeout: float = 12) -> dict:
    content = _request_bytes(url, timeout=timeout)
    return json.loads(content.decode("utf-8", errors="replace"))


def _request_text(url: str, *, timeout: float = 12) -> str:
    return _request_bytes(url, timeout=timeout).decode("utf-8", errors="replace")


def _host_label(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if "google." in host:
        return "Google"
    if "wikimedia.org" in host or "wikipedia.org" in host:
        return "Wikimedia"
    if "duckduckgo.com" in host:
        return "DuckDuckGo"
    return host or "웹"


def _download_image(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ImageSearchError("허용되지 않은 이미지 주소입니다.")
    blocked = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
    if parsed.hostname in blocked or parsed.hostname.endswith(".local"):
        raise ImageSearchError("허용되지 않은 이미지 주소입니다.")
    return _request_bytes(url, timeout=15)


def _candidate_score(page: dict, query: str) -> int:
    title = str(page.get("title", "")).removeprefix("File:").lower()
    normalized_query = query.lower()
    score = -int(page.get("index", 10_000))
    if title.startswith(normalized_query):
        score += 200
    query_tokens = re.findall(r"[a-z0-9]+", normalized_query)
    score += sum(12 for token in query_tokens if token in title)
    detail_terms = (
        "chip",
        "broadcom",
        "processor",
        "circuit",
        "pcb",
        "inside",
        "detail",
        "connector",
    )
    score -= sum(80 for term in detail_terms if term in title)
    return score


def save_equipment_image_content(
    content: bytes,
    *,
    db_id: int,
    target_directory: Path,
) -> str:
    if not content:
        raise ImageSearchError("이미지 파일이 비어 있습니다.")
    if len(content) > MAX_DOWNLOAD_BYTES:
        raise ImageSearchError("이미지 파일은 12MB 이하여야 합니다.")
    try:
        with Image.open(BytesIO(content)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise ImageSearchError("JPEG, PNG, WebP 이미지만 등록할 수 있습니다.")
            image = ImageOps.exif_transpose(source)
            image.thumbnail((1000, 760), Image.Resampling.LANCZOS)
            if image.mode in {"RGBA", "LA"}:
                background = Image.new("RGB", image.size, "#FFFFFF")
                alpha = image.getchannel("A")
                background.paste(image.convert("RGB"), mask=alpha)
                image = background
            else:
                image = image.convert("RGB")

            target_directory.mkdir(parents=True, exist_ok=True)
            filename = f"equipment_{int(db_id)}.jpg"
            image.save(
                target_directory / filename,
                "JPEG",
                quality=88,
                optimize=True,
            )
            return filename
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ImageSearchError(f"유효한 이미지 파일이 아닙니다: {error}") from error


def _google_cse_candidates(query: str) -> list[dict]:
    api_key = os.environ.get("GOOGLE_CSE_API_KEY", "").strip()
    cx = os.environ.get("GOOGLE_CSE_CX", "").strip()
    if not api_key or not cx:
        return []
    parameters = urlencode(
        {
            "key": api_key,
            "cx": cx,
            "q": query,
            "searchType": "image",
            "num": 8,
            "safe": "active",
            "fileType": "jpg,png",
        }
    )
    try:
        payload = _request_json(f"{GOOGLE_CSE_API}?{parameters}")
    except (OSError, TimeoutError, ValueError, HTTPError, URLError):
        return []
    items = payload.get("items") or []
    results: list[dict] = []
    for item in items:
        image = item.get("image") or {}
        image_url = str(item.get("link") or image.get("thumbnailLink") or "")
        source_url = str(
            item.get("image", {}).get("contextLink")
            or item.get("displayLink")
            or google_images_search_url(query)
        )
        if not image_url:
            continue
        results.append(
            {
                "image_url": image_url,
                "source_url": source_url,
                "title": str(item.get("title") or query),
                "label": "Google",
            }
        )
    return results


def _duckduckgo_vqd(query: str) -> str:
    html = _request_text(f"https://duckduckgo.com/?q={quote_plus(query)}&iax=images&ia=images")
    patterns = (
        r'vqd="([^"]+)"',
        r"vqd='([^']+)'",
        r"vqd=([\d-]+)&",
    )
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return unescape(match.group(1))
    raise ImageSearchError("웹 이미지 검색 토큰을 얻지 못했습니다.")


def _duckduckgo_candidates(query: str) -> list[dict]:
    try:
        vqd = _duckduckgo_vqd(query)
        parameters = urlencode(
            {
                "l": "us-en",
                "o": "json",
                "q": query,
                "vqd": vqd,
                "f": ",,,",
                "p": "1",
            }
        )
        payload = _request_json(
            f"https://duckduckgo.com/i.js?{parameters}",
            timeout=15,
        )
    except (OSError, TimeoutError, ValueError, HTTPError, URLError, ImageSearchError):
        return []
    results: list[dict] = []
    for item in payload.get("results") or []:
        image_url = str(item.get("image") or item.get("thumbnail") or "")
        source_url = str(item.get("url") or item.get("source") or "")
        if not image_url:
            continue
        if not source_url:
            source_url = google_images_search_url(query)
        results.append(
            {
                "image_url": image_url,
                "source_url": source_url,
                "title": str(item.get("title") or query),
                "label": _host_label(source_url) or "웹",
            }
        )
    return results


def _wikimedia_candidates(query: str) -> list[dict]:
    parameters = urlencode(
        {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": 6,
            "gsrlimit": 12,
            "prop": "imageinfo",
            "iiprop": "url|mime",
            "iiurlwidth": 1000,
            "format": "json",
            "formatversion": 2,
        }
    )
    try:
        payload = _request_json(f"{COMMONS_API}?{parameters}")
    except (OSError, TimeoutError, ValueError, HTTPError, URLError):
        return []
    pages = payload.get("query", {}).get("pages", [])
    pages = sorted(
        pages,
        key=lambda page: _candidate_score(page, query),
        reverse=True,
    )
    results: list[dict] = []
    for page in pages:
        info_list = page.get("imageinfo") or []
        if not info_list:
            continue
        info = info_list[0]
        mime = str(info.get("mime", ""))
        if mime not in ALLOWED_MIME:
            continue
        image_url = str(info.get("thumburl") or info.get("url") or "")
        source_url = str(info.get("descriptionurl") or image_url)
        if not image_url:
            continue
        results.append(
            {
                "image_url": image_url,
                "source_url": source_url,
                "title": str(page.get("title", query)),
                "label": "Wikimedia",
            }
        )
    return results


def _save_first_candidate(
    candidates: list[dict],
    *,
    db_id: int,
    target_directory: Path,
) -> SavedEquipmentImage | None:
    last_error: Exception | None = None
    for item in candidates:
        try:
            content = _download_image(item["image_url"])
            filename = save_equipment_image_content(
                content,
                db_id=db_id,
                target_directory=target_directory,
            )
            source_url = str(item.get("source_url") or item["image_url"])
            return SavedEquipmentImage(
                filename=filename,
                source_url=source_url,
                title=str(item.get("title") or ""),
                source_label=str(item.get("label") or _host_label(source_url)),
            )
        except (
            ImageSearchError,
            OSError,
            UnidentifiedImageError,
            ValueError,
            HTTPError,
            URLError,
        ) as error:
            last_error = error
            continue
    if last_error is not None:
        raise ImageSearchError(
            f"사용 가능한 이미지를 저장하지 못했습니다: {last_error}"
        )
    return None


def search_and_save_equipment_image(
    model_name: str,
    *,
    db_id: int,
    target_directory: Path,
) -> SavedEquipmentImage:
    query = model_name.strip()
    if not query:
        raise ImageSearchError("장비 모델명을 먼저 입력해 주세요.")

    providers = (
        _google_cse_candidates,
        _duckduckgo_candidates,
        _wikimedia_candidates,
    )
    last_error: Exception | None = None
    for provider in providers:
        try:
            candidates = provider(query)
        except Exception as error:  # noqa: BLE001 - try next provider
            last_error = error
            continue
        if not candidates:
            continue
        try:
            saved = _save_first_candidate(
                candidates,
                db_id=db_id,
                target_directory=target_directory,
            )
        except ImageSearchError as error:
            last_error = error
            continue
        if saved is not None:
            return saved

    google_url = google_images_search_url(query)
    detail = f" ({last_error})" if last_error else ""
    raise ImageSearchError(
        f"'{query}' 모델 이미지를 자동으로 찾지 못했습니다{detail}. "
        f"Google 이미지 검색: {google_url}"
    )
