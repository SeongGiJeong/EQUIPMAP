"""SQLite 기반 장비 정보 저장소."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
from collections.abc import Iterator
import uuid


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "equipmap.db"
RACK_WORLD_HEIGHT = 780.0
RACK_WORLD_WIDTH = RACK_WORLD_HEIGHT * (600 / 2196)
RACK_MOUNT_WIDTH = RACK_WORLD_WIDTH * (485 / 600)
RACK_RU_HEIGHT = RACK_WORLD_HEIGHT * 0.92 / 46
ID_PREFIX_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,19}$")

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
        "RACK",
    ),
    (
        "blank_panel_1ru",
        "rack",
        "설치물",
        "BLANK PANEL",
        1,
        "equipmap/assets/server_rack_icon.png",
        "equipmap/assets/blank_panel_1ru.png",
        "equipmap/assets/blank_panel_1ru.png",
        RACK_MOUNT_WIDTH,
        RACK_RU_HEIGHT,
        201,
        "PANEL",
    ),
    (
        "blank_panel_2ru",
        "rack",
        "설치물",
        "BLANK PANEL",
        2,
        "equipmap/assets/server_rack_icon.png",
        "equipmap/assets/blank_panel_1ru.png",
        "equipmap/assets/blank_panel_1ru.png",
        RACK_MOUNT_WIDTH,
        RACK_RU_HEIGHT * 2,
        202,
        "PANEL",
    ),
    (
        "blank_panel_3ru",
        "rack",
        "설치물",
        "BLANK PANEL",
        3,
        "equipmap/assets/server_rack_icon.png",
        "equipmap/assets/blank_panel_1ru.png",
        "equipmap/assets/blank_panel_1ru.png",
        RACK_MOUNT_WIDTH,
        RACK_RU_HEIGHT * 3,
        203,
        "PANEL",
    ),
    (
        "blank_panel_4ru",
        "rack",
        "설치물",
        "BLANK PANEL",
        4,
        "equipmap/assets/server_rack_icon.png",
        "equipmap/assets/blank_panel_1ru.png",
        "equipmap/assets/blank_panel_1ru.png",
        RACK_MOUNT_WIDTH,
        RACK_RU_HEIGHT * 4,
        204,
        "PANEL",
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
        "DRAWER",
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
        "PDU",
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
        "RACK",
    )
    for ru in range(23, 46)
)

DEFAULT_EQUIPMENT_TYPES += tuple(
    (
        f"blank_panel_{ru}ru",
        "rack",
        "설치물",
        "BLANK PANEL",
        ru,
        "equipmap/assets/server_rack_icon.png",
        "equipmap/assets/blank_panel_1ru.png",
        "equipmap/assets/blank_panel_1ru.png",
        RACK_MOUNT_WIDTH,
        RACK_RU_HEIGHT * ru,
        200 + ru,
        "PANEL",
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

# 장비 종류별 기본 인터페이스: (그룹, 종류, 개수, 정렬)
DEFAULT_INTERFACE_PROFILES: dict[str, tuple[tuple[str, str, int, int], ...]] = {
    "PDU": (
        ("전원", "Power", 8, 10),
        ("네트워크", "Ethernet", 1, 20),
    ),
    "VMU": (
        ("영상", "BNC", 8, 10),
        ("음성", "XLR", 4, 20),
        ("네트워크", "Ethernet", 2, 30),
        ("제어", "Serial", 1, 40),
        ("전원", "Power", 1, 50),
    ),
    "MODULE_FRAME": (
        ("영상", "BNC", 16, 10),
        ("음성", "XLR", 8, 20),
        ("네트워크", "Ethernet", 2, 30),
        ("제어", "Serial", 2, 40),
        ("전원", "Power", 2, 50),
    ),
    "MONITOR": (
        ("영상", "BNC", 2, 10),
        ("영상", "HDMI", 1, 20),
        ("음성", "XLR", 2, 30),
        ("네트워크", "Ethernet", 1, 40),
        ("전원", "Power", 1, 50),
    ),
    "RT": (
        ("음성", "XLR", 4, 10),
        ("음성", "RCA", 2, 20),
        ("네트워크", "Ethernet", 1, 30),
        ("제어", "Serial", 1, 40),
        ("전원", "Power", 1, 50),
    ),
    "MEASURE_DEVICE": (
        ("영상", "BNC", 4, 10),
        ("네트워크", "Ethernet", 1, 20),
        ("제어", "Serial", 1, 30),
        ("전원", "Power", 1, 40),
    ),
    "SIGNAL_GENERATOR": (
        ("영상", "BNC", 4, 10),
        ("음성", "XLR", 2, 20),
        ("음성", "RCA", 2, 30),
        ("네트워크", "Ethernet", 1, 40),
        ("전원", "Power", 1, 50),
    ),
}

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
        slug.upper(),
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
    id_prefix: str
    is_half: bool


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


@dataclass(frozen=True)
class EquipmentLogRecord:
    log_id: int
    equipment_db_id: int
    log_date: str
    category: str
    action: str


@dataclass(frozen=True)
class EquipmentTypeInterfaceRecord:
    interface_id: int
    spec_key: str
    group_name: str
    interface_type: str
    port_count: int
    sort_order: int


@dataclass(frozen=True)
class EquipmentConnectionRecord:
    connection_id: int
    equipment_db_id: int
    interface_type: str
    port_index: int
    connection_name: str


@dataclass(frozen=True)
class EquipmentPortLinkRecord:
    link_id: int
    a_equipment_db_id: int
    a_interface_type: str
    a_port_index: int
    b_equipment_db_id: int
    b_interface_type: str
    b_port_index: int
    a_equipment_id: str = ""
    a_equipment_name: str = ""
    a_connection_name: str = ""
    b_equipment_id: str = ""
    b_equipment_name: str = ""
    b_connection_name: str = ""


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
                    id_prefix TEXT NOT NULL DEFAULT 'EQUIPMENT',
                    is_half INTEGER NOT NULL DEFAULT 0 CHECK (is_half IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            type_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(equipment_types)"
                )
            }
            if "id_prefix" not in type_columns:
                connection.execute(
                    "ALTER TABLE equipment_types ADD COLUMN id_prefix "
                    "TEXT NOT NULL DEFAULT 'EQUIPMENT'"
                )
            if "is_half" not in type_columns:
                connection.execute(
                    "ALTER TABLE equipment_types ADD COLUMN is_half "
                    "INTEGER NOT NULL DEFAULT 0 CHECK (is_half IN (0, 1))"
                )
            connection.executemany(
                """
                INSERT INTO equipment_types (
                    spec_key, category_key, category_name, name, ru,
                    category_icon_path, image_path, canvas_image_path,
                    width, height, sort_order, id_prefix
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(spec_key) DO UPDATE SET
                    category_key = excluded.category_key,
                    category_icon_path = excluded.category_icon_path,
                    image_path = excluded.image_path,
                    canvas_image_path = excluded.canvas_image_path,
                    active = 1,
                    sort_order = excluded.sort_order,
                    id_prefix = excluded.id_prefix,
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
                  AND (layout_width <= 0 OR layout_height <= 0)
                """,
                (
                    (record[8], record[9], record[0])
                    for record in DEFAULT_EQUIPMENT_TYPES
                ),
            )
            connection.execute(
                """
                UPDATE equipment_types
                SET name = 'BLANK PANEL',
                    updated_at = CURRENT_TIMESTAMP
                WHERE spec_key LIKE 'blank_panel_%ru'
                  AND name GLOB '[0-9]*RU'
                """
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS equipment_id_sequences (
                    id_prefix TEXT PRIMARY KEY,
                    next_value INTEGER NOT NULL CHECK (next_value > 0)
                )
                """
            )
            self._initialize_id_sequences(connection)
            self._migrate_equipment_ids(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS equipment_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    equipment_id INTEGER NOT NULL,
                    log_date TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (equipment_id) REFERENCES equipment(id)
                        ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_equipment_logs_equipment
                ON equipment_logs(equipment_id, log_date, id)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS equipment_type_interfaces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    spec_key TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    interface_type TEXT NOT NULL,
                    port_count INTEGER NOT NULL DEFAULT 1
                        CHECK (port_count >= 1),
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (spec_key) REFERENCES equipment_types(spec_key)
                        ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_equipment_type_interfaces_spec
                ON equipment_type_interfaces(spec_key, sort_order, id)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS equipment_connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    equipment_id INTEGER NOT NULL,
                    interface_type TEXT NOT NULL,
                    port_index INTEGER NOT NULL CHECK (port_index >= 1),
                    connection_name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(equipment_id, interface_type, port_index),
                    FOREIGN KEY (equipment_id) REFERENCES equipment(id)
                        ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_equipment_connections_equipment
                ON equipment_connections(equipment_id, interface_type, port_index)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS equipment_port_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    a_equipment_id INTEGER NOT NULL,
                    a_interface_type TEXT NOT NULL,
                    a_port_index INTEGER NOT NULL CHECK (a_port_index >= 1),
                    b_equipment_id INTEGER NOT NULL,
                    b_interface_type TEXT NOT NULL,
                    b_port_index INTEGER NOT NULL CHECK (b_port_index >= 1),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(a_equipment_id, a_interface_type, a_port_index),
                    UNIQUE(b_equipment_id, b_interface_type, b_port_index),
                    CHECK (
                        a_equipment_id != b_equipment_id
                        OR a_interface_type != b_interface_type
                        OR a_port_index != b_port_index
                    ),
                    FOREIGN KEY (a_equipment_id) REFERENCES equipment(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (b_equipment_id) REFERENCES equipment(id)
                        ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_equipment_port_links_a
                ON equipment_port_links(a_equipment_id, a_interface_type, a_port_index)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_equipment_port_links_b
                ON equipment_port_links(b_equipment_id, b_interface_type, b_port_index)
                """
            )
            self._seed_default_interfaces(connection)

    @staticmethod
    def _seed_default_interfaces(connection: sqlite3.Connection) -> None:
        existing = connection.execute(
            "SELECT COUNT(*) AS count FROM equipment_type_interfaces"
        ).fetchone()
        if int(existing["count"]) > 0:
            return
        rows = connection.execute(
            """
            SELECT spec_key, id_prefix
            FROM equipment_types
            WHERE active = 1
            """
        ).fetchall()
        inserts: list[tuple[str, str, str, int, int]] = []
        for row in rows:
            profile = DEFAULT_INTERFACE_PROFILES.get(str(row["id_prefix"]))
            if not profile:
                continue
            for group_name, interface_type, port_count, sort_order in profile:
                inserts.append(
                    (
                        str(row["spec_key"]),
                        group_name,
                        interface_type,
                        int(port_count),
                        int(sort_order),
                    )
                )
        if not inserts:
            return
        connection.executemany(
            """
            INSERT INTO equipment_type_interfaces (
                spec_key, group_name, interface_type, port_count, sort_order
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            inserts,
        )

    @staticmethod
    def _initialize_id_sequences(connection: sqlite3.Connection) -> None:
        highest_by_prefix: dict[str, int] = {}
        rows = connection.execute(
            "SELECT equipment_id FROM equipment"
        ).fetchall()
        for row in rows:
            prefix, separator, raw_number = str(row["equipment_id"]).rpartition("-")
            if not separator or not raw_number.isdigit():
                continue
            highest_by_prefix[prefix] = max(
                highest_by_prefix.get(prefix, 0),
                int(raw_number),
            )
        for prefix, highest in highest_by_prefix.items():
            connection.execute(
                """
                INSERT INTO equipment_id_sequences (id_prefix, next_value)
                VALUES (?, ?)
                ON CONFLICT(id_prefix) DO UPDATE SET
                    next_value = MAX(next_value, excluded.next_value)
                """,
                (prefix, highest + 1),
            )

    @staticmethod
    def _next_equipment_id(
        connection: sqlite3.Connection,
        id_prefix: str,
    ) -> str:
        row = connection.execute(
            "SELECT next_value FROM equipment_id_sequences WHERE id_prefix = ?",
            (id_prefix,),
        ).fetchone()
        if row is None:
            sequence = 1
            connection.execute(
                """
                INSERT INTO equipment_id_sequences (id_prefix, next_value)
                VALUES (?, 2)
                """,
                (id_prefix,),
            )
        else:
            sequence = int(row["next_value"])
            connection.execute(
                """
                UPDATE equipment_id_sequences
                SET next_value = ?
                WHERE id_prefix = ?
                """,
                (sequence + 1, id_prefix),
            )
        return f"{id_prefix}-{sequence:06d}"

    @classmethod
    def _migrate_equipment_ids(cls, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT equipment.id, equipment.equipment_id, equipment_types.id_prefix
            FROM equipment
            JOIN equipment_types
              ON equipment_types.spec_key = equipment.spec_key
            ORDER BY equipment.id
            """
        ).fetchall()
        for row in rows:
            current_id = str(row["equipment_id"])
            expected_prefix = str(row["id_prefix"])
            current_prefix, separator, raw_number = current_id.rpartition("-")
            if (
                separator
                and raw_number.isdigit()
                and current_prefix == expected_prefix
            ):
                continue
            db_id = int(row["id"])
            connection.execute(
                "UPDATE equipment SET equipment_id = ? WHERE id = ?",
                (f"MIGRATING-{uuid.uuid4().hex}", db_id),
            )
            equipment_id = cls._next_equipment_id(
                connection,
                expected_prefix,
            )
            connection.execute(
                """
                UPDATE equipment
                SET equipment_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (equipment_id, db_id),
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
        """장비 유형별 PREFIX-000001 형식 ID를 원자적으로 발급."""
        pending_id = f"PENDING-{uuid.uuid4().hex}"
        with self._connection() as connection:
            type_row = connection.execute(
                """
                SELECT id_prefix
                FROM equipment_types
                WHERE spec_key = ? AND active = 1
                """,
                (spec_key,),
            ).fetchone()
            if type_row is None:
                raise ValueError("알 수 없는 장비 종류입니다.")
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
            equipment_id = self._next_equipment_id(
                connection,
                str(type_row["id_prefix"]),
            )
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

    def create_equipment_type(
        self,
        *,
        category_name: str,
        name: str,
        id_prefix: str,
        ru: int,
        is_half: bool = False,
    ) -> EquipmentTypeRecord:
        normalized_category = category_name.strip()
        normalized_name = name.strip()
        normalized_prefix = id_prefix.strip().upper()
        if not normalized_category or len(normalized_category) > 40:
            raise ValueError("대그룹 이름은 1~40자로 입력해주세요.")
        if not normalized_name or len(normalized_name) > 60:
            raise ValueError("장비 이름은 1~60자로 입력해주세요.")
        if not ID_PREFIX_PATTERN.fullmatch(normalized_prefix):
            raise ValueError(
                "ID 접두사는 영문 대문자로 시작하는 1~20자의 "
                "영문, 숫자, 밑줄만 사용할 수 있습니다."
            )
        if not 1 <= int(ru) <= 46:
            raise ValueError("RU 크기는 1~46 사이여야 합니다.")

        mount_width = (
            RACK_MOUNT_WIDTH / 2 if is_half else RACK_MOUNT_WIDTH
        )
        spec_key = f"custom_{uuid.uuid4().hex[:12]}"
        with self._connection() as connection:
            category = connection.execute(
                """
                SELECT category_key, category_icon_path
                FROM equipment_types
                WHERE active = 1 AND LOWER(category_name) = LOWER(?)
                ORDER BY sort_order
                LIMIT 1
                """,
                (normalized_category,),
            ).fetchone()
            if category is None:
                category_key = f"custom_group_{uuid.uuid4().hex[:10]}"
                category_icon_path = (
                    "equipmap/assets/broadcast_equipment_icon.png"
                )
            else:
                category_key = str(category["category_key"])
                category_icon_path = str(category["category_icon_path"])

            duplicate = connection.execute(
                """
                SELECT name, id_prefix
                FROM equipment_types
                WHERE active = 1
                  AND (
                    (category_key = ? AND LOWER(name) = LOWER(?))
                    OR id_prefix = ?
                  )
                LIMIT 1
                """,
                (category_key, normalized_name, normalized_prefix),
            ).fetchone()
            if duplicate is not None:
                if str(duplicate["id_prefix"]) == normalized_prefix:
                    raise ValueError("이미 사용 중인 ID 접두사입니다.")
                raise ValueError("같은 이름의 장비가 이미 있습니다.")

            next_sort_order = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(sort_order), 0) + 1
                    FROM equipment_types
                    WHERE category_key = ?
                    """,
                    (category_key,),
                ).fetchone()[0]
            )
            connection.execute(
                """
                INSERT INTO equipment_types (
                    spec_key, category_key, category_name, name, ru,
                    category_icon_path, image_path, canvas_image_path,
                    width, height, sort_order, id_prefix, is_half
                )
                VALUES (?, ?, ?, ?, ?, ?,
                        'equipmap/assets/solid_rack_device.png',
                        'equipmap/assets/solid_rack_device.png',
                        ?, ?, ?, ?, ?)
                """,
                (
                    spec_key,
                    category_key,
                    normalized_category,
                    normalized_name,
                    int(ru),
                    category_icon_path,
                    mount_width,
                    RACK_RU_HEIGHT * int(ru),
                    next_sort_order,
                    normalized_prefix,
                    int(bool(is_half)),
                ),
            )
            row = connection.execute(
                "SELECT * FROM equipment_types WHERE spec_key = ?",
                (spec_key,),
            ).fetchone()
        if row is None:
            raise RuntimeError("추가한 장비 종류를 찾을 수 없습니다.")
        return self._to_type_record(row)

    def update_category_name(
        self,
        *,
        category_key: str,
        category_name: str,
    ) -> list[EquipmentTypeRecord]:
        normalized_name = category_name.strip()
        if not normalized_name or len(normalized_name) > 40:
            raise ValueError("대그룹 이름은 1~40자로 입력해주세요.")
        with self._connection() as connection:
            exists = connection.execute(
                """
                SELECT 1
                FROM equipment_types
                WHERE category_key = ? AND active = 1
                LIMIT 1
                """,
                (category_key,),
            ).fetchone()
            if exists is None:
                raise ValueError("수정할 대그룹을 찾을 수 없습니다.")
            duplicate = connection.execute(
                """
                SELECT 1
                FROM equipment_types
                WHERE category_key <> ?
                  AND active = 1
                  AND LOWER(category_name) = LOWER(?)
                LIMIT 1
                """,
                (category_key, normalized_name),
            ).fetchone()
            if duplicate is not None:
                raise ValueError("같은 이름의 대그룹이 이미 있습니다.")
            connection.execute(
                """
                UPDATE equipment_types
                SET category_name = ?, updated_at = CURRENT_TIMESTAMP
                WHERE category_key = ?
                """,
                (normalized_name, category_key),
            )
            rows = connection.execute(
                """
                SELECT *
                FROM equipment_types
                WHERE category_key = ? AND active = 1
                ORDER BY sort_order, name
                """,
                (category_key,),
            ).fetchall()
        return [self._to_type_record(row) for row in rows]

    def update_equipment_type_group(
        self,
        *,
        spec_keys: list[str],
        name: str,
        category_name: str | None = None,
        ru: int | None = None,
        is_half: bool | None = None,
    ) -> list[EquipmentTypeRecord]:
        normalized_keys = list(
            dict.fromkeys(key.strip() for key in spec_keys if key.strip())
        )
        normalized_name = name.strip()
        if not normalized_keys or len(normalized_keys) > 100:
            raise ValueError("수정할 장비 종류를 선택해주세요.")
        if not normalized_name or len(normalized_name) > 60:
            raise ValueError("장비 이름은 1~60자로 입력해주세요.")
        ru_value: int | None = None
        if ru is not None:
            ru_value = int(ru)
            if not 1 <= ru_value <= 46:
                raise ValueError("RU 크기는 1~46 사이여야 합니다.")

        placeholders = ", ".join("?" for _ in normalized_keys)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM equipment_types
                WHERE spec_key IN ({placeholders}) AND active = 1
                ORDER BY ru, sort_order, spec_key
                """,
                normalized_keys,
            ).fetchall()
            if len(rows) != len(normalized_keys):
                raise ValueError("수정할 장비 종류를 찾을 수 없습니다.")
            source_category_keys = {str(row["category_key"]) for row in rows}
            if len(source_category_keys) != 1:
                raise ValueError("같은 대그룹의 장비만 함께 수정할 수 있습니다.")
            target_category_key = source_category_keys.pop()
            target_category_name = str(rows[0]["category_name"])
            target_category_icon = str(rows[0]["category_icon_path"])

            if category_name is not None:
                normalized_category = category_name.strip()
                if not normalized_category or len(normalized_category) > 40:
                    raise ValueError("대그룹 이름은 1~40자로 입력해주세요.")
                existing = connection.execute(
                    """
                    SELECT category_key, category_name, category_icon_path
                    FROM equipment_types
                    WHERE active = 1 AND LOWER(category_name) = LOWER(?)
                    ORDER BY sort_order
                    LIMIT 1
                    """,
                    (normalized_category,),
                ).fetchone()
                if existing is None:
                    target_category_key = (
                        f"custom_group_{uuid.uuid4().hex[:10]}"
                    )
                    target_category_name = normalized_category
                else:
                    target_category_key = str(existing["category_key"])
                    target_category_name = str(existing["category_name"])
                    target_category_icon = str(
                        existing["category_icon_path"]
                    )

            is_rack = any(
                str(row["spec_key"]).startswith("rack_") for row in rows
            )
            # 신규 배치에 쓰는 대표 종류만 RU/Half를 바꾼다.
            survivor_key = (
                str(rows[-1]["spec_key"])
                if is_rack
                else str(rows[0]["spec_key"])
            )
            half_value = (
                bool(is_half)
                if is_half is not None
                else bool(rows[0]["is_half"])
            )
            if is_rack and half_value:
                raise ValueError("랙은 Half 크기로 설정할 수 없습니다.")

            duplicate = connection.execute(
                f"""
                SELECT 1
                FROM equipment_types
                WHERE category_key = ?
                  AND active = 1
                  AND LOWER(name) = LOWER(?)
                  AND spec_key NOT IN ({placeholders})
                LIMIT 1
                """,
                (target_category_key, normalized_name, *normalized_keys),
            ).fetchone()
            if duplicate is not None:
                raise ValueError("같은 대그룹에 동일한 장비 이름이 있습니다.")

            connection.execute(
                f"""
                UPDATE equipment_types
                SET name = ?,
                    category_key = ?,
                    category_name = ?,
                    category_icon_path = ?,
                    is_half = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE spec_key IN ({placeholders})
                """,
                (
                    normalized_name,
                    target_category_key,
                    target_category_name,
                    target_category_icon,
                    int(half_value),
                    *normalized_keys,
                ),
            )
            template_ru = (
                ru_value
                if ru_value is not None
                else int(
                    next(
                        row["ru"]
                        for row in rows
                        if str(row["spec_key"]) == survivor_key
                    )
                )
            )
            if is_rack:
                layout_width = RACK_WORLD_WIDTH
                layout_height = RACK_RU_HEIGHT * (template_ru + 4)
            else:
                layout_width = (
                    RACK_MOUNT_WIDTH / 2 if half_value else RACK_MOUNT_WIDTH
                )
                layout_height = RACK_RU_HEIGHT * template_ru
            # 목록(템플릿) 크기만 변경한다. 이미 배치된 장비 크기는 유지.
            connection.execute(
                """
                UPDATE equipment_types
                SET ru = ?, width = ?, height = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE spec_key = ?
                """,
                (template_ru, layout_width, layout_height, survivor_key),
            )
            if ru_value is not None:
                unused = [
                    key for key in normalized_keys if key != survivor_key
                ]
                if unused:
                    unused_placeholders = ", ".join("?" for _ in unused)
                    unused_without_placements = [
                        str(row["spec_key"])
                        for row in connection.execute(
                            f"""
                            SELECT equipment_types.spec_key
                            FROM equipment_types
                            LEFT JOIN equipment
                              ON equipment.spec_key = equipment_types.spec_key
                             AND equipment.deleted = 0
                            WHERE equipment_types.spec_key IN ({unused_placeholders})
                            GROUP BY equipment_types.spec_key
                            HAVING COUNT(equipment.id) = 0
                            """,
                            unused,
                        ).fetchall()
                    ]
                    if unused_without_placements:
                        deactivate_placeholders = ", ".join(
                            "?" for _ in unused_without_placements
                        )
                        connection.execute(
                            f"""
                            UPDATE equipment_types
                            SET active = 0, updated_at = CURRENT_TIMESTAMP
                            WHERE spec_key IN ({deactivate_placeholders})
                            """,
                            unused_without_placements,
                        )
            updated_rows = connection.execute(
                f"""
                SELECT *
                FROM equipment_types
                WHERE spec_key IN ({placeholders}) AND active = 1
                ORDER BY ru, sort_order, spec_key
                """,
                normalized_keys,
            ).fetchall()
        return [self._to_type_record(row) for row in updated_rows]

    def delete_equipment_types(
        self,
        *,
        spec_keys: list[str],
    ) -> list[str]:
        normalized_keys = list(
            dict.fromkeys(key.strip() for key in spec_keys if key.strip())
        )
        if not normalized_keys or len(normalized_keys) > 100:
            raise ValueError("삭제할 장비 종류를 선택해주세요.")
        placeholders = ", ".join("?" for _ in normalized_keys)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT spec_key
                FROM equipment_types
                WHERE spec_key IN ({placeholders}) AND active = 1
                """,
                normalized_keys,
            ).fetchall()
            if len(rows) != len(normalized_keys):
                raise ValueError("삭제할 장비 종류를 찾을 수 없습니다.")
            placed = connection.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM equipment
                WHERE deleted = 0 AND spec_key IN ({placeholders})
                """,
                normalized_keys,
            ).fetchone()
            if int(placed["count"]) > 0:
                raise ValueError(
                    "캔버스에 배치된 장비가 있어 삭제할 수 없습니다. "
                    "배치된 장비를 먼저 삭제해주세요."
                )
            connection.execute(
                f"""
                UPDATE equipment_types
                SET active = 0, updated_at = CURRENT_TIMESTAMP
                WHERE spec_key IN ({placeholders})
                """,
                normalized_keys,
            )
        return normalized_keys

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
    def _normalize_log_date(value: str) -> str:
        digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
        if len(digits) != 8:
            raise ValueError("날짜는 YYYYMMDD 형식으로 입력해주세요.")
        year = int(digits[0:4])
        month = int(digits[4:6])
        day = int(digits[6:8])
        if not (1 <= month <= 12 and 1 <= day <= 31 and year >= 2000):
            raise ValueError("날짜 형식이 올바르지 않습니다.")
        return digits

    def list_type_interfaces(
        self,
        spec_keys: list[str] | None = None,
    ) -> dict[str, list[EquipmentTypeInterfaceRecord]]:
        query = """
            SELECT *
            FROM equipment_type_interfaces
        """
        params: tuple[object, ...] = ()
        if spec_keys is not None:
            normalized = list(
                dict.fromkeys(key.strip() for key in spec_keys if key.strip())
            )
            if not normalized:
                return {}
            placeholders = ", ".join("?" for _ in normalized)
            query += f" WHERE spec_key IN ({placeholders})"
            params = tuple(normalized)
        query += " ORDER BY sort_order, id"
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
        result: dict[str, list[EquipmentTypeInterfaceRecord]] = {}
        for row in rows:
            record = self._to_interface_record(row)
            result.setdefault(record.spec_key, []).append(record)
        return result

    def replace_type_interfaces(
        self,
        spec_key: str,
        interfaces: list[dict[str, object]],
    ) -> tuple[list[str], list[EquipmentTypeInterfaceRecord]]:
        normalized_key = spec_key.strip()
        if not normalized_key:
            raise ValueError("장비 종류를 찾을 수 없습니다.")
        if len(interfaces) > 50:
            raise ValueError("인터페이스는 최대 50개까지 등록할 수 있습니다.")

        normalized: list[tuple[str, int]] = []
        seen_types: set[str] = set()
        for item in interfaces:
            interface_type = str(item.get("interface_type", "")).strip()
            if not interface_type or len(interface_type) > 40:
                raise ValueError("인터페이스 종류는 1~40자로 입력해주세요.")
            lowered = interface_type.casefold()
            if lowered in seen_types:
                raise ValueError("같은 인터페이스 종류를 중복 등록할 수 없습니다.")
            seen_types.add(lowered)
            try:
                port_count = int(item.get("port_count", 0))
            except (TypeError, ValueError) as error:
                raise ValueError("연결 수량은 숫자로 입력해주세요.") from error
            if not 1 <= port_count <= 9999:
                raise ValueError("연결 수량은 1~9999 사이여야 합니다.")
            normalized.append((interface_type, port_count))

        with self._connection() as connection:
            source = connection.execute(
                """
                SELECT category_key, id_prefix
                FROM equipment_types
                WHERE spec_key = ? AND active = 1
                """,
                (normalized_key,),
            ).fetchone()
            if source is None:
                raise ValueError("장비 종류를 찾을 수 없습니다.")
            if str(source["category_key"]) != "broadcast_equipment":
                raise ValueError("방송 장비의 연결 정보만 수정할 수 있습니다.")

            rows = connection.execute(
                """
                SELECT spec_key
                FROM equipment_types
                WHERE active = 1
                  AND category_key = ?
                  AND id_prefix = ?
                ORDER BY ru, sort_order, spec_key
                """,
                (str(source["category_key"]), str(source["id_prefix"])),
            ).fetchall()
            target_keys = [str(row["spec_key"]) for row in rows]
            placeholders = ", ".join("?" for _ in target_keys)
            connection.execute(
                f"""
                DELETE FROM equipment_type_interfaces
                WHERE spec_key IN ({placeholders})
                """,
                target_keys,
            )
            inserts = [
                (
                    target_key,
                    "기타",
                    interface_type,
                    port_count,
                    (index + 1) * 10,
                )
                for target_key in target_keys
                for index, (interface_type, port_count) in enumerate(normalized)
            ]
            if inserts:
                connection.executemany(
                    """
                    INSERT INTO equipment_type_interfaces (
                        spec_key, group_name, interface_type,
                        port_count, sort_order
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    inserts,
                )
            updated_rows = connection.execute(
                """
                SELECT *
                FROM equipment_type_interfaces
                WHERE spec_key = ?
                ORDER BY sort_order, id
                """,
                (normalized_key,),
            ).fetchall()
        return (
            target_keys,
            [self._to_interface_record(row) for row in updated_rows],
        )

    def list_connections(
        self,
        equipment_db_id: int,
    ) -> list[EquipmentConnectionRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM equipment_connections
                WHERE equipment_id = ?
                ORDER BY interface_type, port_index, id
                """,
                (equipment_db_id,),
            ).fetchall()
        return [self._to_connection_record(row) for row in rows]

    def replace_connections(
        self,
        equipment_db_id: int,
        *,
        interface_type: str,
        connection_names: list[str],
    ) -> list[EquipmentConnectionRecord]:
        normalized_type = interface_type.strip()
        if not normalized_type or len(normalized_type) > 40:
            raise ValueError("인터페이스 종류는 1~40자로 입력해주세요.")
        if len(connection_names) > 9999:
            raise ValueError("연결 항목이 너무 많습니다.")
        normalized_names: list[str] = []
        for name in connection_names:
            text = str(name).strip()
            if len(text) > 80:
                raise ValueError("연결 이름은 80자 이하로 입력해주세요.")
            normalized_names.append(text)

        with self._connection() as connection:
            exists = connection.execute(
                """
                SELECT 1 FROM equipment
                WHERE id = ? AND deleted = 0
                """,
                (equipment_db_id,),
            ).fetchone()
            if exists is None:
                raise ValueError("장비를 찾을 수 없습니다.")
            connection.execute(
                """
                DELETE FROM equipment_connections
                WHERE equipment_id = ? AND interface_type = ?
                """,
                (equipment_db_id, normalized_type),
            )
            if normalized_names:
                connection.executemany(
                    """
                    INSERT INTO equipment_connections (
                        equipment_id, interface_type, port_index, connection_name
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        (
                            equipment_db_id,
                            normalized_type,
                            index,
                            name,
                        )
                        for index, name in enumerate(normalized_names, start=1)
                    ],
                )
            rows = connection.execute(
                """
                SELECT *
                FROM equipment_connections
                WHERE equipment_id = ? AND interface_type = ?
                ORDER BY port_index, id
                """,
                (equipment_db_id, normalized_type),
            ).fetchall()
        return [self._to_connection_record(row) for row in rows]

    def clone_equipment(
        self,
        source_db_id: int,
        *,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
    ) -> EquipmentRecord:
        """장비 정보를 복제하고 새 장비 ID만 발급한다."""
        pending_id = f"PENDING-{uuid.uuid4().hex}"
        with self._connection() as connection:
            source = connection.execute(
                """
                SELECT *
                FROM equipment
                WHERE id = ? AND deleted = 0
                """,
                (source_db_id,),
            ).fetchone()
            if source is None:
                raise ValueError("복사할 장비를 찾을 수 없습니다.")
            type_row = connection.execute(
                """
                SELECT id_prefix
                FROM equipment_types
                WHERE spec_key = ? AND active = 1
                """,
                (str(source["spec_key"]),),
            ).fetchone()
            if type_row is None:
                raise ValueError("알 수 없는 장비 종류입니다.")

            cursor = connection.execute(
                """
                INSERT INTO equipment (
                    equipment_id, spec_key, equipment_name,
                    equipment_vendor, equipment_model,
                    asset_number, serial_number,
                    photo_path, photo_source_url, photo_query,
                    world_x, world_y, layout_width, layout_height, locked
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pending_id,
                    str(source["spec_key"]),
                    str(source["equipment_name"]),
                    str(source["equipment_vendor"]),
                    str(source["equipment_model"]),
                    str(source["asset_number"]),
                    str(source["serial_number"]),
                    "",
                    str(source["photo_source_url"]),
                    str(source["photo_query"]),
                    float(source["world_x"]) + float(offset_x),
                    float(source["world_y"]) + float(offset_y),
                    float(source["layout_width"]),
                    float(source["layout_height"]),
                    int(source["locked"]),
                ),
            )
            target_db_id = int(cursor.lastrowid)
            equipment_id = self._next_equipment_id(
                connection,
                str(type_row["id_prefix"]),
            )
            connection.execute(
                "UPDATE equipment SET equipment_id = ? WHERE id = ?",
                (equipment_id, target_db_id),
            )
            connection.execute(
                """
                INSERT INTO equipment_connections (
                    equipment_id, interface_type, port_index,
                    connection_name, created_at, updated_at
                )
                SELECT ?, interface_type, port_index,
                       connection_name, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                FROM equipment_connections
                WHERE equipment_id = ?
                ORDER BY id
                """,
                (target_db_id, source_db_id),
            )
            connection.execute(
                """
                INSERT INTO equipment_logs (
                    equipment_id, log_date, category, action,
                    created_at, updated_at
                )
                SELECT ?, log_date, category, action,
                       CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                FROM equipment_logs
                WHERE equipment_id = ?
                ORDER BY id
                """,
                (target_db_id, source_db_id),
            )
            row = connection.execute(
                "SELECT * FROM equipment WHERE id = ?",
                (target_db_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("복제한 장비 정보를 DB에서 찾을 수 없습니다.")
        return self._to_record(row)

    def clone_related_data(
        self,
        source_db_id: int,
        target_db_id: int,
    ) -> None:
        """장비 ID를 제외한 로그와 연결 정보를 새 장비로 복제."""
        with self._connection() as connection:
            source = connection.execute(
                """
                SELECT 1 FROM equipment
                WHERE id = ? AND deleted = 0
                """,
                (source_db_id,),
            ).fetchone()
            target = connection.execute(
                """
                SELECT 1 FROM equipment
                WHERE id = ? AND deleted = 0
                """,
                (target_db_id,),
            ).fetchone()
            if source is None or target is None:
                raise ValueError("복제할 장비 정보를 찾을 수 없습니다.")

            connection.execute(
                """
                INSERT INTO equipment_connections (
                    equipment_id, interface_type, port_index,
                    connection_name, created_at, updated_at
                )
                SELECT ?, interface_type, port_index,
                       connection_name, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                FROM equipment_connections
                WHERE equipment_id = ?
                ORDER BY id
                """,
                (target_db_id, source_db_id),
            )
            connection.execute(
                """
                INSERT INTO equipment_logs (
                    equipment_id, log_date, category, action,
                    created_at, updated_at
                )
                SELECT ?, log_date, category, action,
                       CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                FROM equipment_logs
                WHERE equipment_id = ?
                ORDER BY id
                """,
                (target_db_id, source_db_id),
            )

    def list_port_links(
        self,
        equipment_db_id: int | None = None,
    ) -> list[EquipmentPortLinkRecord]:
        query = """
            SELECT
                l.id,
                l.a_equipment_id,
                l.a_interface_type,
                l.a_port_index,
                l.b_equipment_id,
                l.b_interface_type,
                l.b_port_index,
                ea.equipment_id AS a_equipment_code,
                ea.equipment_name AS a_equipment_name,
                eb.equipment_id AS b_equipment_code,
                eb.equipment_name AS b_equipment_name,
                COALESCE(ca.connection_name, '') AS a_connection_name,
                COALESCE(cb.connection_name, '') AS b_connection_name
            FROM equipment_port_links l
            JOIN equipment ea ON ea.id = l.a_equipment_id AND ea.deleted = 0
            JOIN equipment eb ON eb.id = l.b_equipment_id AND eb.deleted = 0
            LEFT JOIN equipment_connections ca
              ON ca.equipment_id = l.a_equipment_id
             AND ca.interface_type = l.a_interface_type
             AND ca.port_index = l.a_port_index
            LEFT JOIN equipment_connections cb
              ON cb.equipment_id = l.b_equipment_id
             AND cb.interface_type = l.b_interface_type
             AND cb.port_index = l.b_port_index
        """
        params: tuple[object, ...] = ()
        if equipment_db_id is not None:
            query += """
                WHERE l.a_equipment_id = ? OR l.b_equipment_id = ?
            """
            params = (equipment_db_id, equipment_db_id)
        query += " ORDER BY l.id"
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._to_port_link_record(row) for row in rows]

    def upsert_port_link(
        self,
        *,
        from_equipment_db_id: int,
        from_interface_type: str,
        from_port_index: int,
        to_equipment_db_id: int,
        to_interface_type: str,
        to_port_index: int,
    ) -> EquipmentPortLinkRecord:
        a_type = from_interface_type.strip()
        b_type = to_interface_type.strip()
        a_index = int(from_port_index)
        b_index = int(to_port_index)
        if not a_type or len(a_type) > 40 or not b_type or len(b_type) > 40:
            raise ValueError("인터페이스 종류는 1~40자로 입력해주세요.")
        if a_index < 1 or b_index < 1:
            raise ValueError("포트 번호가 올바르지 않습니다.")
        if (
            from_equipment_db_id == to_equipment_db_id
            and a_type == b_type
            and a_index == b_index
        ):
            raise ValueError("같은 포트에는 연결할 수 없습니다.")

        with self._connection() as connection:
            endpoints = (
                (from_equipment_db_id, a_type, a_index),
                (to_equipment_db_id, b_type, b_index),
            )
            for equipment_db_id, interface_type, port_index in endpoints:
                exists = connection.execute(
                    """
                    SELECT 1 FROM equipment
                    WHERE id = ? AND deleted = 0
                    """,
                    (equipment_db_id,),
                ).fetchone()
                if exists is None:
                    raise ValueError("연결할 장비를 찾을 수 없습니다.")
                connection.execute(
                    """
                    DELETE FROM equipment_port_links
                    WHERE (
                        a_equipment_id = ? AND a_interface_type = ?
                        AND a_port_index = ?
                    ) OR (
                        b_equipment_id = ? AND b_interface_type = ?
                        AND b_port_index = ?
                    )
                    """,
                    (
                        equipment_db_id,
                        interface_type,
                        port_index,
                        equipment_db_id,
                        interface_type,
                        port_index,
                    ),
                )
            cursor = connection.execute(
                """
                INSERT INTO equipment_port_links (
                    a_equipment_id, a_interface_type, a_port_index,
                    b_equipment_id, b_interface_type, b_port_index
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    from_equipment_db_id,
                    a_type,
                    a_index,
                    to_equipment_db_id,
                    b_type,
                    b_index,
                ),
            )
            link_id = int(cursor.lastrowid)
        links = [
            link
            for link in self.list_port_links(from_equipment_db_id)
            if link.link_id == link_id
        ]
        if not links:
            raise RuntimeError("포트 연결을 저장하지 못했습니다.")
        return links[0]

    def delete_port_link(self, link_id: int) -> None:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM equipment_port_links WHERE id = ?",
                (int(link_id),),
            )
            if cursor.rowcount <= 0:
                raise ValueError("삭제할 연결을 찾을 수 없습니다.")

    def list_logs(self, equipment_db_id: int) -> list[EquipmentLogRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM equipment_logs
                WHERE equipment_id = ?
                ORDER BY log_date DESC, id DESC
                """,
                (equipment_db_id,),
            ).fetchall()
        return [self._to_log_record(row) for row in rows]

    def create_log(
        self,
        equipment_db_id: int,
        *,
        log_date: str,
        category: str,
        action: str,
    ) -> EquipmentLogRecord:
        normalized_date = self._normalize_log_date(log_date)
        normalized_category = category.strip()
        normalized_action = action.strip()
        if not normalized_category or len(normalized_category) > 40:
            raise ValueError("구분은 1~40자로 입력해주세요.")
        if not normalized_action or len(normalized_action) > 200:
            raise ValueError("조치사항은 1~200자로 입력해주세요.")
        with self._connection() as connection:
            exists = connection.execute(
                """
                SELECT 1 FROM equipment
                WHERE id = ? AND deleted = 0
                """,
                (equipment_db_id,),
            ).fetchone()
            if exists is None:
                raise ValueError("장비를 찾을 수 없습니다.")
            cursor = connection.execute(
                """
                INSERT INTO equipment_logs (
                    equipment_id, log_date, category, action
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    equipment_db_id,
                    normalized_date,
                    normalized_category,
                    normalized_action,
                ),
            )
            row = connection.execute(
                "SELECT * FROM equipment_logs WHERE id = ?",
                (int(cursor.lastrowid),),
            ).fetchone()
        if row is None:
            raise RuntimeError("장비 로그를 저장하지 못했습니다.")
        return self._to_log_record(row)

    def update_log(
        self,
        equipment_db_id: int,
        log_id: int,
        *,
        log_date: str,
        category: str,
        action: str,
    ) -> EquipmentLogRecord:
        normalized_date = self._normalize_log_date(log_date)
        normalized_category = category.strip()
        normalized_action = action.strip()
        if not normalized_category or len(normalized_category) > 40:
            raise ValueError("구분은 1~40자로 입력해주세요.")
        if not normalized_action or len(normalized_action) > 200:
            raise ValueError("조치사항은 1~200자로 입력해주세요.")
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE equipment_logs
                SET log_date = ?, category = ?, action = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND equipment_id = ?
                """,
                (
                    normalized_date,
                    normalized_category,
                    normalized_action,
                    log_id,
                    equipment_db_id,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM equipment_logs
                WHERE id = ? AND equipment_id = ?
                """,
                (log_id, equipment_db_id),
            ).fetchone()
        if row is None:
            raise ValueError("수정할 로그를 찾을 수 없습니다.")
        return self._to_log_record(row)

    def delete_log(self, equipment_db_id: int, log_id: int) -> None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM equipment_logs
                WHERE id = ? AND equipment_id = ?
                """,
                (log_id, equipment_db_id),
            )
            if cursor.rowcount <= 0:
                raise ValueError("삭제할 로그를 찾을 수 없습니다.")

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
            id_prefix=str(row["id_prefix"]),
            is_half=bool(row["is_half"]),
        )

    @staticmethod
    def _to_log_record(row: sqlite3.Row) -> EquipmentLogRecord:
        return EquipmentLogRecord(
            log_id=int(row["id"]),
            equipment_db_id=int(row["equipment_id"]),
            log_date=str(row["log_date"]),
            category=str(row["category"]),
            action=str(row["action"]),
        )

    @staticmethod
    def _to_interface_record(row: sqlite3.Row) -> EquipmentTypeInterfaceRecord:
        return EquipmentTypeInterfaceRecord(
            interface_id=int(row["id"]),
            spec_key=str(row["spec_key"]),
            group_name=str(row["group_name"]),
            interface_type=str(row["interface_type"]),
            port_count=int(row["port_count"]),
            sort_order=int(row["sort_order"]),
        )

    @staticmethod
    def _to_connection_record(row: sqlite3.Row) -> EquipmentConnectionRecord:
        return EquipmentConnectionRecord(
            connection_id=int(row["id"]),
            equipment_db_id=int(row["equipment_id"]),
            interface_type=str(row["interface_type"]),
            port_index=int(row["port_index"]),
            connection_name=str(row["connection_name"]),
        )

    @staticmethod
    def _to_port_link_record(row: sqlite3.Row) -> EquipmentPortLinkRecord:
        return EquipmentPortLinkRecord(
            link_id=int(row["id"]),
            a_equipment_db_id=int(row["a_equipment_id"]),
            a_interface_type=str(row["a_interface_type"]),
            a_port_index=int(row["a_port_index"]),
            b_equipment_db_id=int(row["b_equipment_id"]),
            b_interface_type=str(row["b_interface_type"]),
            b_port_index=int(row["b_port_index"]),
            a_equipment_id=str(row["a_equipment_code"]),
            a_equipment_name=str(row["a_equipment_name"]),
            a_connection_name=str(row["a_connection_name"] or ""),
            b_equipment_id=str(row["b_equipment_code"]),
            b_equipment_name=str(row["b_equipment_name"]),
            b_connection_name=str(row["b_connection_name"] or ""),
        )
