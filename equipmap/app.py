"""EQUIPMAP 메인 애플리케이션 창."""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont, messagebox

from equipmap.canvas_board import CanvasBoard, PlacedEquipment
from equipmap.catalog import RackSpec, spec_from_record
from equipmap.database import EquipmentRepository
from equipmap.inspector import EquipmentInspector
from equipmap.palette import EquipmentPalette


TOOLBAR_BG = "#F0F0F0"
TOOLBAR_BORDER = "#D0D0D0"
BTN_BG = "#FFFFFF"
BTN_ACTIVE = "#E8E8E8"
BTN_FG = "#333333"
STATUS_BG = "#ECEFF3"


class EquipMapApp(tk.Tk):
    def __init__(self, db_path=None) -> None:
        super().__init__()
        self.title("EQUIPMAP")
        self.configure(bg="#FFFFFF")
        self.repository = (
            EquipmentRepository()
            if db_path is None
            else EquipmentRepository(db_path)
        )
        all_specs = [
            spec_from_record(record)
            for record in self.repository.list_equipment_types(active_only=False)
        ]
        self.specs_by_key = {spec.key: spec for spec in all_specs}
        active_keys = {
            record.key for record in self.repository.list_equipment_types()
        }
        self.equipment_specs = [
            spec for spec in all_specs if spec.key in active_keys
        ]

        self._build_toolbar()

        body = tk.Frame(self, bg="#FFFFFF")
        body.pack(fill="both", expand=True)

        self.palette = EquipmentPalette(
            body,
            specs=self.equipment_specs,
            on_select_rack=self._on_select_rack,
        )
        self.palette.pack(side="left", fill="y")

        self.inspector = EquipmentInspector(
            body,
            on_save=self._save_equipment_details,
        )
        self.inspector.pack(side="right", fill="y")

        canvas_area = tk.Frame(body, bg="#FFFFFF")
        canvas_area.pack(side="left", fill="both", expand=True)

        self.board = CanvasBoard(
            canvas_area,
            on_view_changed=self._update_zoom_label,
            on_place_mode_changed=self._on_place_mode_changed,
            on_selection_changed=self._on_selection_changed,
            on_equipment_created=self._on_equipment_created,
            on_equipment_updated=self._on_equipment_updated,
            on_equipment_deleted=self._on_equipment_deleted,
        )
        self.board.pack(fill="both", expand=True)

        self.status = tk.Label(
            self,
            text="준비됨",
            anchor="w",
            bg=STATUS_BG,
            fg="#555",
            padx=10,
            pady=4,
            font=tkfont.Font(family="Segoe UI", size=9),
        )
        self.status.pack(side="bottom", fill="x")
        self._load_saved_equipment()

        self.bind_all("<MouseWheel>", self._on_global_mouse_wheel)
        self.bind("<Escape>", self._on_escape)
        self.bind("<F11>", self._toggle_fullscreen)
        self.bind_all("<Delete>", self._on_delete_key)

        self.after(50, self._enter_fullscreen)

    def _build_toolbar(self) -> None:
        bar = tk.Frame(self, bg=TOOLBAR_BG, highlightbackground=TOOLBAR_BORDER, highlightthickness=1)
        bar.pack(side="top", fill="x")

        title = tk.Label(
            bar,
            text="EQUIPMAP",
            bg=TOOLBAR_BG,
            fg="#222222",
            font=tkfont.Font(family="Segoe UI", size=11, weight="bold"),
        )
        title.pack(side="left", padx=(12, 8), pady=6)

        zoom_frame = tk.Frame(bar, bg=TOOLBAR_BG)
        zoom_frame.pack(side="right", padx=10, pady=4)

        self.zoom_label = tk.Label(
            zoom_frame,
            text="100%",
            width=5,
            bg=TOOLBAR_BG,
            fg=BTN_FG,
            font=tkfont.Font(family="Segoe UI", size=10),
        )

        btn_style = {
            "bg": BTN_BG,
            "fg": BTN_FG,
            "activebackground": BTN_ACTIVE,
            "activeforeground": BTN_FG,
            "relief": "solid",
            "bd": 1,
            "padx": 8,
            "pady": 2,
            "cursor": "hand2",
            "font": tkfont.Font(family="Segoe UI Symbol", size=12),
        }

        self.btn_zoom_out = tk.Button(zoom_frame, text="🔍−", command=self._zoom_out, **btn_style)
        self.btn_zoom_in = tk.Button(zoom_frame, text="🔍+", command=self._zoom_in, **btn_style)
        self.btn_zoom_reset = tk.Button(
            zoom_frame,
            text="1:1",
            command=self._zoom_reset,
            font=tkfont.Font(family="Segoe UI", size=9),
            bg=BTN_BG,
            fg=BTN_FG,
            activebackground=BTN_ACTIVE,
            relief="solid",
            bd=1,
            padx=6,
            pady=3,
            cursor="hand2",
        )

        self.btn_zoom_out.pack(side="left", padx=(0, 4))
        self.zoom_label.pack(side="left", padx=2)
        self.btn_zoom_in.pack(side="left", padx=(4, 8))
        self.btn_zoom_reset.pack(side="left")

        hint = tk.Label(
            bar,
            text="Ctrl+클릭:선택 추가  ·  빈곳 드래그:복수선택  ·  방향키:이동",
            bg=TOOLBAR_BG,
            fg="#888888",
            font=tkfont.Font(family="Segoe UI", size=9),
        )
        hint.pack(side="right", padx=(0, 8))

    def _on_select_rack(self, spec: RackSpec) -> None:
        self.board.start_place_mode(spec)
        self.status.configure(text=f"배치 모드: {spec.name} — 캔버스를 클릭하세요 (Esc로 취소)")

    def _on_equipment_created(self, item: PlacedEquipment) -> None:
        try:
            record = self.repository.create(
                spec_key=item.spec.key,
                equipment_name=item.equipment_name,
                world_x=item.world_x,
                world_y=item.world_y,
                layout_width=item.world_width,
                layout_height=item.world_height,
                locked=item.locked,
            )
        except Exception as error:
            messagebox.showerror("DB 저장 오류", str(error), parent=self)
            raise
        item.db_id = record.db_id
        item.equipment_id = record.equipment_id

    def _on_equipment_updated(self, item: PlacedEquipment) -> None:
        if item.db_id is None:
            return
        self.repository.update_state(
            item.db_id,
            world_x=item.world_x,
            world_y=item.world_y,
            layout_width=item.world_width,
            layout_height=item.world_height,
            locked=item.locked,
        )

    def _on_equipment_deleted(self, item: PlacedEquipment) -> None:
        if item.db_id is not None:
            self.repository.delete(item.db_id)

    def _save_equipment_details(
        self,
        item: PlacedEquipment,
        values: dict[str, str],
    ) -> None:
        details = {
            "equipment_name": values.get("equipment_name", "").strip(),
            "equipment_vendor": values.get("equipment_vendor", "").strip(),
            "equipment_model": values.get("equipment_model", "").strip(),
            "asset_number": values.get("asset_number", "").strip(),
            "serial_number": values.get("serial_number", "").strip(),
        }
        try:
            if item.db_id is not None:
                self.repository.update_details(item.db_id, **details)
        except Exception as error:
            messagebox.showerror("DB 저장 오류", str(error), parent=self)
            return

        item.equipment_name = details["equipment_name"]
        item.equipment_vendor = details["equipment_vendor"]
        item.equipment_model = details["equipment_model"]
        item.asset_number = details["asset_number"]
        item.serial_number = details["serial_number"]
        self.inspector.update_selection(self.board.selection)
        self.status.configure(text=f"{item.equipment_id} 장비 정보를 저장했습니다.")

    def _load_saved_equipment(self) -> None:
        skipped = 0
        for record in self.repository.list_all():
            spec = self.specs_by_key.get(record.spec_key)
            if spec is None:
                skipped += 1
                continue
            self.board.restore_equipment(
                spec=spec,
                db_id=record.db_id,
                equipment_id=record.equipment_id,
                equipment_name=record.equipment_name,
                equipment_vendor=record.equipment_vendor,
                equipment_model=record.equipment_model,
                asset_number=record.asset_number,
                serial_number=record.serial_number,
                world_x=record.world_x,
                world_y=record.world_y,
                world_width=record.layout_width,
                world_height=record.layout_height,
                locked=record.locked,
            )
        if skipped:
            self.status.configure(text=f"알 수 없는 장비 종류 {skipped}개를 불러오지 못했습니다.")

    def _on_place_mode_changed(self, active: bool) -> None:
        if not active:
            self.palette.clear_selection()
            if not self.board.has_selection:
                self.status.configure(text="준비됨")

    def _on_selection_changed(self, items: tuple) -> None:
        self.inspector.update_selection(items)
        if not items:
            self.status.configure(text="준비됨")
        else:
            locked_count = sum(item.locked for item in items)
            if len(items) == 1:
                label = items[0].spec.name
            else:
                label = f"{len(items)}개 장비"
            if locked_count == len(items):
                self.status.configure(
                    text=f"선택: {label} — 위치 고정됨 / 우클릭으로 고정 해제"
                )
                return
            lock_note = f" / 고정 {locked_count}개 제외" if locked_count else ""
            self.status.configure(
                text=f"선택: {label} — 드래그·방향키 이동{lock_note} / Delete 삭제"
            )

    def _on_delete_key(self, _event: tk.Event | None = None) -> str | None:
        if not self.board.has_selection:
            return None
        self.board.delete_selected(confirm=True)
        return "break"

    def _on_escape(self, _event: tk.Event | None = None) -> None:
        if self.board.cancel_nudge_mode():
            return
        if self.board.cancel_place_mode():
            return
        self._exit_fullscreen()

    def _enter_fullscreen(self) -> None:
        self.attributes("-fullscreen", True)

    def _exit_fullscreen(self) -> None:
        self.attributes("-fullscreen", False)

    def _toggle_fullscreen(self, _event: tk.Event | None = None) -> None:
        current = bool(self.attributes("-fullscreen"))
        self.attributes("-fullscreen", not current)

    def _zoom_in(self) -> None:
        self.board.zoom_in()

    def _zoom_out(self) -> None:
        self.board.zoom_out()

    def _zoom_reset(self) -> None:
        self.board.reset_view()

    def _on_global_mouse_wheel(self, event: tk.Event) -> str | None:
        widget = self.winfo_containing(event.x_root, event.y_root)
        if widget is None:
            return None
        w: tk.Misc | None = widget
        while w is not None:
            if w is self.board:
                x = event.x_root - self.board.winfo_rootx()
                y = event.y_root - self.board.winfo_rooty()
                if event.delta > 0:
                    self.board.zoom_in(x, y)
                elif event.delta < 0:
                    self.board.zoom_out(x, y)
                return "break"
            w = w.master if hasattr(w, "master") else None
        return None

    def _update_zoom_label(self) -> None:
        percent = int(round(self.board.zoom * 100))
        self.zoom_label.configure(text=f"{percent}%")


def run() -> None:
    app = EquipMapApp()
    app.mainloop()
