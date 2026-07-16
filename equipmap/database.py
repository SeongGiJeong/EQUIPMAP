"""SQLite 기반 장비 정보 저장소."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from collections.abc import Iterator
import uuid


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "equipmap.db"
RACK_WORLD_HEIGHT = 780.0
RACK_WORLD_WIDTH = RACK_WORLD_HEIGHT * (600 / 2196)
RACK_MOUNT_WIDTH = RACK_WORLD_WIDTH * (485 / 600)
RACK_RU_HEIGHT = RACK_WORLD_HEIGHT * 0.92 / 46

DEFAULT_EQUIPMENT_TYPES = (
    (
        "rack_46ru",
        "rack",
        "설치물",
        "RACK",
        46,
        "equipmap/assets/server_rack_icon.png",
        "equipmap/assets/rack_46ru.png",
        "equipmap/assets/rack_46ru_canvas.png",
        RACK_WORLD_WIDTH,
        RACK_WORLD_HEIGHT,
        146,
    ),
    (
        "blank_panel_1ru",
        "rack",
        "설치물",
        "1RU",
        1,
        "equipmap/assets/server_rack_icon.png",
        "equipmap/assets/blank_panel_1ru.png",
        "equipmap/assets/blank_panel_1ru.png",
        RACK_MOUNT_WIDTH,
        RACK_RU_HEIGHT,
        201,
    ),
    (
        "blank_panel_2ru",
        "rack",
        "설치물",
        "2RU",
        2,
        "equipmap/assets/server_rack_icon.png",
        "equipmap/assets/blank_panel_1ru.png",
        "equipmap/assets/blank_panel_1ru.png",
        RACK_MOUNT_WIDTH,
        RACK_RU_HEIGHT * 2,
        202,
    ),
    (
        "blank_panel_3ru",
        "rack",
        "설치물",
        "3RU",
        3,
        "equipmap/assets/server_rack_icon.png",
        "equipmap/assets/blank_panel_1ru.png",
        "equipmap/assets/blank_panel_1ru.png",
        RACK_MOUNT_WIDTH,
        RACK_RU_HEIGHT * 3,
        203,
    ),
    (
        "blank_panel_4ru",
        "rack",
        "설치물",
        "4RU",
        4,
        "equipmap/assets/server_rack_icon.png",
        "equipmap/assets/blank_panel_1ru.png",
        "equipmap/assets/blank_panel_1ru.png",
        RACK_MOUNT_WIDTH,
        RACK_RU_HEIGHT * 4,
        204,
    ),
    (
        "drawer_2ru",
        "rack",
        "설치물",
        "DRAWER",
        2,
        "equipmap/assets/server_rack_icon.png",
        "equipmap/assets/drawer_2ru.png",
        "equipmap/assets/drawer_2ru.png",
        RACK_MOUNT_WIDTH,
        RACK_RU_HEIGHT * 2,
        300,
    ),
    (
        "pdu_2ru",
        "rack",
        "설치물",
        "PDU",
        2,
        "equipmap/assets/server_rack_icon.png",
        "equipmap/assets/pdu_2ru.png",
        "equipmap/assets/pdu_2ru.png",
        RACK_MOUNT_WIDTH,
        RACK_RU_HEIGHT * 2,
        400,
    ),
)

DEFAULT_EQUIPMENT_TYPES += tuple(
    (
        f"rack_{ru}ru",
        "rack",
        "설치물",
        "RACK",
        ru,
        "equipmap/assets/server_rack_icon.png",
        "equipmap/assets/rack_46ru.png",
        "equipmap/assets/rack_46ru_canvas.png",
        RACK_WORLD_WIDTH,
        RACK_RU_HEIGHT * (ru + 4),
        100 + ru,
    )
    for ru in range(23, 46)
)

DEFAULT_EQUIPMENT_TYPES += tuple(
    (
        f"blank_panel_{ru}ru",
        "rack",
        "설치물",
        f"{ru}RU",
        ru,
        "equipmap/assets/server_rack_icon.png",
        "equipmap/assets/blank_panel_1ru.png",
        "equipmap/assets/blank_panel_1ru.png",
        RACK_MOUNT_WIDTH,
        RACK_RU_HEIGHT * ru,
        200 + ru,
    )
    for ru in range(5, 11)
)

BROADCAST_DEVICE_DEFINITIONS = (
    ("vmu", "VMU"),
    ("module_frame", "MODULE FRAME"),
    ("monitor", "MONITOR"),
    ("rt", "RT"),
    ("measure_device", "MEASURE DEVICE"),
    ("signal_generator", "SIGNAL GENERATOR"),
)

DEFAULT_EQUIPMENT_TYPES += tuple(
    (
        f"broadcast_{slug}_{ru}ru",
        "broadcast_equipment",
        "방송장비",
        name,
        ru,
        "equipmap/assets/broadcast_equipment_icon.png",
        "equipmap/assets/solid_rack_device.png",
        "equipmap/assets/solid_rack_device.png",
        RACK_MOUNT_WIDTH,
        RACK_RU_HEIGHT * ru,
        100 + group_index * 10 + ru,
    )
    for group_index, (slug, name) in enumerate(
        BROADCAST_DEVICE_DEFINITIONS
    )
    for ru in range(1, 11)
)


@dataclass(frozen=True)
class EquipmentTypeRecord:
    key: str
    category_key: str
    category_name: str
    name: str
    ru: int
    category_icon_path: str
    image_path: str
    canvas_image_path: str
    width: float
    height: float
    active: bool
    sort_order: int


@dataclass(frozen=True)
class EquipmentRecord:
    db_id: int
    equipment_id: str
    spec_key: str
    equipment_name: str
    equipment_vendor: str
    equipment_model: str
    asset_number: str
    serial_number: str
    photo_path: str
    photo_source_url: str
    photo_query: str
    world_x: float
    world_y: float
    layout_width: float
    layout_height: float
    locked: bool


class EquipmentRepository:
    """장비 CRUD 및 자동 장비 ID 발급을 담당."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS equipment (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    equipment_id TEXT NOT NULL UNIQUE,
                    spec_key TEXT NOT NULL,
                    equipment_name TEXT NOT NULL DEFAULT '',
                    equipment_vendor TEXT NOT NULL DEFAULT '',
                    equipment_model TEXT NOT NULL DEFAULT '',
                    asset_number TEXT NOT NULL DEFAULT '',
                    serial_number TEXT NOT NULL DEFAULT '',
                    photo_path TEXT NOT NULL DEFAULT '',
                    photo_source_url TEXT NOT NULL DEFAULT '',
                    photo_query TEXT NOT NULL DEFAULT '',
                    world_x REAL NOT NULL,
                    world_y REAL NOT NULL,
                    layout_width REAL NOT NULL DEFAULT 0,
                    layout_height REAL NOT NULL DEFAULT 0,
                    locked INTEGER NOT NULL DEFAULT 0 CHECK (locked IN (0, 1)),
                    deleted INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(equipment)")
            }
            if "layout_width" not in columns:
                connection.execute(
                    "ALTER TABLE equipment ADD COLUMN layout_width REAL NOT NULL DEFAULT 0"
                )
            if "layout_height" not in columns:
                connection.execute(
                    "ALTER TABLE equipment ADD COLUMN layout_height REAL NOT NULL DEFAULT 0"
                )
            for column in ("photo_path", "photo_source_url", "photo_query"):
                if column not in columns:
                    connection.execute(
                        f"ALTER TABLE equipment ADD COLUMN {column} "
                        "TEXT NOT NULL DEFAULT ''"
                    )
            if "equipment_vendor" not in columns:
                connection.execute(
                    "ALTER TABLE equipment ADD COLUMN equipment_vendor "
                    "TEXT NOT NULL DEFAULT ''"
                )
            if "deleted" not in columns:
                connection.execute(
                    "ALTER TABLE equipment ADD COLUMN deleted "
                    "INTEGER NOT NULL DEFAULT 0 CHECK (deleted IN (0, 1))"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_equipment_spec_key ON equipment(spec_key)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS equipment_types (
                    spec_key TEXT PRIMARY KEY,
                    category_key TEXT NOT NULL,
                    category_name TEXT NOT NULL,
                    name TEXT NOT NULL,
                    ru INTEGER NOT NULL DEFAULT 0,
                    category_icon_path TEXT NOT NULL DEFAULT '',
                    image_path TEXT NOT NULL,
                    canvas_image_path TEXT NOT NULL,
                    width REAL NOT NULL,
                    height REAL NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.executemany(
                """
                INSERT INTO equipment_types (
                    spec_key, category_key, category_name, name, ru,
                    category_icon_path, image_path, canvas_image_path,
                    width, height, sort_order
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(spec_key) DO UPDATE SET
                    category_key = excluded.category_key,
                    category_name = excluded.category_name,
                    name = excluded.name,
                    ru = excluded.ru,
                    category_icon_path = excluded.category_icon_path,
                    image_path = excluded.image_path,
                    canvas_image_path = excluded.canvas_image_path,
                    width = excluded.width,
                    height = excluded.height,
                    active = 1,
                    sort_order = excluded.sort_order,
                    updated_at = CURRENT_TIMESTAMP
                """,
                DEFAULT_EQUIPMENT_TYPES,
            )
            connection.executemany(
                """
                UPDATE equipment
                SET layout_width = ?, layout_height = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE spec_key = ?
                """,
                (
                    (record[8], record[9], record[0])
                    for record in DEFAULT_EQUIPMENT_TYPES
                ),
            )
            connection.execute(
                """
                UPDATE equipment
                SET equipment_name = 'RACK',
                    updated_at = CURRENT_TIMESTAMP
                WHERE spec_key LIKE 'rack_%ru'
                  AND equipment_name IN (
                      '46RU RACK', '46RU 랙', '46RU 서버랙'
                  )
                """
            )

    def create(
        self,
        *,
        spec_key: str,
        equipment_name: str,
        world_x: float,
        world_y: float,
        layout_width: float,
        layout_height: float,
        locked: bool = False,
    ) -> EquipmentRecord:
        """장비를 추가하고 RACK-000001 형식 ID를 원자적으로 발급."""
        pending_id = f"PENDING-{uuid.uuid4().hex}"
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO equipment (
                    equipment_id, spec_key, equipment_name,
                    world_x, world_y, layout_width, layout_height, locked
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pending_id,
                    spec_key,
                    equipment_name.strip(),
                    float(world_x),
                    float(world_y),
                    float(layout_width),
                    float(layout_height),
                    int(locked),
                ),
            )
            db_id = int(cursor.lastrowid)
            equipment_id = f"RACK-{db_id:06d}"
            connection.execute(
                "UPDATE equipment SET equipment_id = ? WHERE id = ?",
                (equipment_id, db_id),
            )
            row = connection.execute(
                "SELECT * FROM equipment WHERE id = ?",
                (db_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("생성한 장비 정보를 DB에서 찾을 수 없습니다.")
        return self._to_record(row)

    def list_all(self) -> list[EquipmentRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM equipment WHERE deleted = 0 ORDER BY id"
            ).fetchall()
        return [self._to_record(row) for row in rows]

    def list_equipment_types(self, *, active_only: bool = True) -> list[EquipmentTypeRecord]:
        query = "SELECT * FROM equipment_types"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY category_name, sort_order, name"
        with self._connection() as connection:
            rows = connection.execute(query).fetchall()
        return [self._to_type_record(row) for row in rows]

    def update_state(
        self,
        db_id: int,
        *,
        world_x: float,
        world_y: float,
        layout_width: float,
        layout_height: float,
        locked: bool,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE equipment
                SET world_x = ?, world_y = ?,
                    layout_width = ?, layout_height = ?, locked = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    float(world_x),
                    float(world_y),
                    float(layout_width),
                    float(layout_height),
                    int(locked),
                    db_id,
                ),
            )

    def update_details(
        self,
        db_id: int,
        *,
        equipment_name: str,
        equipment_vendor: str,
        equipment_model: str,
        asset_number: str,
        serial_number: str,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE equipment
                SET equipment_name = ?, equipment_vendor = ?, equipment_model = ?,
                    asset_number = ?, serial_number = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    equipment_name.strip(),
                    equipment_vendor.strip(),
                    equipment_model.strip(),
                    asset_number.strip(),
                    serial_number.strip(),
                    db_id,
                ),
            )

    def update_photo(
        self,
        db_id: int,
        *,
        photo_path: str,
        photo_source_url: str,
        photo_query: str,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE equipment
                SET photo_path = ?, photo_source_url = ?, photo_query = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    photo_path.strip(),
                    photo_source_url.strip(),
                    photo_query.strip(),
                    db_id,
                ),
            )

    def delete(self, db_id: int) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE equipment
                SET deleted = 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (db_id,),
            )

    def restore(self, db_id: int) -> EquipmentRecord | None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE equipment
                SET deleted = 0, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (db_id,),
            )
            row = connection.execute(
                "SELECT * FROM equipment WHERE id = ? AND deleted = 0",
                (db_id,),
            ).fetchone()
        return self._to_record(row) if row is not None else None

    @staticmethod
    def _to_record(row: sqlite3.Row) -> EquipmentRecord:
        return EquipmentRecord(
            db_id=int(row["id"]),
            equipment_id=str(row["equipment_id"]),
            spec_key=str(row["spec_key"]),
            equipment_name=str(row["equipment_name"]),
            equipment_vendor=str(row["equipment_vendor"]),
            equipment_model=str(row["equipment_model"]),
            asset_number=str(row["asset_number"]),
            serial_number=str(row["serial_number"]),
            photo_path=str(row["photo_path"]),
            photo_source_url=str(row["photo_source_url"]),
            photo_query=str(row["photo_query"]),
            world_x=float(row["world_x"]),
            world_y=float(row["world_y"]),
            layout_width=float(row["layout_width"]),
            layout_height=float(row["layout_height"]),
            locked=bool(row["locked"]),
        )

    @staticmethod
    def _to_type_record(row: sqlite3.Row) -> EquipmentTypeRecord:
        return EquipmentTypeRecord(
            key=str(row["spec_key"]),
            category_key=str(row["category_key"]),
            category_name=str(row["category_name"]),
            name=str(row["name"]),
            ru=int(row["ru"]),
            category_icon_path=str(row["category_icon_path"]),
            image_path=str(row["image_path"]),
            canvas_image_path=str(row["canvas_image_path"]),
            width=float(row["width"]),
            height=float(row["height"]),
            active=bool(row["active"]),
            sort_order=int(row["sort_order"]),
        )
