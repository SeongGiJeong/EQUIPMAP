"""캔버스에서 선택한 장비의 정보를 표시하는 우측 패널."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
import tkinter as tk
from tkinter import font as tkfont
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from equipmap.canvas_board import PlacedEquipment


PANEL_BG = "#F5F6F8"
PANEL_BORDER = "#D4D7DE"
LABEL_COLOR = "#6B7280"
VALUE_COLOR = "#1F2937"


class EquipmentInspector(tk.Frame):
    """단일 장비 편집 및 복수 선택 요약 패널."""

    def __init__(
        self,
        master: tk.Misc,
        on_save: Callable[[PlacedEquipment, dict[str, str]], None] | None = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("bg", PANEL_BG)
        kwargs.setdefault("width", 270)
        kwargs.setdefault("highlightbackground", PANEL_BORDER)
        kwargs.setdefault("highlightthickness", 1)
        super().__init__(master, **kwargs)
        self.pack_propagate(False)
        self.on_save = on_save
        self._selected_item: PlacedEquipment | None = None
        self._edit_vars: dict[str, tk.StringVar] = {}
        self._editing = False
        self._current_items: tuple[PlacedEquipment, ...] = ()

        tk.Label(
            self,
            text="장비 정보",
            bg=PANEL_BG,
            fg="#222222",
            anchor="w",
            font=tkfont.Font(family="Segoe UI", size=10, weight="bold"),
        ).pack(fill="x", padx=12, pady=(12, 8))

        self.content = tk.Frame(self, bg=PANEL_BG)
        self.content.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.update_selection(())

    def update_selection(self, items: Sequence[PlacedEquipment]) -> None:
        self._current_items = tuple(items)
        self._selected_item = items[0] if len(items) == 1 else None
        self._editing = False
        self._render()

    def _render(self) -> None:
        self._edit_vars.clear()
        for child in self.content.winfo_children():
            child.destroy()

        if not self._current_items:
            tk.Label(
                self.content,
                text="캔버스에서 장비를\n선택하면 정보가 표시됩니다.",
                bg=PANEL_BG,
                fg="#8A8F98",
                justify="left",
                anchor="nw",
                font=tkfont.Font(family="Segoe UI", size=9),
            ).pack(fill="x", pady=4)
            return

        if len(self._current_items) == 1:
            self._show_single(self._current_items[0])
        else:
            self._show_multiple(self._current_items)

    def _show_single(self, item: PlacedEquipment) -> None:
        if (
            item.spec.key.startswith("blank_panel_")
            or item.spec.key == "drawer_2ru"
        ):
            return
        self._add_section_title("장비 정보")
        if self._editing:
            self._add_editable_row("장비이름\n(용도)", "equipment_name", item.equipment_name)
            self._add_editable_row("장비업체", "equipment_vendor", item.equipment_vendor)
            self._add_editable_row("장비모델", "equipment_model", item.equipment_model)
            self._add_editable_row("자산번호", "asset_number", item.asset_number)
            self._add_editable_row("일련번호", "serial_number", item.serial_number)
            button_row = tk.Frame(self.content, bg=PANEL_BG)
            button_row.pack(fill="x", pady=(8, 4))
            self._add_action_button(button_row, "저장", self._save, primary=True)
            self._add_action_button(button_row, "취소", self._cancel_edit)
        else:
            self._add_row("장비이름", item.equipment_name or "-")
            self._add_row("장비업체", item.equipment_vendor or "-")
            self._add_row("장비모델", item.equipment_model or "-")
            self._add_row("자산번호", item.asset_number or "-")
            self._add_row("일련번호", item.serial_number or "-")
            self._add_action_button(self.content, "수정", self._begin_edit, primary=True)

        self._add_separator()
        self._add_section_title("읽기 전용 정보")
        self._add_row("장비 ID", item.equipment_id or "-")
        self._add_row("장비 종류", item.spec.name)
        self._add_row("좌표정보", f"X {item.world_x:.1f} / Y {item.world_y:.1f}")
        self._add_row("위치 상태", "고정" if item.locked else "이동 가능")

    def _show_multiple(self, items: Sequence[PlacedEquipment]) -> None:
        counts = Counter(item.spec.ru for item in items)
        locked = sum(item.locked for item in items)
        rack_summary = ", ".join(f"{ru}RU × {count}" for ru, count in sorted(counts.items()))

        self._add_row("선택 장비", f"{len(items)}개")
        self._add_row("구성", rack_summary)
        self._add_row("고정", f"{locked}개")
        self._add_row("이동 가능", f"{len(items) - locked}개")

    def _save(self) -> None:
        item = self._selected_item
        if item is None or self.on_save is None:
            return
        values = {key: variable.get().strip() for key, variable in self._edit_vars.items()}
        self.on_save(item, values)

    def _begin_edit(self) -> None:
        if self._selected_item is None:
            return
        self._editing = True
        self._render()

    def _cancel_edit(self) -> None:
        self._editing = False
        self._render()

    def _add_action_button(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable[[], None],
        *,
        primary: bool = False,
    ) -> None:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg="#2F6FED" if primary else "#FFFFFF",
            fg="#FFFFFF" if primary else VALUE_COLOR,
            activebackground="#2459BF" if primary else "#E5E7EB",
            activeforeground="#FFFFFF" if primary else VALUE_COLOR,
            relief="solid",
            bd=0 if primary else 1,
            cursor="hand2",
            pady=5,
            font=tkfont.Font(family="Segoe UI", size=9, weight="bold"),
        )
        if isinstance(parent, tk.Frame) and parent is not self.content:
            button.pack(side="left", fill="x", expand=True, padx=2)
        else:
            button.pack(fill="x", pady=(8, 4))

    def _add_section_title(self, text: str) -> None:
        tk.Label(
            self.content,
            text=text,
            bg=PANEL_BG,
            fg="#374151",
            anchor="w",
            font=tkfont.Font(family="Segoe UI", size=9, weight="bold"),
        ).pack(fill="x", pady=(4, 6))

    def _add_editable_row(self, label: str, key: str, value: str) -> None:
        row = tk.Frame(self.content, bg=PANEL_BG)
        row.pack(fill="x", pady=4)
        tk.Label(
            row,
            text=label,
            width=9,
            bg=PANEL_BG,
            fg=LABEL_COLOR,
            anchor="w",
            justify="left",
            font=tkfont.Font(family="Segoe UI", size=9),
        ).pack(side="left")
        variable = tk.StringVar(value=value)
        self._edit_vars[key] = variable
        tk.Entry(
            row,
            textvariable=variable,
            bg="#FFFFFF",
            fg=VALUE_COLOR,
            relief="solid",
            bd=1,
            font=tkfont.Font(family="Segoe UI", size=9),
        ).pack(side="left", fill="x", expand=True, ipady=3)

    def _add_row(self, label: str, value: str) -> None:
        row = tk.Frame(self.content, bg=PANEL_BG)
        row.pack(fill="x", pady=4)
        tk.Label(
            row,
            text=label,
            width=9,
            bg=PANEL_BG,
            fg=LABEL_COLOR,
            anchor="w",
            font=tkfont.Font(family="Segoe UI", size=9),
        ).pack(side="left")
        tk.Label(
            row,
            text=value,
            bg=PANEL_BG,
            fg=VALUE_COLOR,
            anchor="w",
            justify="left",
            wraplength=125,
            font=tkfont.Font(family="Segoe UI", size=9, weight="bold"),
        ).pack(side="left", fill="x", expand=True)

    def _add_separator(self) -> None:
        tk.Frame(self.content, height=1, bg=PANEL_BORDER).pack(fill="x", pady=8)
