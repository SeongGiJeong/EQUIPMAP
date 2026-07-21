"""EquipMap 로컬 웹 서버와 JSON API."""

from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
import shutil
from threading import Timer
import webbrowser

from flask import Flask, jsonify, render_template, request, send_from_directory

from equipmap.database import (
    DEFAULT_DB_PATH,
    EquipmentConnectionRecord,
    EquipmentLogRecord,
    EquipmentPortLinkRecord,
    EquipmentRecord,
    EquipmentRepository,
    EquipmentTypeInterfaceRecord,
    EquipmentTypeRecord,
)
from equipmap.image_search import (
    ImageSearchError,
    MAX_DOWNLOAD_BYTES,
    google_images_search_url,
    save_equipment_image_content,
    search_and_save_equipment_image,
)


PACKAGE_DIR = Path(__file__).resolve().parent
ASSET_DIR = PACKAGE_DIR / "assets"
EQUIPMENT_IMAGE_DIR = PACKAGE_DIR.parent / "equipment_images"


def _equipment_payload(record: EquipmentRecord) -> dict:
    payload = asdict(record)
    payload["photo_url"] = (
        f"/equipment-images/{Path(record.photo_path).name}"
        if record.photo_path
        else ""
    )
    payload["parent_equipment_id"] = record.parent_equipment_id
    payload["slot_index"] = record.slot_index
    return payload


def _equipment_type_payload(
    record: EquipmentTypeRecord,
    interfaces: list[EquipmentTypeInterfaceRecord] | None = None,
) -> dict:
    return {
        **asdict(record),
        "category_icon_url": (
            f"/assets/{Path(record.category_icon_path).name}"
        ),
        "image_url": f"/assets/{Path(record.image_path).name}",
        "interfaces": [
            {
                "interface_id": item.interface_id,
                "group_name": item.group_name,
                "interface_type": item.interface_type,
                "port_count": item.port_count,
                "sort_order": item.sort_order,
            }
            for item in (interfaces or [])
        ],
    }


def _equipment_types_payload(
    repository: EquipmentRepository,
    records: list[EquipmentTypeRecord],
) -> list[dict]:
    interfaces_by_key = repository.list_type_interfaces(
        [record.key for record in records]
    )
    return [
        _equipment_type_payload(
            record,
            interfaces_by_key.get(record.key, []),
        )
        for record in records
    ]


def _equipment_log_payload(record: EquipmentLogRecord) -> dict:
    return asdict(record)


def _equipment_connection_payload(record: EquipmentConnectionRecord) -> dict:
    return {
        "connection_id": record.connection_id,
        "interface_type": record.interface_type,
        "port_index": record.port_index,
        "connection_name": record.connection_name,
    }


def _equipment_port_link_payload(record: EquipmentPortLinkRecord) -> dict:
    return {
        "link_id": record.link_id,
        "a_equipment_db_id": record.a_equipment_db_id,
        "a_interface_type": record.a_interface_type,
        "a_port_index": record.a_port_index,
        "a_equipment_id": record.a_equipment_id,
        "a_equipment_name": record.a_equipment_name,
        "a_connection_name": record.a_connection_name,
        "b_equipment_db_id": record.b_equipment_db_id,
        "b_interface_type": record.b_interface_type,
        "b_port_index": record.b_port_index,
        "b_equipment_id": record.b_equipment_id,
        "b_equipment_name": record.b_equipment_name,
        "b_connection_name": record.b_connection_name,
    }


