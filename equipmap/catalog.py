"""DB 장비 종류 레코드를 UI/캔버스 규격으로 변환."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from equipmap.database import EquipmentTypeRecord

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class RackSpec:
    key: str
    category_key: str
    category_name: str
    name: str
    ru: int
    category_icon_path: Path
    image_path: Path
    canvas_image_path: Path
    # 월드 좌표 기준 기본 크기 (줌 100% = 픽셀)
    width: float
    height: float
    is_half: bool = False


def spec_from_record(record: EquipmentTypeRecord) -> RackSpec:
    return RackSpec(
        key=record.key,
        category_key=record.category_key,
        category_name=record.category_name,
        name=record.name,
        ru=record.ru,
        category_icon_path=PROJECT_ROOT / record.category_icon_path,
        image_path=PROJECT_ROOT / record.image_path,
        canvas_image_path=PROJECT_ROOT / record.canvas_image_path,
        width=record.width,
        height=record.height,
        is_half=record.is_half,
    )
