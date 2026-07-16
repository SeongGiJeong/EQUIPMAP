"""좌측 장비 배치 팔레트."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence

import tkinter as tk
from tkinter import font as tkfont
from PIL import Image, ImageTk

from equipmap.catalog import RackSpec


PALETTE_BG = "#F5F6F8"
PALETTE_BORDER = "#D4D7DE"
CARD_BG = "#FFFFFF"
ACCENT = "#2F6FED"


class EquipmentPalette(tk.Frame):
    """서버랙 등 배치 장비를 고르는 좌측 목록."""

    def __init__(
        self,
        master: tk.Misc,
        specs: Sequence[RackSpec],
        on_select_rack: Callable[[RackSpec], None],
        **kwargs,
    ) -> None:
        kwargs.setdefault("bg", PALETTE_BG)
        kwargs.setdefault("highlightbackground", PALETTE_BORDER)
        kwargs.setdefault("highlightthickness", 1)
        kwargs.setdefault("width", 168)
        super().__init__(master, **kwargs)
        self.pack_propagate(False)

        self.on_select_rack = on_select_rack
        self.specs = list(specs)
        self._photos: list[ImageTk.PhotoImage] = []
        self._expanded_category: str | None = None
        self._category_buttons: dict[str, tk.Button] = {}
        self._specs_by_category: dict[str, list[RackSpec]] = defaultdict(list)
        for spec in self.specs:
            self._specs_by_category[spec.category_key].append(spec)
        self._selected_key: str | None = None

        self._build()

    def _build(self) -> None:
        header = tk.Label(
            self,
            text="장비 목록",
            bg=PALETTE_BG,
            fg="#222",
            font=tkfont.Font(family="Segoe UI", size=10, weight="bold"),
            anchor="w",
        )
        header.pack(fill="x", padx=10, pady=(10, 6))

        self.category_frame = tk.Frame(self, bg=PALETTE_BG)
        self.category_frame.pack(fill="x", padx=8)

        for category_key, specs in self._specs_by_category.items():
            first = specs[0]
            icon = (
                None
                if category_key == "rack"
                else self._load_photo(first.category_icon_path, (56, 56))
            )
            button = tk.Button(
                self.category_frame,
                image=icon,
                text=first.category_name,
                compound="top" if icon is not None else "none",
                bg=CARD_BG,
                fg="#222",
                activebackground="#EEF3FF",
                relief="solid",
                bd=1,
                padx=4,
                pady=6,
                cursor="hand2",
                font=tkfont.Font(family="Segoe UI", size=9),
                command=lambda key=category_key: self._toggle_category(key),
            )
            button.pack(fill="x", pady=(0, 5))
            self._category_buttons[category_key] = button

        self.sizes_frame = tk.Frame(self, bg=PALETTE_BG)
        # 처음엔 숨김 — 서버랙 클릭 시 표시

        tip = tk.Label(
            self,
            text="장비 종류를 누른 뒤\n모델을 선택하세요.\n캔버스를 클릭하면\n배치됩니다.",
            bg=PALETTE_BG,
            fg="#888",
            justify="left",
            font=tkfont.Font(family="Segoe UI", size=8),
        )
        tip.pack(side="bottom", fill="x", padx=10, pady=10)

    def _toggle_category(self, category_key: str) -> None:
        if self._expanded_category == category_key:
            self.sizes_frame.pack_forget()
            for child in self.sizes_frame.winfo_children():
                child.destroy()
            self._expanded_category = None
            self._category_buttons[category_key].configure(bg=CARD_BG)
            return

        for child in self.sizes_frame.winfo_children():
            child.destroy()
        self._expanded_category = category_key
        for key, button in self._category_buttons.items():
            button.configure(bg="#EEF3FF" if key == category_key else CARD_BG)
        self.sizes_frame.pack(fill="x", padx=8, pady=(8, 0), after=self.category_frame)

        specs = self._specs_by_category[category_key]
        title = tk.Label(
            self.sizes_frame,
            text=f"{specs[0].category_name} 선택",
            bg=PALETTE_BG,
            fg="#555",
            anchor="w",
            font=tkfont.Font(family="Segoe UI", size=8),
        )
        title.pack(fill="x", pady=(0, 4))

        for spec in specs:
            self._add_rack_option(spec)

    def _choose_rack(self, spec: RackSpec) -> None:
        self._selected_key = spec.key
        for child in self.sizes_frame.winfo_children():
            if not isinstance(child, tk.Frame):
                continue
            selected = getattr(child, "_rack_key", None) == spec.key
            child.configure(highlightbackground=ACCENT if selected else PALETTE_BORDER)
            child.configure(highlightthickness=2 if selected else 1)
            for btn in child.winfo_children():
                if isinstance(btn, tk.Button):
                    btn.configure(bg="#E8F0FF" if selected else CARD_BG)
        self.on_select_rack(spec)

    def _add_rack_option(self, spec: RackSpec) -> None:
        card = tk.Frame(self.sizes_frame, bg=CARD_BG, highlightbackground=PALETTE_BORDER, highlightthickness=1)
        card._rack_key = spec.key  # type: ignore[attr-defined]
        card.pack(fill="x", pady=4)

        btn = tk.Button(
            card,
            text=spec.name,
            bg=CARD_BG,
            fg="#222",
            activebackground="#EEF3FF",
            relief="flat",
            padx=10,
            pady=7,
            cursor="hand2",
            justify="left",
            font=tkfont.Font(family="Segoe UI", size=9, weight="bold"),
            command=lambda s=spec: self._choose_rack(s),
            anchor="w",
        )
        btn.pack(fill="x")

    def clear_selection(self) -> None:
        self._selected_key = None

    def _load_photo(self, path, size: tuple[int, int]) -> ImageTk.PhotoImage:
        img = Image.open(path).convert("RGBA")
        img.thumbnail(size, Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        self._photos.append(photo)
        return photo
