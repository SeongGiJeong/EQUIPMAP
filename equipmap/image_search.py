"""장비 모델 이미지를 Wikimedia Commons에서 찾아 로컬에 저장."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
from pathlib import Path
import re
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageOps, UnidentifiedImageError


COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "EquipMap/1.0 (local equipment layout application)"
MAX_DOWNLOAD_BYTES = 12 * 1024 * 1024


class ImageSearchError(RuntimeError):
    """검색 결과나 유효한 이미지를 얻지 못한 경우."""


@dataclass(frozen=True)
class SavedEquipmentImage:
    filename: str
    source_url: str
    title: str


def _request_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=12) as response:
        return json.load(response)


def _download_image(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "upload.wikimedia.org":
        raise ImageSearchError("허용되지 않은 이미지 주소입니다.")
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=15) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_DOWNLOAD_BYTES:
            raise ImageSearchError("검색된 이미지 파일이 너무 큽니다.")
        content = response.read(MAX_DOWNLOAD_BYTES + 1)
    if len(content) > MAX_DOWNLOAD_BYTES:
        raise ImageSearchError("검색된 이미지 파일이 너무 큽니다.")
    return content


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


def search_and_save_equipment_image(
    model_name: str,
    *,
    db_id: int,
    target_directory: Path,
) -> SavedEquipmentImage:
    query = model_name.strip()
    if not query:
        raise ImageSearchError("장비 모델명을 먼저 입력해 주세요.")

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
    except (OSError, TimeoutError, ValueError) as error:
        raise ImageSearchError(f"이미지 검색 서버에 연결하지 못했습니다: {error}") from error
    pages = payload.get("query", {}).get("pages", [])
    pages = sorted(
        pages,
        key=lambda page: _candidate_score(page, query),
        reverse=True,
    )

    last_error: Exception | None = None
    for page in pages:
        info_list = page.get("imageinfo") or []
        if not info_list:
            continue
        info = info_list[0]
        mime = str(info.get("mime", ""))
        if mime not in {"image/jpeg", "image/png", "image/webp"}:
            continue
        image_url = str(info.get("thumburl") or info.get("url") or "")
        source_url = str(info.get("descriptionurl") or image_url)
        if not image_url:
            continue
        try:
            content = _download_image(image_url)
            filename = save_equipment_image_content(
                content,
                db_id=db_id,
                target_directory=target_directory,
            )
            return SavedEquipmentImage(
                filename=filename,
                source_url=source_url,
                title=str(page.get("title", query)),
            )
        except (
            ImageSearchError,
            OSError,
            UnidentifiedImageError,
            ValueError,
        ) as error:
            last_error = error
            continue

    if last_error is not None:
        raise ImageSearchError(f"사용 가능한 이미지를 저장하지 못했습니다: {last_error}")
    raise ImageSearchError(f"'{query}' 모델의 공개 이미지를 찾지 못했습니다.")