def create_app(db_path: str | Path = DEFAULT_DB_PATH) -> Flask:
    app = Flask(__name__)
    repository = EquipmentRepository(db_path)

    @app.after_request
    def disable_browser_cache(response):
        if (
            request.path == "/"
            or request.path.startswith("/static/")
            or request.path.startswith("/equipment-images/")
        ):
            response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/assets/<path:filename>")
    def equipment_asset(filename: str):
        return send_from_directory(ASSET_DIR, filename)

    @app.get("/equipment-images/<path:filename>")
    def equipment_image(filename: str):
        return send_from_directory(EQUIPMENT_IMAGE_DIR, filename)

    @app.get("/api/equipment-types")
    def equipment_types():
        records = repository.list_equipment_types()
        return jsonify(_equipment_types_payload(repository, records))

    @app.put("/api/equipment-types/<spec_key>/interfaces")
    def equipment_type_interfaces_update(spec_key: str):
        values = request.get_json(silent=True) or {}
        raw_interfaces = values.get("interfaces")
        if not isinstance(raw_interfaces, list):
            return jsonify({"error": "인터페이스 목록이 올바르지 않습니다."}), 400
        if not all(isinstance(item, dict) for item in raw_interfaces):
            return jsonify({"error": "인터페이스 항목이 올바르지 않습니다."}), 400
        try:
            spec_keys, interfaces = repository.replace_type_interfaces(
                spec_key,
                raw_interfaces,
            )
        except (TypeError, ValueError) as error:
            return jsonify({"error": str(error)}), 400
        return jsonify(
            {
                "spec_keys": spec_keys,
                "interfaces": [
                    {
                        "interface_id": item.interface_id,
                        "group_name": item.group_name,
                        "interface_type": item.interface_type,
                        "port_count": item.port_count,
                        "sort_order": item.sort_order,
                    }
                    for item in interfaces
                ],
            }
        )

    @app.post("/api/equipment-types")
    def equipment_type_create():
        values = request.get_json(silent=True) or {}
        try:
            record = repository.create_equipment_type(
                category_name=str(values.get("category_name", "")),
                name=str(values.get("name", "")),
                id_prefix=str(values.get("id_prefix", "")),
                ru=int(values.get("ru", 1)),
                is_half=bool(values.get("is_half", False)),
            )
        except (TypeError, ValueError) as error:
            return jsonify({"error": str(error)}), 400
        return jsonify(_equipment_type_payload(record, [])), 201

    @app.patch("/api/equipment-types/category")
    def equipment_category_update():
        values = request.get_json(silent=True) or {}
        try:
            records = repository.update_category_name(
                category_key=str(values.get("category_key", "")).strip(),
                category_name=str(values.get("category_name", "")),
            )
        except (TypeError, ValueError) as error:
            return jsonify({"error": str(error)}), 400
        return jsonify(_equipment_types_payload(repository, records))

    @app.patch("/api/equipment-types/group")
    def equipment_type_group_update():
        values = request.get_json(silent=True) or {}
        raw_keys = values.get("spec_keys") or []
        if not isinstance(raw_keys, list):
            return jsonify({"error": "장비 종류 목록이 올바르지 않습니다."}), 400
        try:
            raw_ru = values.get("ru")
            raw_category = values.get("category_name")
            raw_half = values.get("is_half")
            records = repository.update_equipment_type_group(
                spec_keys=[str(key) for key in raw_keys],
                name=str(values.get("name", "")),
                category_name=(
                    str(raw_category) if raw_category is not None else None
                ),
                ru=int(raw_ru) if raw_ru is not None else None,
                is_half=bool(raw_half) if raw_half is not None else None,
            )
        except (TypeError, ValueError) as error:
            return jsonify({"error": str(error)}), 400
        return jsonify(_equipment_types_payload(repository, records))

    @app.delete("/api/equipment-types/group")
    def equipment_type_group_delete():
        values = request.get_json(silent=True) or {}
        raw_keys = values.get("spec_keys") or []
        if not isinstance(raw_keys, list):
            return jsonify({"error": "장비 종류 목록이 올바르지 않습니다."}), 400
        try:
            deleted = repository.delete_equipment_types(
                spec_keys=[str(key) for key in raw_keys],
            )
        except (TypeError, ValueError) as error:
            return jsonify({"error": str(error)}), 400
        return jsonify({"deleted": deleted})

    @app.get("/api/equipment")
    def equipment_list():
        return jsonify(
            [_equipment_payload(record) for record in repository.list_all()]
        )

    @app.post("/api/equipment")
    def equipment_create():
        values = request.get_json(silent=True) or {}
        spec_key = str(values.get("spec_key", "")).strip()
        type_by_key = {
            record.key: record
            for record in repository.list_equipment_types()
        }
        spec = type_by_key.get(spec_key)
        if spec is None:
            return jsonify({"error": "알 수 없는 장비 종류입니다."}), 400

        try:
            record = repository.create(
                spec_key=spec_key,
                equipment_name=str(
                    values.get("equipment_name") or spec.name
                ),
                world_x=float(values.get("world_x", 0)),
                world_y=float(values.get("world_y", 0)),
                layout_width=float(values.get("layout_width", spec.width)),
                layout_height=float(values.get("layout_height", spec.height)),
                locked=bool(values.get("locked", False)),
            )
        except (TypeError, ValueError) as error:
            return jsonify({"error": str(error)}), 400
        return jsonify(_equipment_payload(record)), 201

    @app.post("/api/equipment/clone")
    def equipment_clone():
        values = request.get_json(silent=True) or {}
        raw_ids = values.get("db_ids") or []
        if not isinstance(raw_ids, list) or not raw_ids:
            return jsonify({"error": "복사할 장비가 없습니다."}), 400
        if len(raw_ids) > 100:
            return jsonify({"error": "한 번에 최대 100개까지 복사할 수 있습니다."}), 400
        try:
            db_ids = [int(value) for value in raw_ids]
            offset_x = float(values.get("offset_x", 20))
            offset_y = float(values.get("offset_y", 20))
        except (TypeError, ValueError) as error:
            return jsonify({"error": str(error)}), 400

        by_id = {
            record.db_id: record
            for record in repository.list_all()
        }
        raw_parent = values.get("parent_db_id")
        target_parent_id = int(raw_parent) if raw_parent is not None else None
        raw_slot = values.get("slot_index")
        target_slot_index = int(raw_slot) if raw_slot is not None else None
        created_records: list[EquipmentRecord] = []
        for db_id in db_ids:
            source = by_id.get(db_id)
            if source is None:
                continue
            try:
                created = repository.clone_equipment(
                    source.db_id,
                    offset_x=offset_x,
                    offset_y=offset_y,
                    parent_db_id=(
                        target_parent_id
                        if source.parent_equipment_id is not None
                        else None
                    ),
                    slot_index=(
                        target_slot_index
                        if (
                            source.parent_equipment_id is not None
                            and target_slot_index is not None
                        )
                        else None
                    ),
                )
            except (TypeError, ValueError) as error:
                return jsonify({"error": str(error)}), 400
            # 지정 슬롯은 첫 카드에만 적용하고, 나머지는 빈 슬롯에 순차 배치
            target_slot_index = None
            if source.photo_path:
                source_photo = (
                    EQUIPMENT_IMAGE_DIR / Path(source.photo_path).name
                )
                if source_photo.is_file():
                    photo_name = f"equipment_{created.db_id}.jpg"
                    EQUIPMENT_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(
                        source_photo,
                        EQUIPMENT_IMAGE_DIR / photo_name,
                    )
                    repository.update_photo(
                        created.db_id,
                        photo_path=photo_name,
                        photo_source_url=source.photo_source_url,
                        photo_query=source.photo_query,
                    )
                    refreshed = repository.get(created.db_id)
                    if refreshed is not None:
                        created = refreshed
            created_records.append(created)
            if created.parent_equipment_id is None:
                created_records.extend(
                    repository.list_child_equipment(created.db_id)
                )

        if not created_records:
            return jsonify({"error": "복사할 장비를 찾을 수 없습니다."}), 404
        return jsonify(
            [_equipment_payload(record) for record in created_records]
        ), 201

    @app.patch("/api/equipment/<int:db_id>")
    def equipment_update(db_id: int):
        current = next(
            (
                record
                for record in repository.list_all()
                if record.db_id == db_id
            ),
            None,
        )
        if current is None:
            return jsonify({"error": "장비를 찾을 수 없습니다."}), 404

        values = request.get_json(silent=True) or {}
        try:
            repository.update_state(
                db_id,
                world_x=float(values.get("world_x", current.world_x)),
                world_y=float(values.get("world_y", current.world_y)),
                layout_width=float(
                    values.get("layout_width", current.layout_width)
                ),
                layout_height=float(
                    values.get("layout_height", current.layout_height)
                ),
                locked=bool(values.get("locked", current.locked)),
            )
        except (TypeError, ValueError) as error:
            return jsonify({"error": str(error)}), 400

        new_vendor = str(
            values.get("equipment_vendor", current.equipment_vendor)
        ).strip()
        new_model = str(
            values.get("equipment_model", current.equipment_model)
        ).strip()
        new_photo_query = " ".join(
            value for value in (new_vendor, new_model) if value
        )
        repository.update_details(
            db_id,
            equipment_name=str(
                values.get("equipment_name", current.equipment_name)
            ),
            equipment_vendor=new_vendor,
            equipment_model=new_model,
            asset_number=str(
                values.get("asset_number", current.asset_number)
            ),
            serial_number=str(
                values.get("serial_number", current.serial_number)
            ),
        )
        if (
            current.photo_path
            and current.photo_query != "manual"
            and new_photo_query != current.photo_query
        ):
            (EQUIPMENT_IMAGE_DIR / Path(current.photo_path).name).unlink(
                missing_ok=True
            )
            repository.update_photo(
                db_id,
                photo_path="",
                photo_source_url="",
                photo_query="",
            )
        updated = next(
            record
            for record in repository.list_all()
            if record.db_id == db_id
        )
        return jsonify(_equipment_payload(updated))

    @app.post("/api/equipment/<int:db_id>/search-image")
    def equipment_search_image(db_id: int):
        current = next(
            (
                record
                for record in repository.list_all()
                if record.db_id == db_id
            ),
            None,
        )
        if current is None:
            return jsonify({"error": "장비를 찾을 수 없습니다."}), 404
        photo_query = " ".join(
            value
            for value in (
                current.equipment_vendor,
                current.equipment_model,
            )
            if value
        )
        try:
            saved = search_and_save_equipment_image(
                photo_query,
                db_id=db_id,
                target_directory=EQUIPMENT_IMAGE_DIR,
            )
        except ImageSearchError as error:
            return jsonify(
                {
                    "error": str(error),
                    "google_images_url": google_images_search_url(photo_query),
                }
            ), 404

        repository.update_photo(
            db_id,
            photo_path=saved.filename,
            photo_source_url=saved.source_url,
            photo_query=photo_query,
        )
        updated = next(
            record
            for record in repository.list_all()
            if record.db_id == db_id
        )
        return jsonify(
            {
                **_equipment_payload(updated),
                "photo_title": saved.title,
                "photo_source_label": saved.source_label,
            }
        )

    @app.post("/api/equipment/<int:db_id>/clear-photo")
    @app.delete("/api/equipment/<int:db_id>/photo")
    def equipment_clear_photo(db_id: int):
        current = next(
            (
                record
                for record in repository.list_all()
                if record.db_id == db_id
            ),
            None,
        )
        if current is None:
            return jsonify({"error": "장비를 찾을 수 없습니다."}), 404
        if current.photo_path:
            photo_file = EQUIPMENT_IMAGE_DIR / Path(current.photo_path).name
            if photo_file.is_file():
                try:
                    photo_file.unlink()
                except OSError:
                    pass
        repository.update_photo(
            db_id,
            photo_path="",
            photo_source_url="",
            photo_query="",
        )
        updated = next(
            (
                record
                for record in repository.list_all()
                if record.db_id == db_id
            ),
            None,
        )
        if updated is None:
            return jsonify({"error": "장비를 찾을 수 없습니다."}), 404
        return jsonify(_equipment_payload(updated))

    @app.post("/api/equipment/<int:db_id>/upload-image")
    def equipment_upload_image(db_id: int):
        current = next(
            (
                record
                for record in repository.list_all()
                if record.db_id == db_id
            ),
            None,
        )
        if current is None:
            return jsonify({"error": "장비를 찾을 수 없습니다."}), 404
        upload = request.files.get("photo")
        if upload is None or not upload.filename:
            return jsonify({"error": "등록할 이미지 파일을 선택해 주세요."}), 400
        content = upload.read(MAX_DOWNLOAD_BYTES + 1)
        try:
            filename = save_equipment_image_content(
                content,
                db_id=db_id,
                target_directory=EQUIPMENT_IMAGE_DIR,
            )
        except ImageSearchError as error:
            return jsonify({"error": str(error)}), 400

        repository.update_photo(
            db_id,
            photo_path=filename,
            photo_source_url="",
            photo_query="manual",
        )
        updated = next(
            record
            for record in repository.list_all()
            if record.db_id == db_id
        )
        return jsonify(_equipment_payload(updated))

    @app.put("/api/equipment/<int:db_id>/slots")
    def equipment_slots_update(db_id: int):
        values = request.get_json(silent=True) or {}
        try:
            record = repository.set_frame_slot_count(
                db_id,
                int(values.get("slot_count")),
            )
        except (TypeError, ValueError) as error:
            return jsonify({"error": str(error)}), 400
        return jsonify(
            {
                "frame": _equipment_payload(record),
                "slot_count": repository.frame_slot_count_for(record),
            }
        )

    @app.get("/api/equipment/<int:db_id>/slots")
    def equipment_slots(db_id: int):
        frame = repository.get(db_id)
        if frame is None:
            return jsonify({"error": "장비를 찾을 수 없습니다."}), 404
        try:
            slot_count = repository.frame_slot_count_for(frame)
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        children = {
            child.slot_index: child
            for child in repository.list_child_equipment(db_id)
            if child.slot_index is not None
        }
        slots = []
        for index in range(1, slot_count + 1):
            card = children.get(index)
            slots.append(
                {
                    "slot_index": index,
                    "card": _equipment_payload(card) if card else None,
                }
            )
        return jsonify(
            {
                "frame_db_id": db_id,
                "slot_count": slot_count,
                "slots": slots,
            }
        )

    @app.post("/api/equipment/<int:db_id>/slots/<int:slot_index>/mount")
    def equipment_slot_mount(db_id: int, slot_index: int):
        values = request.get_json(silent=True) or {}
        try:
            record = repository.mount_module_card(
                db_id,
                slot_index=slot_index,
                spec_key=str(values.get("spec_key", "")).strip(),
                equipment_name=str(values.get("equipment_name", "")),
            )
        except (TypeError, ValueError) as error:
            return jsonify({"error": str(error)}), 400
        return jsonify(_equipment_payload(record)), 201

    @app.delete("/api/equipment/<int:db_id>/slots/<int:slot_index>")
    def equipment_slot_unmount(db_id: int, slot_index: int):
        try:
            repository.unmount_module_card(db_id, slot_index)
        except ValueError as error:
            return jsonify({"error": str(error)}), 404
        return ("", 204)

    @app.delete("/api/equipment/<int:db_id>")
    def equipment_delete(db_id: int):
        repository.delete(db_id)
        return ("", 204)

    @app.get("/api/equipment/<int:db_id>/connections")
    def equipment_connections(db_id: int):
        current = next(
            (
                record
                for record in repository.list_all()
                if record.db_id == db_id
            ),
            None,
        )
        if current is None:
            return jsonify({"error": "장비를 찾을 수 없습니다."}), 404
        return jsonify(
            [
                _equipment_connection_payload(record)
                for record in repository.list_connections(db_id)
            ]
        )

    @app.put("/api/equipment/<int:db_id>/connections")
    def equipment_connections_update(db_id: int):
        values = request.get_json(silent=True) or {}
        raw_names = values.get("connection_names")
        if not isinstance(raw_names, list):
            return jsonify({"error": "연결 이름 목록이 올바르지 않습니다."}), 400
        try:
            records = repository.replace_connections(
                db_id,
                interface_type=str(values.get("interface_type", "")),
                connection_names=[str(name) for name in raw_names],
            )
        except (TypeError, ValueError) as error:
            return jsonify({"error": str(error)}), 400
        return jsonify(
            [_equipment_connection_payload(record) for record in records]
        )

    @app.get("/api/port-links")
    def all_port_links():
        return jsonify(
            [
                _equipment_port_link_payload(record)
                for record in repository.list_port_links()
            ]
        )

    @app.get("/api/equipment/<int:db_id>/port-links")
    def equipment_port_links(db_id: int):
        current = next(
            (
                record
                for record in repository.list_all()
                if record.db_id == db_id
            ),
            None,
        )
        if current is None:
            return jsonify({"error": "장비를 찾을 수 없습니다."}), 404
        return jsonify(
            [
                _equipment_port_link_payload(record)
                for record in repository.list_port_links(db_id)
            ]
        )

    @app.post("/api/equipment/port-links")
    def equipment_port_link_create():
        values = request.get_json(silent=True) or {}
        source = values.get("from") or {}
        target = values.get("to") or {}
        if not isinstance(source, dict) or not isinstance(target, dict):
            return jsonify({"error": "연결 정보가 올바르지 않습니다."}), 400
        try:
            record = repository.upsert_port_link(
                from_equipment_db_id=int(source.get("db_id")),
                from_interface_type=str(source.get("interface_type", "")),
                from_port_index=int(source.get("port_index")),
                to_equipment_db_id=int(target.get("db_id")),
                to_interface_type=str(target.get("interface_type", "")),
                to_port_index=int(target.get("port_index")),
            )
        except (TypeError, ValueError) as error:
            return jsonify({"error": str(error)}), 400
        return jsonify(_equipment_port_link_payload(record)), 201

    @app.delete("/api/equipment/port-links/<int:link_id>")
    def equipment_port_link_delete(link_id: int):
        try:
            repository.delete_port_link(link_id)
        except ValueError as error:
            return jsonify({"error": str(error)}), 404
        return ("", 204)

    @app.get("/api/equipment/<int:db_id>/logs")
    def equipment_logs(db_id: int):
        current = next(
            (
                record
                for record in repository.list_all()
                if record.db_id == db_id
            ),
            None,
        )
        if current is None:
            return jsonify({"error": "장비를 찾을 수 없습니다."}), 404
        return jsonify(
            [
                _equipment_log_payload(record)
                for record in repository.list_logs(db_id)
            ]
        )

    @app.post("/api/equipment/<int:db_id>/logs")
    def equipment_log_create(db_id: int):
        values = request.get_json(silent=True) or {}
        try:
            record = repository.create_log(
                db_id,
                log_date=str(values.get("log_date", "")),
                category=str(values.get("category", "")),
                action=str(values.get("action", "")),
            )
        except (TypeError, ValueError) as error:
            return jsonify({"error": str(error)}), 400
        return jsonify(_equipment_log_payload(record)), 201

    @app.patch("/api/equipment/<int:db_id>/logs/<int:log_id>")
    def equipment_log_update(db_id: int, log_id: int):
        values = request.get_json(silent=True) or {}
        try:
            record = repository.update_log(
                db_id,
                log_id,
                log_date=str(values.get("log_date", "")),
                category=str(values.get("category", "")),
                action=str(values.get("action", "")),
            )
        except (TypeError, ValueError) as error:
            return jsonify({"error": str(error)}), 400
        return jsonify(_equipment_log_payload(record))

    @app.delete("/api/equipment/<int:db_id>/logs/<int:log_id>")
    def equipment_log_delete(db_id: int, log_id: int):
        try:
            repository.delete_log(db_id, log_id)
        except ValueError as error:
            return jsonify({"error": str(error)}), 404
        return ("", 204)

    @app.post("/api/equipment/restore")
    def equipment_restore():
        values = request.get_json(silent=True) or {}
        raw_ids = values.get("db_ids") or []
        if not isinstance(raw_ids, list) or not raw_ids:
            return jsonify({"error": "복원할 장비가 없습니다."}), 400
        if len(raw_ids) > 100:
            return jsonify({"error": "한 번에 최대 100개까지 복원할 수 있습니다."}), 400
        restored: list[EquipmentRecord] = []
        for value in raw_ids:
            try:
                record = repository.restore(int(value))
            except (TypeError, ValueError):
                continue
            if record is not None:
                restored.append(record)
        if not restored:
            return jsonify({"error": "복원할 장비를 찾을 수 없습니다."}), 404
        return jsonify([_equipment_payload(record) for record in restored])

    return app


def run(*, open_browser: bool = True) -> None:
    """개발 서버를 실행하고 코드 변경 시 자동으로 다시 시작."""
    if open_browser and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        Timer(0.8, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    create_app().run(
        host="127.0.0.1",
        port=5000,
        debug=True,
        use_reloader=True,
    )


if __name__ == "__main__":
    run()
