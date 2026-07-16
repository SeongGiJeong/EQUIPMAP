"""장비 배치 캔버스 (팬 / 줌 / 복수 선택·드래그)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
import itertools

import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk

from equipmap.catalog import RackSpec


BG_COLOR = "#FFFFFF"
SELECT_COLOR = "#2F6FED"
MARQUEE_COLOR = "#2F6FED"
MARQUEE_CROSS_COLOR = "#27AE60"
MIN_ZOOM = 0.25
MAX_ZOOM = 8.0
ZOOM_STEP = 1.15
ZOOM_COALESCE_MS = 120
SELECT_PAD = 5
NUDGE_SCREEN_PX = 2
NUDGE_COLOR = "#E67E22"
LOCKED_COLOR = "#7F8C8D"
MARQUEE_MIN_PX = 4
CONTROL_MASK = 0x0004
HOVER_DELAY_MS = 250


@dataclass
class PlacedEquipment:
    uid: int
    spec: RackSpec
    world_x: float
    world_y: float
    world_width: float
    world_height: float
    db_id: int | None = None
    equipment_id: str = ""
    equipment_name: str = ""
    equipment_vendor: str = ""
    equipment_model: str = ""
    asset_number: str = ""
    serial_number: str = ""
    locked: bool = False
    canvas_id: int | None = None
    photo: ImageTk.PhotoImage | None = field(default=None, repr=False)


class CanvasBoard(tk.Canvas):
    """흰 바탕 캔버스. 복수 선택·드래그 이동·삭제 지원."""

    def __init__(
        self,
        master: tk.Misc,
        on_view_changed: Callable[[], None] | None = None,
        on_place_mode_changed: Callable[[bool], None] | None = None,
        on_selection_changed: Callable[[tuple[PlacedEquipment, ...]], None] | None = None,
        on_equipment_created: Callable[[PlacedEquipment], None] | None = None,
        on_equipment_updated: Callable[[PlacedEquipment], None] | None = None,
        on_equipment_deleted: Callable[[PlacedEquipment], None] | None = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("bg", BG_COLOR)
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("cursor", "arrow")
        super().__init__(master, **kwargs)

        self.on_view_changed = on_view_changed
        self.on_place_mode_changed = on_place_mode_changed
        self.on_selection_changed = on_selection_changed
        self.on_equipment_created = on_equipment_created
        self.on_equipment_updated = on_equipment_updated
        self.on_equipment_deleted = on_equipment_deleted
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.zoom = 1.0

        self._pan_active = False
        self._pan_last_x = 0
        self._pan_last_y = 0

        self._id_seq = itertools.count(1)
        self.equipment: list[PlacedEquipment] = []
        self._photo_cache: dict[tuple[str, int, int], ImageTk.PhotoImage] = {}
        self._source_images: dict[str, Image.Image] = {}
        self._place_spec: RackSpec | None = None

        self._selected_ids: set[int] = set()
        self._drag_active = False
        self._drag_last_x = 0
        self._drag_last_y = 0
        self._equipment_drag_changed = False
        self._marquee_start: tuple[int, int] | None = None
        self._marquee_rect_id: int | None = None
        self._nudge_mode = False
        self._context_menu = tk.Menu(self, tearoff=0)
        self._context_menu.add_command(label="이동", command=self._menu_move)
        self._context_menu.add_command(label="고정", command=self._menu_toggle_lock)
        self._context_menu.add_separator()
        self._context_menu.add_command(label="삭제", command=self._menu_delete)

        self._hover_job: str | None = None
        self._hover_item: PlacedEquipment | None = None
        self._tooltip: tk.Toplevel | None = None
        self._tooltip_label: tk.Label | None = None

        self._zoom_job: str | None = None
        self._pending_zoom: float | None = None
        self._configure_job: str | None = None

        self.bind("<Configure>", self._on_configure)
        self.bind("<ButtonPress-1>", self._on_left_press)
        self.bind("<B1-Motion>", self._on_left_drag)
        self.bind("<ButtonRelease-1>", self._on_left_release)
        self.bind("<Button-3>", self._on_right_click)
        self.bind("<ButtonPress-2>", self._on_pan_start)
        self.bind("<B2-Motion>", self._on_pan_move)
        self.bind("<ButtonRelease-2>", self._on_pan_end)
        self.bind("<Motion>", self._on_hover_motion)
        self.bind("<Leave>", self._on_hover_leave)
        self.bind("<Button-4>", self._on_mouse_wheel_linux_up)
        self.bind("<Button-5>", self._on_mouse_wheel_linux_down)
        self.bind("<Delete>", self._on_delete_key)
        self.bind("<Left>", lambda e: self._on_nudge_key(-1, 0))
        self.bind("<Right>", lambda e: self._on_nudge_key(1, 0))
        self.bind("<Up>", lambda e: self._on_nudge_key(0, -1))
        self.bind("<Down>", lambda e: self._on_nudge_key(0, 1))

    def destroy(self) -> None:
        """예약된 Tk 콜백을 취소한 뒤 안전하게 캔버스를 종료."""
        for job_name in ("_zoom_job", "_configure_job", "_hover_job"):
            job = getattr(self, job_name, None)
            if job is not None:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
                setattr(self, job_name, None)
        self._hide_tooltip()
        super().destroy()

    # --- 배치 모드 ---------------------------------------------------------

    def start_place_mode(self, spec: RackSpec) -> None:
        self.cancel_nudge_mode()
        self.clear_selection()
        self._place_spec = spec
        self.configure(cursor="crosshair")
        if self.on_place_mode_changed:
            self.on_place_mode_changed(True)

    def cancel_place_mode(self) -> bool:
        if self._place_spec is None:
            return False
        self._place_spec = None
        self.configure(cursor="arrow")
        if self.on_place_mode_changed:
            self.on_place_mode_changed(False)
        return True

    @property
    def place_mode(self) -> bool:
        return self._place_spec is not None

    @property
    def selection(self) -> tuple[PlacedEquipment, ...]:
        by_uid = {item.uid: item for item in self.equipment}
        return tuple(by_uid[uid] for uid in sorted(self._selected_ids) if uid in by_uid)

    def _selected_items(self) -> list[PlacedEquipment]:
        by_uid = {item.uid: item for item in self.equipment}
        return [by_uid[uid] for uid in self._selected_ids if uid in by_uid]

    def _movable_selected_items(self) -> list[PlacedEquipment]:
        return [item for item in self._selected_items() if not item.locked]

    @property
    def selected(self) -> PlacedEquipment | None:
        """단일 선택 호환용 — 1개일 때만 반환."""
        items = self.selection
        if len(items) == 1:
            return items[0]
        return None

    @property
    def has_selection(self) -> bool:
        return bool(self._selected_ids)

    @property
    def nudge_mode(self) -> bool:
        return self._nudge_mode

    def place_equipment(self, spec: RackSpec, world_x: float, world_y: float) -> PlacedEquipment:
        world_width, world_height = self._default_item_size(spec)
        if spec.key == "rack_46ru":
            racks = [
                item
                for item in self.equipment
                if item.spec.key == "rack_46ru"
            ]
            if racks:
                anchor = min(
                    racks,
                    key=lambda item: (
                        (item.world_x - world_x) ** 2
                        + (item.world_y - world_y) ** 2
                    ),
                )
                row = [
                    item
                    for item in racks
                    if abs(item.world_y - anchor.world_y) < 0.01
                ]
                if world_x >= anchor.world_x:
                    right_edge = max(
                        item.world_x + item.world_width / 2
                        for item in row
                    )
                    world_x = right_edge + world_width / 2
                else:
                    left_edge = min(
                        item.world_x - item.world_width / 2
                        for item in row
                    )
                    world_x = left_edge - world_width / 2
                world_y = anchor.world_y
        item = PlacedEquipment(
            uid=next(self._id_seq),
            spec=spec,
            world_x=world_x,
            world_y=world_y,
            world_width=world_width,
            world_height=world_height,
            equipment_name=spec.name,
        )
        if self.on_equipment_created:
            self.on_equipment_created(item)
        self.equipment.append(item)
        self._draw_equipment(item, allow_resize=True)
        self.select_items([item])
        return item

    def restore_equipment(
        self,
        *,
        spec: RackSpec,
        db_id: int,
        equipment_id: str,
        equipment_name: str,
        equipment_vendor: str,
        equipment_model: str,
        asset_number: str,
        serial_number: str,
        world_x: float,
        world_y: float,
        world_width: float,
        world_height: float,
        locked: bool,
    ) -> PlacedEquipment:
        """DB에 저장된 장비를 INSERT 없이 캔버스에 복원."""
        if spec.key == "rack_46ru":
            world_width, world_height = spec.width, spec.height
        elif world_width <= 0 or world_height <= 0:
            world_width, world_height = self._default_item_size(spec)
        item = PlacedEquipment(
            uid=next(self._id_seq),
            spec=spec,
            world_x=world_x,
            world_y=world_y,
            world_width=world_width,
            world_height=world_height,
            db_id=db_id,
            equipment_id=equipment_id,
            equipment_name=equipment_name,
            equipment_vendor=equipment_vendor,
            equipment_model=equipment_model,
            asset_number=asset_number,
            serial_number=serial_number,
            locked=locked,
        )
        self.equipment.append(item)
        self._draw_equipment(item, allow_resize=True)
        return item

    def select_items(self, items: Iterable[PlacedEquipment]) -> None:
        new_ids = {item.uid for item in items}
        if new_ids != self._selected_ids:
            self._nudge_mode = False
        self._selected_ids = new_ids
        self._update_selection_boxes()
        self.focus_set()
        self._notify_selection_changed()

    def add_to_selection(self, item: PlacedEquipment) -> None:
        if item.uid in self._selected_ids:
            self.focus_set()
            return
        self._nudge_mode = False
        self._selected_ids.add(item.uid)
        self._update_selection_boxes()
        self.focus_set()
        self._notify_selection_changed()

    def clear_selection(self) -> None:
        self._nudge_mode = False
        if not self._selected_ids:
            self._clear_selection_boxes()
            return
        self._selected_ids.clear()
        self._clear_selection_boxes()
        self._notify_selection_changed()

    def start_nudge_mode(self) -> None:
        if not self._movable_selected_items():
            return
        self.cancel_place_mode()
        self._nudge_mode = True
        self.focus_set()
        self._update_selection_boxes()
        self._notify_selection_changed()

    def cancel_nudge_mode(self) -> bool:
        if not self._nudge_mode:
            return False
        self._nudge_mode = False
        self._update_selection_boxes()
        self._notify_selection_changed()
        return True

    def delete_selected(self, *, confirm: bool = True) -> bool:
        if not self._selected_ids:
            return False
        items = self._selected_items()
        if confirm:
            if len(items) == 1:
                msg = f"선택한 '{items[0].spec.name}' 장비를 삭제하시겠습니까?"
            else:
                msg = f"선택한 {len(items)}개 장비를 삭제하시겠습니까?"
            ok = messagebox.askyesno("장비 삭제", msg, parent=self.winfo_toplevel())
            if not ok:
                return False
        for item in items:
            self._remove_equipment(item, notify=False)
        self._selected_ids.clear()
        self._nudge_mode = False
        self._clear_selection_boxes()
        self._notify_selection_changed()
        return True

    def _remove_equipment(self, item: PlacedEquipment, *, notify: bool = True) -> None:
        if self.on_equipment_deleted:
            self.on_equipment_deleted(item)
        if item.canvas_id is not None:
            self.delete(f"eq-{item.uid}")
        if item in self.equipment:
            self.equipment.remove(item)
        self._selected_ids.discard(item.uid)
        if notify:
            self._nudge_mode = False
            self._update_selection_boxes()
            self._notify_selection_changed()

    def _notify_selection_changed(self) -> None:
        if self.on_selection_changed:
            self.on_selection_changed(self.selection)

    def _notify_equipment_updated(self, item: PlacedEquipment) -> None:
        if self.on_equipment_updated:
            self.on_equipment_updated(item)

    def screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        return (sx - self.offset_x) / self.zoom, (sy - self.offset_y) / self.zoom

    def world_to_screen(self, wx: float, wy: float) -> tuple[float, float]:
        return wx * self.zoom + self.offset_x, wy * self.zoom + self.offset_y

    # --- 뷰 ----------------------------------------------------------------

    def zoom_in(self, anchor_x: float | None = None, anchor_y: float | None = None) -> None:
        base = self._pending_zoom if self._pending_zoom is not None else self.zoom
        self._queue_zoom(base * ZOOM_STEP, anchor_x, anchor_y)

    def zoom_out(self, anchor_x: float | None = None, anchor_y: float | None = None) -> None:
        base = self._pending_zoom if self._pending_zoom is not None else self.zoom
        self._queue_zoom(base / ZOOM_STEP, anchor_x, anchor_y)

    def reset_view(self) -> None:
        self._cancel_pending_zoom()
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.zoom = 1.0
        self._clear_photo_cache()
        self._relayout_equipment(allow_resize=True)
        self._notify_view_changed()

    def redraw(self) -> None:
        self._relayout_equipment(allow_resize=True)

    def _queue_zoom(
        self,
        new_zoom: float,
        anchor_x: float | None,
        anchor_y: float | None,
    ) -> None:
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, new_zoom))
        cx = self.winfo_width() / 2 if anchor_x is None else anchor_x
        cy = self.winfo_height() / 2 if anchor_y is None else anchor_y
        self._pending_zoom = new_zoom

        self._apply_zoom_transform(new_zoom, cx, cy)
        self._relayout_equipment(allow_resize=False)
        self._notify_view_changed()

        if self._zoom_job is not None:
            self.after_cancel(self._zoom_job)
        self._zoom_job = self.after(ZOOM_COALESCE_MS, self._apply_pending_zoom)

    def _apply_zoom_transform(self, new_zoom: float, cx: float, cy: float) -> None:
        world_x = (cx - self.offset_x) / self.zoom
        world_y = (cy - self.offset_y) / self.zoom
        self.zoom = new_zoom
        self.offset_x = cx - world_x * self.zoom
        self.offset_y = cy - world_y * self.zoom

    def _cancel_pending_zoom(self) -> None:
        if self._zoom_job is not None:
            self.after_cancel(self._zoom_job)
            self._zoom_job = None
        self._pending_zoom = None

    def _apply_pending_zoom(self) -> None:
        self._zoom_job = None
        self._pending_zoom = None
        if not self.equipment:
            self._update_selection_boxes()
            return
        self._clear_photo_cache()
        self._relayout_equipment(allow_resize=True)

    def _relayout_equipment(self, *, allow_resize: bool) -> None:
        for item in self.equipment:
            self._draw_equipment(item, allow_resize=allow_resize)
        self._update_selection_boxes()

    def _notify_view_changed(self) -> None:
        if self.on_view_changed is not None:
            self.on_view_changed()

    def _clear_photo_cache(self) -> None:
        self._photo_cache.clear()

    # --- 히트 테스트 / 선택 박스 ----------------------------------------

    def _find_by_uid(self, uid: int) -> PlacedEquipment | None:
        for item in self.equipment:
            if item.uid == uid:
                return item
        return None

    def _hit_test(self, x: int, y: int) -> PlacedEquipment | None:
        for cid in reversed(self.find_overlapping(x - 1, y - 1, x + 1, y + 1)):
            tags = self.gettags(cid)
            for tag in tags:
                if tag.startswith("eq-"):
                    try:
                        uid = int(tag.split("-", 1)[1])
                    except ValueError:
                        continue
                    item = self._find_by_uid(uid)
                    if item is not None:
                        return item
        return None

    def _item_screen_bbox(self, item: PlacedEquipment) -> tuple[float, float, float, float]:
        sx, sy = self.world_to_screen(item.world_x, item.world_y)
        w, h = self._item_scaled_size(item)
        return sx - w / 2, sy - h / 2, sx + w / 2, sy + h / 2

    @staticmethod
    def _rects_overlap(
        a: tuple[float, float, float, float],
        b: tuple[float, float, float, float],
    ) -> bool:
        ax0, ay0, ax1, ay1 = a
        bx0, by0, bx1, by1 = b
        left = max(min(ax0, ax1), min(bx0, bx1))
        right = min(max(ax0, ax1), max(bx0, bx1))
        top = max(min(ay0, ay1), min(by0, by1))
        bottom = min(max(ay0, ay1), max(by0, by1))
        return left <= right and top <= bottom

    def _items_in_marquee(self, x0: int, y0: int, x1: int, y1: int) -> list[PlacedEquipment]:
        marquee = (float(x0), float(y0), float(x1), float(y1))
        window_selection = x1 >= x0 and y1 >= y0
        if not window_selection:
            return [
                item
                for item in self.equipment
                if self._rects_overlap(self._item_screen_bbox(item), marquee)
            ]

        mx0, my0, mx1, my1 = marquee
        picked: list[PlacedEquipment] = []
        for item in self.equipment:
            ix0, iy0, ix1, iy1 = self._item_screen_bbox(item)
            if mx0 <= ix0 and my0 <= iy0 and ix1 <= mx1 and iy1 <= my1:
                picked.append(item)
        return picked

    def _clear_selection_boxes(self) -> None:
        self.delete("selection")

    def _clear_marquee(self) -> None:
        self.delete("marquee")
        self._marquee_rect_id = None

    def _update_selection_boxes(self) -> None:
        self._clear_selection_boxes()
        if not self._selected_ids:
            return
        dash = (4, 2) if self._nudge_mode else ()
        for item in self._selected_items():
            sx, sy = self.world_to_screen(item.world_x, item.world_y)
            w, h = self._item_scaled_size(item)
            x0 = sx - w / 2 - SELECT_PAD
            y0 = sy - h / 2 - SELECT_PAD
            x1 = sx + w / 2 + SELECT_PAD
            y1 = sy + h / 2 + SELECT_PAD
            kw: dict = {
                "outline": (
                    LOCKED_COLOR
                    if item.locked
                    else NUDGE_COLOR if self._nudge_mode else SELECT_COLOR
                ),
                "width": 2,
                "tags": ("selection", f"sel-{item.uid}"),
            }
            if item.locked:
                kw["dash"] = (2, 2)
            elif dash:
                kw["dash"] = dash
            self.create_rectangle(x0, y0, x1, y1, **kw)
        self.tag_raise("selection")

    def _move_selected(self, dx_screen: float, dy_screen: float) -> None:
        movable = self._movable_selected_items()
        if not movable:
            return
        dx_world = dx_screen / self.zoom
        dy_world = dy_screen / self.zoom
        for item in movable:
            item.world_x += dx_world
            item.world_y += dy_world
            self._draw_equipment(item, allow_resize=False)
        if dx_screen or dy_screen:
            self._equipment_drag_changed = True
        self._update_selection_boxes()

    # --- 이벤트 ------------------------------------------------------------

    def _on_configure(self, _event: tk.Event) -> None:
        if self._configure_job is not None:
            self.after_cancel(self._configure_job)
        self._configure_job = self.after(30, self._apply_configure)

    def _apply_configure(self) -> None:
        self._configure_job = None
        self._relayout_equipment(allow_resize=True)

    def _on_left_press(self, event: tk.Event) -> None:
        self._hide_tooltip()
        hit = self._hit_test(event.x, event.y)
        ctrl_down = bool(event.state & CONTROL_MASK)

        if self._place_spec is not None:
            if hit is not None:
                self.cancel_place_mode()
                self.select_items([hit])
                self._start_move_drag(event)
            else:
                wx, wy = self.screen_to_world(event.x, event.y)
                self.place_equipment(self._place_spec, wx, wy)
            return

        if hit is not None:
            self.cancel_nudge_mode()
            if ctrl_down:
                self.add_to_selection(hit)
            elif hit.uid not in self._selected_ids:
                self.select_items([hit])
            self._start_move_drag(event)
            return

        self.cancel_nudge_mode()
        self.clear_selection()
        self._marquee_start = (event.x, event.y)
        self._drag_active = True

    def _on_right_click(self, event: tk.Event) -> None:
        self._hide_tooltip()
        hit = self._hit_test(event.x, event.y)
        if hit is None:
            return
        self.cancel_place_mode()
        if hit.uid not in self._selected_ids:
            self.select_items([hit])
        items = self._selected_items()
        all_locked = bool(items) and all(item.locked for item in items)
        self._context_menu.entryconfigure(0, state="disabled" if all_locked else "normal")
        self._context_menu.entryconfigure(1, label="고정 해제" if all_locked else "고정")
        try:
            self._context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._context_menu.grab_release()

    def _menu_move(self) -> None:
        self.start_nudge_mode()

    def _menu_toggle_lock(self) -> None:
        items = self._selected_items()
        if not items:
            return
        new_locked = not all(item.locked for item in items)
        for item in items:
            item.locked = new_locked
            self._notify_equipment_updated(item)
        self._nudge_mode = False
        self._drag_active = False
        self.configure(cursor="arrow")
        self._update_selection_boxes()
        self._notify_selection_changed()

    def _menu_delete(self) -> None:
        self.delete_selected(confirm=True)

    def _on_delete_key(self, _event: tk.Event | None = None) -> str | None:
        if not self._selected_ids:
            return None
        self.delete_selected(confirm=True)
        return "break"

    def _on_nudge_key(self, dx: int, dy: int) -> str | None:
        movable = self._movable_selected_items()
        if not movable:
            return None
        step = NUDGE_SCREEN_PX / self.zoom
        for item in movable:
            item.world_x += dx * step
            item.world_y += dy * step
            self._draw_equipment(item, allow_resize=False)
            self._notify_equipment_updated(item)
        self._update_selection_boxes()
        self._notify_selection_changed()
        return "break"

    def _start_move_drag(self, event: tk.Event) -> None:
        self._nudge_mode = False
        self._update_selection_boxes()
        self._marquee_start = None
        self._clear_marquee()
        self._drag_active = bool(self._movable_selected_items())
        self._equipment_drag_changed = False
        self._drag_last_x = event.x
        self._drag_last_y = event.y
        self.configure(cursor="fleur" if self._drag_active else "arrow")

    def _on_left_drag(self, event: tk.Event) -> None:
        if self._marquee_start is not None:
            x0, y0 = self._marquee_start
            if self._marquee_rect_id is None:
                if abs(event.x - x0) < MARQUEE_MIN_PX and abs(event.y - y0) < MARQUEE_MIN_PX:
                    return
                self._marquee_rect_id = self.create_rectangle(
                    x0,
                    y0,
                    event.x,
                    event.y,
                    outline=MARQUEE_COLOR,
                    width=1,
                    dash=(3, 2),
                    tags="marquee",
                )
            else:
                self.coords(self._marquee_rect_id, x0, y0, event.x, event.y)
            window_selection = event.x >= x0 and event.y >= y0
            self.itemconfigure(
                self._marquee_rect_id,
                outline=MARQUEE_COLOR if window_selection else MARQUEE_CROSS_COLOR,
                dash=() if window_selection else (3, 2),
            )
            return

        if not self._drag_active or not self._selected_ids:
            return
        dx = event.x - self._drag_last_x
        dy = event.y - self._drag_last_y
        self._drag_last_x = event.x
        self._drag_last_y = event.y
        self._move_selected(dx, dy)

    def _on_left_release(self, _event: tk.Event) -> None:
        if self._marquee_rect_id is not None and self._marquee_start is not None:
            x0, y0 = self._marquee_start
            x1, y1 = _event.x, _event.y
            picked = self._items_in_marquee(x0, y0, x1, y1)
            self.select_items(picked)
            self._clear_marquee()
        self._marquee_start = None
        if self._drag_active:
            if self._equipment_drag_changed:
                for item in self._movable_selected_items():
                    self._notify_equipment_updated(item)
                self._notify_selection_changed()
            self._drag_active = False
            self._equipment_drag_changed = False
            self.configure(cursor="crosshair" if self._place_spec else "arrow")

    def _on_pan_start(self, event: tk.Event) -> None:
        self._hide_tooltip()
        self._pan_active = True
        self._pan_last_x = event.x
        self._pan_last_y = event.y
        self.configure(cursor="fleur")

    def _on_pan_move(self, event: tk.Event) -> None:
        if not self._pan_active:
            return
        dx = event.x - self._pan_last_x
        dy = event.y - self._pan_last_y
        self._pan_last_x = event.x
        self._pan_last_y = event.y
        self.offset_x += dx
        self.offset_y += dy
        self.move("equipment", dx, dy)
        self.move("selection", dx, dy)

    def _on_pan_end(self, _event: tk.Event) -> None:
        self._pan_active = False
        self._relayout_equipment(allow_resize=False)
        self.configure(cursor="crosshair" if self._place_spec else "arrow")

    def _on_mouse_wheel_linux_up(self, event: tk.Event) -> None:
        self.zoom_in(event.x, event.y)

    def _on_mouse_wheel_linux_down(self, event: tk.Event) -> None:
        self.zoom_out(event.x, event.y)

    # --- 롤오버 정보 -------------------------------------------------------

    def _on_hover_motion(self, event: tk.Event) -> None:
        if self._drag_active or self._pan_active or self._place_spec is not None:
            self._hide_tooltip()
            return

        item = self._hit_test(event.x, event.y)
        if item is None:
            self._cancel_hover_job()
            self._hover_item = None
            self._hide_tooltip()
            return

        if item is self._hover_item and self._tooltip is not None:
            self._position_tooltip(event.x_root, event.y_root)
            return

        self._cancel_hover_job()
        self._hover_item = item
        root_x, root_y = event.x_root, event.y_root
        self._hover_job = self.after(
            HOVER_DELAY_MS,
            lambda: self._show_tooltip(item, root_x, root_y),
        )

    def _on_hover_leave(self, _event: tk.Event) -> None:
        self._cancel_hover_job()
        self._hover_item = None
        self._hide_tooltip()

    def _cancel_hover_job(self) -> None:
        if self._hover_job is None:
            return
        try:
            self.after_cancel(self._hover_job)
        except tk.TclError:
            pass
        self._hover_job = None

    def _show_tooltip(
        self,
        item: PlacedEquipment,
        root_x: int,
        root_y: int,
    ) -> None:
        self._hover_job = None
        if item is not self._hover_item or not self.winfo_exists():
            return
        if (
            item.spec.key.startswith("blank_panel_")
            or item.spec.key == "drawer_2ru"
        ):
            self._hide_tooltip()
            return

        text = "\n".join(
            (
                item.equipment_name or item.spec.name,
                f"업체: {item.equipment_vendor or '-'}",
                f"모델: {item.equipment_model or '-'}",
                f"자산번호: {item.asset_number or '-'}",
                f"일련번호: {item.serial_number or '-'}",
                f"장비 ID: {item.equipment_id or '-'}",
                f"위치상태: {'고정' if item.locked else '이동 가능'}",
            )
        )

        if self._tooltip is None or not self._tooltip.winfo_exists():
            self._tooltip = tk.Toplevel(self)
            self._tooltip.withdraw()
            self._tooltip.overrideredirect(True)
            self._tooltip.attributes("-topmost", True)
            self._tooltip_label = tk.Label(
                self._tooltip,
                bg="#FFFBEA",
                fg="#202124",
                justify="left",
                anchor="w",
                relief="solid",
                bd=1,
                padx=8,
                pady=6,
                font=("Segoe UI", 9),
            )
            self._tooltip_label.pack()

        assert self._tooltip_label is not None
        self._tooltip_label.configure(text=text)
        self._position_tooltip(root_x, root_y)
        self._tooltip.deiconify()

    def _position_tooltip(self, root_x: int, root_y: int) -> None:
        if self._tooltip is None or not self._tooltip.winfo_exists():
            return
        self._tooltip.geometry(f"+{root_x + 16}+{root_y + 18}")

    def _hide_tooltip(self) -> None:
        self._hover_item = None
        if self._tooltip is not None and self._tooltip.winfo_exists():
            self._tooltip.withdraw()

    # --- 장비 --------------------------------------------------------------

    def _default_item_size(self, spec: RackSpec) -> tuple[float, float]:
        if spec.key != "rack_46ru" and spec.ru > 0:
            rack = next(
                (
                    item
                    for item in self.equipment
                    if item.spec.key == "rack_46ru"
                ),
                None,
            )
            if rack is not None:
                width = spec.width
                if spec.key.startswith("blank_panel_") or spec.key == "pdu_2ru":
                    width = rack.world_width * (485 / 600)
                return (
                    width,
                    rack.world_height * 0.92 / 46 * max(1, spec.ru),
                )
            return spec.width, spec.height
        return spec.width, spec.height

    def _item_scaled_size(self, item: PlacedEquipment) -> tuple[int, int]:
        w = max(8, int(round(item.world_width * self.zoom)))
        h = max(8, int(round(item.world_height * self.zoom)))
        return w, h

    def _get_source(self, spec: RackSpec) -> Image.Image:
        cached = self._source_images.get(spec.key)
        if cached is not None:
            return cached
        img = Image.open(spec.canvas_image_path).convert("RGBA")
        self._source_images[spec.key] = img
        return img

    def _get_photo(self, item: PlacedEquipment) -> ImageTk.PhotoImage:
        w, h = self._item_scaled_size(item)
        key = (item.spec.key, w, h)
        cached = self._photo_cache.get(key)
        if cached is not None:
            return cached
        img = self._get_source(item.spec).resize((w, h), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        stale = [k for k in self._photo_cache if k[0] == item.spec.key]
        for k in stale:
            del self._photo_cache[k]
        self._photo_cache[key] = photo
        return photo

    def _draw_equipment(self, item: PlacedEquipment, *, allow_resize: bool) -> None:
        if item.spec.key == "rack_46ru":
            self._draw_vector_rack(item)
            return
        if item.spec.key.startswith("blank_panel_"):
            self._draw_vector_blank_panel(item)
            return

        sx, sy = self.world_to_screen(item.world_x, item.world_y)

        if allow_resize or item.photo is None:
            photo = self._get_photo(item)
            item.photo = photo
        else:
            photo = item.photo

        if item.canvas_id is None:
            item.canvas_id = self.create_image(
                sx, sy, image=photo, anchor="center", tags=("equipment", f"eq-{item.uid}")
            )
        else:
            if allow_resize:
                self.itemconfigure(item.canvas_id, image=photo)
            self.coords(item.canvas_id, sx, sy)

        self.tag_raise(f"eq-{item.uid}")

    def _draw_vector_rack(self, item: PlacedEquipment) -> None:
        """해상도에 독립적인 CAD 스타일 랙 정면도를 Canvas 도형으로 그림."""
        tag = f"eq-{item.uid}"
        self.delete(tag)

        sx, sy = self.world_to_screen(item.world_x, item.world_y)
        width, height = self._item_scaled_size(item)
        x0 = sx - width / 2
        y0 = sy - height / 2
        x1 = sx + width / 2
        y1 = sy + height / 2
        tags = ("equipment", tag)

        line_width = max(1, min(3, int(round(self.zoom))))
        cad_color = "#252A31"
        item.canvas_id = self.create_rectangle(
            x0,
            y0,
            x1,
            y1,
            fill="#FFFFFF",
            outline=cad_color,
            width=max(2, line_width),
            tags=tags,
        )

        # DWG 전면도 비율: 상단 캡, 이중 측면 프레임, 하단 베이스.
        frame_inset = max(2.0, width * 0.018)
        top_height = max(7.0, height * 0.045)
        bottom_height = max(7.0, height * 0.035)
        self.create_rectangle(
            x0 + frame_inset,
            y0 + frame_inset,
            x1 - frame_inset,
            y1 - frame_inset,
            outline=cad_color,
            width=line_width,
            tags=tags,
        )

        self.create_rectangle(
            x0,
            y0,
            x1,
            y0 + top_height,
            outline=cad_color,
            width=line_width,
            tags=tags,
        )
        panel_width = width * 0.46
        self.create_rectangle(
            sx - panel_width / 2,
            y0 + top_height * 0.2,
            sx + panel_width / 2,
            y0 + top_height * 0.78,
            outline=cad_color,
            width=line_width,
            tags=tags,
        )

        opening_top = y0 + top_height
        opening_bottom = y1 - bottom_height
        side_frame = max(3.0, width * 0.045)
        self.create_rectangle(
            x0 + frame_inset,
            opening_top,
            x0 + frame_inset + side_frame,
            opening_bottom,
            outline=cad_color,
            width=line_width,
            tags=tags,
        )
        self.create_rectangle(
            x1 - frame_inset - side_frame,
            opening_top,
            x1 - frame_inset,
            opening_bottom,
            outline=cad_color,
            width=line_width,
            tags=tags,
        )

        rail_center_offset = width * 0.105
        rail_width = max(2.0, width * 0.018)
        left_rail = x0 + rail_center_offset
        right_rail = x1 - rail_center_offset
        for rail in (left_rail, right_rail):
            self.create_rectangle(
                rail - rail_width,
                opening_top,
                rail + rail_width,
                opening_bottom,
                outline=cad_color,
                width=line_width,
                tags=tags,
            )

        # DWG처럼 각 U 위치는 레일 안쪽의 짧은 눈금으로 표현.
        ru_count = max(1, item.spec.ru)
        unit_height = (opening_bottom - opening_top) / ru_count
        for unit in range(ru_count + 1):
            y = opening_top + unit * unit_height
            for rail in (left_rail, right_rail):
                self.create_line(
                    rail - rail_width,
                    y,
                    rail + rail_width,
                    y,
                    fill=cad_color,
                    width=1,
                    tags=tags,
                )

        # 랙 하단을 1U로 보고 위쪽으로 올라가며 5U 단위 번호를 표시.
        label_x = left_rail - rail_width - max(5.0, width * 0.025)
        label_size = max(1, min(20, int(round(unit_height * 1.35))))
        for unit in range(5, ru_count + 1, 5):
            y = opening_bottom - unit * unit_height
            self.create_text(
                label_x,
                y,
                text=str(unit),
                anchor="e",
                fill="#9AA0A8",
                # 음수 크기는 Tk 포인트가 아닌 픽셀 단위이므로 줌과 정확히 연동됨.
                font=("Segoe UI", -label_size),
                tags=tags,
            )

        # CAD 원본처럼 하단 플린스는 빈 프레임만 유지.
        self.create_rectangle(
            x0,
            opening_bottom,
            x1,
            y1,
            outline=cad_color,
            width=line_width,
            tags=tags,
        )

        self.tag_raise(tag)

    def _draw_vector_blank_panel(self, item: PlacedEquipment) -> None:
        """DWG의 485×44 1RU 형상을 RU 높이만큼 반복해 그림."""
        tag = f"eq-{item.uid}"
        self.delete(tag)

        sx, sy = self.world_to_screen(item.world_x, item.world_y)
        width, height = self._item_scaled_size(item)
        x0 = sx - width / 2
        y0 = sy - height / 2
        x1 = sx + width / 2
        y1 = sy + height / 2
        tags = ("equipment", tag)
        line_width = max(1, min(3, int(round(self.zoom))))
        cad_color = "#252A31"

        item.canvas_id = self.create_rectangle(
            x0,
            y0,
            x1,
            y1,
            fill="#FFFFFF",
            outline=cad_color,
            width=line_width,
            tags=tags,
        )

        slot_margin_x = width * 0.09
        slot_gap = width * 0.035
        slot_width = (width - slot_margin_x * 2 - slot_gap * 3) / 4
        ru_count = max(1, item.spec.ru)
        unit_height = height / ru_count

        for row in range(ru_count):
            slot_y0 = y0 + row * unit_height + unit_height * 0.22
            slot_y1 = y0 + (row + 1) * unit_height - unit_height * 0.22
            radius = max(
                1.0,
                min(slot_width * 0.18, (slot_y1 - slot_y0) / 2),
            )
            for index in range(4):
                left = x0 + slot_margin_x + index * (slot_width + slot_gap)
                right = left + slot_width
                points = (
                    left + radius,
                    slot_y0,
                    right - radius,
                    slot_y0,
                    right,
                    slot_y0,
                    right,
                    slot_y0 + radius,
                    right,
                    slot_y1 - radius,
                    right,
                    slot_y1,
                    right - radius,
                    slot_y1,
                    left + radius,
                    slot_y1,
                    left,
                    slot_y1,
                    left,
                    slot_y1 - radius,
                    left,
                    slot_y0 + radius,
                    left,
                    slot_y0,
                )
                self.create_polygon(
                    points,
                    smooth=True,
                    splinesteps=12,
                    fill="#FFFFFF",
                    outline=cad_color,
                    width=1,
                    tags=tags,
                )

        self.tag_raise(tag)
