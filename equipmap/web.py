"""EquipMap 로컬 웹 서버와 JSON API."""

from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
import shutil
from threading import Timer
import webbrowser

from flask import Flask, jsonify, render_template, request, send_from_directory

from equipmap.database import DEFAULT_DB_PATH, EquipmentRecord, EquipmentRepository
from equipmap.image_search import (
    ImageSearchError,
    MAX_DOWNLOAD_BYTES,
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
    return payload


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
        return jsonify(
            [
                {
                    **asdict(record),
                    "category_icon_url": (
                        f"/assets/{Path(record.category_icon_path).name}"
                    ),
                    "image_url": f"/assets/{Path(record.image_path).name}",
                }
                for record in records
            ]
        )

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
        created_ids: list[int] = []
        for db_id in db_ids:
            source = by_id.get(db_id)
            if source is None:
                continue
            created = repository.create(
                spec_key=source.spec_key,
                equipment_name=source.equipment_name,
                world_x=source.world_x + offset_x,
                world_y=source.world_y + offset_y,
                layout_width=source.layout_width,
                layout_height=source.layout_height,
                locked=source.locked,
            )
            repository.update_details(
                created.db_id,
                equipment_name=source.equipment_name,
                equipment_vendor=source.equipment_vendor,
                equipment_model=source.equipment_model,
                asset_number=source.asset_number,
                serial_number=source.serial_number,
            )
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
            created_ids.append(created.db_id)

        if not created_ids:
            return jsonify({"error": "복사할 장비를 찾을 수 없습니다."}), 404
        created_by_id = {
            record.db_id: record
            for record in repository.list_all()
            if record.db_id in created_ids
        }
        return jsonify(
            [
                _equipment_payload(created_by_id[db_id])
                for db_id in created_ids
            ]
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
            return jsonify({"error": str(error)}), 404

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
            }
        )

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

    @app.delete("/api/equipment/<int:db_id>")
    def equipment_delete(db_id: int):
        repository.delete(db_id)
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
