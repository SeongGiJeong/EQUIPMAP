const board = document.getElementById("board");
const wrap = document.getElementById("canvas-wrap");
const ctx = board.getContext("2d");
const catalog = document.getElementById("catalog");
const statusEl = document.getElementById("status");
const zoomEl = document.getElementById("zoom-reset");
const inspector = document.getElementById("inspector-content");
const placeBanner = document.getElementById("place-banner");
const tooltip = document.getElementById("tooltip");
const contextMenu = document.getElementById("context-menu");

const MIN_ZOOM = 0.25;
const MAX_ZOOM = 8;
const ZOOM_STEP = 1.15;
const RACK_SNAP_DISTANCE_PX = 64;
const state = {
  types: [],
  typeByKey: new Map(),
  items: [],
  selected: new Set(),
  zoom: 1,
  offsetX: 0,
  offsetY: 0,
  placeSpec: null,
  expandedCategory: null,
  ruSelections: { rack: 46, blank_panel: 1 },
  clipboardIds: [],
  undoStack: [],
  drag: null,
  pan: null,
  marquee: null,
  inspectorEditing: false,
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `요청 실패 (${response.status})`);
  }
  return response.status === 204 ? null : response.json();
}

function setStatus(message) {
  statusEl.textContent = message;
}

function specFor(item) {
  return state.typeByKey.get(item.spec_key);
}

function isRackKey(key) {
  return /^rack_\d+ru$/.test(key);
}

function selectedItems() {
  return state.items.filter((item) => state.selected.has(item.db_id));
}

function geometrySnapshot(item) {
  return {
    db_id: item.db_id,
    world_x: item.world_x,
    world_y: item.world_y,
    layout_width: item.layout_width,
    layout_height: item.layout_height,
  };
}

function pushUndo(action) {
  state.undoStack.push(action);
  if (state.undoStack.length > 100) state.undoStack.shift();
}

function recordMoveUndo(before, items) {
  const afterById = new Map(
    items.map((item) => [item.db_id, geometrySnapshot(item)]),
  );
  const changes = before
    .map((previous) => ({
      db_id: previous.db_id,
      before: previous,
      after: afterById.get(previous.db_id),
    }))
    .filter(({ before: previous, after }) =>
      after && (
        Math.abs(previous.world_x - after.world_x) > 0.001 ||
        Math.abs(previous.world_y - after.world_y) > 0.001 ||
        Math.abs(previous.layout_width - after.layout_width) > 0.001 ||
        Math.abs(previous.layout_height - after.layout_height) > 0.001
      ),
    );
  if (changes.length) pushUndo({ type: "move", changes });
}

function equipmentPhotoQuery(item) {
  return [item.equipment_vendor, item.equipment_model]
    .filter(Boolean)
    .join(" ");
}

function screenPoint(event) {
  const rect = board.getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

function worldPoint(x, y) {
  return {
    x: (x - state.offsetX) / state.zoom,
    y: (y - state.offsetY) / state.zoom,
  };
}

function itemBox(item) {
  const width = item.layout_width * state.zoom;
  const height = item.layout_height * state.zoom;
  const cx = item.world_x * state.zoom + state.offsetX;
  const cy = item.world_y * state.zoom + state.offsetY;
  return {
    x0: cx - width / 2,
    y0: cy - height / 2,
    x1: cx + width / 2,
    y1: cy + height / 2,
    width,
    height,
    cx,
    cy,
  };
}

function hitTest(x, y) {
  for (let index = state.items.length - 1; index >= 0; index -= 1) {
    const item = state.items[index];
    const box = itemBox(item);
    if (x >= box.x0 && x <= box.x1 && y >= box.y0 && y <= box.y1) {
      return item;
    }
  }
  return null;
}

function resizeCanvas() {
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(1, wrap.clientWidth);
  const height = Math.max(1, wrap.clientHeight);
  board.width = Math.round(width * ratio);
  board.height = Math.round(height * ratio);
  board.style.width = `${width}px`;
  board.style.height = `${height}px`;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  draw();
}

function drawGrid() {
  const width = wrap.clientWidth;
  const height = wrap.clientHeight;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);

  const spacing = 24 * state.zoom;
  if (spacing < 8) return;
  const startX = ((state.offsetX % spacing) + spacing) % spacing;
  const startY = ((state.offsetY % spacing) + spacing) % spacing;
  ctx.fillStyle = "#d8dce3";
  for (let x = startX; x < width; x += spacing) {
    for (let y = startY; y < height; y += spacing) {
      ctx.beginPath();
      ctx.arc(x, y, Math.max(0.7, Math.min(1.2, state.zoom)), 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

function drawRack(item, box) {
  const { x0, y0, x1, y1, width, height, cx } = box;
  const lineWidth = Math.max(0.6, Math.min(3, state.zoom));
  const color = "#252a31";
  ctx.save();
  ctx.fillStyle = "#fff";
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.fillRect(x0, y0, width, height);
  ctx.strokeRect(x0, y0, width, height);

  const ruCount = Math.max(1, Number(specFor(item)?.ru) || 46);
  const structuralUnit = height / (ruCount + 4);
  const inset = Math.max(width * 0.018, 0.6 * state.zoom);
  const topHeight = structuralUnit * 2.25;
  const bottomHeight = structuralUnit * 1.75;
  ctx.strokeRect(x0 + inset, y0 + inset, width - inset * 2, height - inset * 2);
  ctx.strokeRect(x0, y0, width, topHeight);

  const panelWidth = width * 0.46;
  ctx.strokeRect(
    cx - panelWidth / 2,
    y0 + topHeight * 0.2,
    panelWidth,
    topHeight * 0.58,
  );

  const openingTop = y0 + topHeight;
  const openingBottom = y1 - bottomHeight;
  const sideFrame = width * 0.045;
  ctx.strokeRect(
    x0 + inset,
    openingTop,
    sideFrame,
    openingBottom - openingTop,
  );
  ctx.strokeRect(
    x1 - inset - sideFrame,
    openingTop,
    sideFrame,
    openingBottom - openingTop,
  );

  const railOffset = width * 0.105;
  const railWidth = Math.max(width * 0.018, 0.5 * state.zoom);
  const rails = [x0 + railOffset, x1 - railOffset];
  for (const rail of rails) {
    ctx.strokeRect(
      rail - railWidth,
      openingTop,
      railWidth * 2,
      openingBottom - openingTop,
    );
  }

  const unitHeight = (openingBottom - openingTop) / ruCount;
  ctx.lineWidth = Math.max(0.45, state.zoom * 0.7);
  for (let unit = 0; unit <= ruCount; unit += 1) {
    const y = openingTop + unit * unitHeight;
    for (const rail of rails) {
      ctx.beginPath();
      ctx.moveTo(rail - railWidth, y);
      ctx.lineTo(rail + railWidth, y);
      ctx.stroke();
    }
  }

  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.strokeRect(x0, openingBottom, width, bottomHeight);
  ctx.restore();

  // 글자를 작은 화면 폰트로 다시 만들지 않고 랙과 동일한 월드 변환으로 그림.
  // 브라우저의 최소 글꼴 렌더링 크기에 걸리지 않아 랙과 정확히 같은 비율로 축척된다.
  const worldX0 = item.world_x - item.layout_width / 2;
  const worldY0 = item.world_y - item.layout_height / 2;
  const worldY1 = item.world_y + item.layout_height / 2;
  const worldStructuralUnit = item.layout_height / (ruCount + 4);
  const worldTopHeight = worldStructuralUnit * 2.25;
  const worldBottomHeight = worldStructuralUnit * 1.75;
  const worldOpeningBottom = worldY1 - worldBottomHeight;
  const worldOpeningTop = worldY0 + worldTopHeight;
  const worldUnitHeight =
    (worldOpeningBottom - worldOpeningTop) / ruCount;
  const worldRail =
    worldX0 + item.layout_width * 0.105;
  const worldRailWidth = item.layout_width * 0.018;
  const worldLabelX =
    worldRail - worldRailWidth - item.layout_width * 0.01;

  ctx.save();
  ctx.translate(state.offsetX, state.offsetY);
  ctx.scale(state.zoom, state.zoom);
  ctx.beginPath();
  ctx.rect(worldX0, worldY0, item.layout_width, item.layout_height);
  ctx.clip();

  if (item.equipment_name) {
    ctx.fillStyle = "#252a31";
    ctx.font = `${worldTopHeight * 0.32}px "Segoe UI", sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(
      item.equipment_name,
      item.world_x,
      worldY0 + worldTopHeight * 0.49,
      item.layout_width * 0.42,
    );
  }

  ctx.fillStyle = "#9aa0a8";
  ctx.font = `${worldUnitHeight * 0.78}px "Segoe UI", sans-serif`;
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let unit = 5; unit <= ruCount; unit += 5) {
    ctx.fillText(
      String(unit),
      worldLabelX,
      worldOpeningBottom - unit * worldUnitHeight,
    );
  }
  ctx.restore();
}

function drawBlankPanel(item, box) {
  const { x0, y0, width, height } = box;
  ctx.save();
  ctx.fillStyle = "rgba(128, 128, 128, 0.5)";
  ctx.strokeStyle = "#252a31";
  ctx.lineWidth = Math.max(0.6, Math.min(3, state.zoom));
  ctx.fillRect(x0, y0, width, height);
  ctx.strokeRect(x0, y0, width, height);

  ctx.fillStyle = "rgba(255, 255, 255, 0.65)";
  const ru = Math.max(1, specFor(item)?.ru || 1);
  const unitHeight = height / ru;
  const margin = width * 0.09;
  const gap = width * 0.035;
  const slotWidth = (width - margin * 2 - gap * 3) / 4;
  for (let row = 0; row < ru; row += 1) {
    const slotY = y0 + row * unitHeight + unitHeight * 0.22;
    const slotHeight = unitHeight * 0.56;
    const radius = Math.max(0.5, Math.min(slotWidth * 0.18, slotHeight / 2));
    for (let index = 0; index < 4; index += 1) {
      const left = x0 + margin + index * (slotWidth + gap);
      ctx.beginPath();
      ctx.roundRect(left, slotY, slotWidth, slotHeight, radius);
      ctx.fill();
      ctx.stroke();
    }
  }
  ctx.restore();
}

function drawPdu(_item, box) {
  const { x0, y0, width, height } = box;
  const color = "#252a31";
  const lineWidth = Math.max(0.6, Math.min(3, state.zoom));
  const cy = y0 + height / 2;
  const earWidth = width * 0.05;
  ctx.save();
  ctx.fillStyle = "#fff";
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.fillRect(x0, y0, width, height);
  ctx.strokeRect(x0, y0, width, height);
  ctx.beginPath();
  ctx.moveTo(x0 + earWidth, y0);
  ctx.lineTo(x0 + earWidth, y0 + height);
  ctx.moveTo(x0 + width - earWidth, y0);
  ctx.lineTo(x0 + width - earWidth, y0 + height);
  ctx.stroke();

  const holeWidth = earWidth * 0.42;
  const holeHeight = height * 0.12;
  for (const hx of [x0 + earWidth / 2, x0 + width - earWidth / 2]) {
    for (const hy of [y0 + height * 0.22, y0 + height * 0.78]) {
      ctx.beginPath();
      ctx.roundRect(
        hx - holeWidth / 2,
        hy - holeHeight / 2,
        holeWidth,
        holeHeight,
        holeHeight / 2,
      );
      ctx.stroke();
    }
  }

  function drawMeter(left, label) {
    const meterWidth = width * 0.145;
    const meterHeight = height * 0.43;
    const top = cy - meterHeight / 2;
    ctx.strokeRect(left, top, meterWidth, meterHeight);
    ctx.strokeRect(
      left + meterWidth * 0.09,
      top + meterHeight * 0.17,
      meterWidth * 0.68,
      meterHeight * 0.66,
    );
    ctx.fillStyle = "#667085";
    ctx.font = `${Math.max(1, height * 0.16)}px monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("88.8", left + meterWidth * 0.43, cy);
    ctx.font = `${Math.max(1, height * 0.14)}px "Segoe UI", sans-serif`;
    ctx.fillText(label, left + meterWidth * 0.87, cy);
  }
  drawMeter(x0 + width * 0.105, "V");
  drawMeter(x0 + width * 0.285, "A");

  const socketX = x0 + width * 0.57;
  const socketRadius = height * 0.29;
  ctx.strokeRect(
    socketX - socketRadius * 0.72,
    cy - socketRadius * 1.05,
    socketRadius * 1.44,
    socketRadius * 2.1,
  );
  ctx.beginPath();
  ctx.arc(socketX, cy, socketRadius, 0, Math.PI * 2);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(socketX, cy - socketRadius);
  ctx.lineTo(socketX, cy + socketRadius);
  ctx.stroke();
  for (const contactX of [-0.35, 0, 0.35]) {
    ctx.beginPath();
    ctx.arc(
      socketX + socketRadius * contactX,
      cy,
      Math.max(0.4, socketRadius * 0.1),
      0,
      Math.PI * 2,
    );
    ctx.stroke();
  }

  const breakerX = x0 + width * 0.73;
  const breakerY = y0 + height * 0.29;
  const breakerWidth = width * 0.12;
  const breakerHeight = height * 0.42;
  ctx.strokeRect(
    breakerX,
    breakerY,
    breakerWidth,
    breakerHeight,
  );
  ctx.fillStyle = "#eef0f3";
  ctx.fillRect(
    breakerX + breakerWidth * 0.68,
    breakerY + breakerHeight * 0.08,
    breakerWidth * 0.2,
    breakerHeight * 0.84,
  );
  ctx.strokeRect(
    breakerX + breakerWidth * 0.68,
    breakerY + breakerHeight * 0.08,
    breakerWidth * 0.2,
    breakerHeight * 0.84,
  );
  ctx.restore();
}

function drawDrawer(_item, box) {
  const { x0, y0, width, height } = box;
  const color = "#252a31";
  const lineWidth = Math.max(0.6, Math.min(3, state.zoom));
  const earWidth = width * 0.05;
  ctx.save();
  ctx.fillStyle = "#fff";
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.fillRect(x0, y0, width, height);
  ctx.strokeRect(x0, y0, width, height);
  ctx.beginPath();
  ctx.moveTo(x0 + earWidth, y0);
  ctx.lineTo(x0 + earWidth, y0 + height);
  ctx.moveTo(x0 + width - earWidth, y0);
  ctx.lineTo(x0 + width - earWidth, y0 + height);
  ctx.stroke();

  const holeWidth = earWidth * 0.42;
  const holeHeight = height * 0.1;
  for (const hx of [x0 + earWidth / 2, x0 + width - earWidth / 2]) {
    for (const hy of [y0 + height * 0.22, y0 + height * 0.78]) {
      ctx.beginPath();
      ctx.roundRect(
        hx - holeWidth / 2,
        hy - holeHeight / 2,
        holeWidth,
        holeHeight,
        holeHeight / 2,
      );
      ctx.stroke();
    }
  }

  const faceX = x0 + width * 0.07;
  const faceY = y0 + height * 0.13;
  const faceWidth = width * 0.86;
  const faceHeight = height * 0.74;
  ctx.beginPath();
  ctx.roundRect(
    faceX,
    faceY,
    faceWidth,
    faceHeight,
    Math.max(1, height * 0.035),
  );
  ctx.fill();
  ctx.stroke();
  ctx.strokeStyle = "#7a818b";
  ctx.beginPath();
  ctx.moveTo(faceX + faceWidth * 0.02, faceY + faceHeight * 0.12);
  ctx.lineTo(faceX + faceWidth * 0.98, faceY + faceHeight * 0.12);
  ctx.stroke();

  ctx.strokeStyle = color;
  const handleWidth = width * 0.3;
  const handleHeight = height * 0.27;
  ctx.fillStyle = "#f5f6f8";
  ctx.beginPath();
  ctx.roundRect(
    x0 + width / 2 - handleWidth / 2,
    y0 + height / 2 - handleHeight / 2,
    handleWidth,
    handleHeight,
    Math.max(1, handleHeight * 0.2),
  );
  ctx.fill();
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(x0 + width * 0.39, y0 + height / 2);
  ctx.lineTo(x0 + width * 0.61, y0 + height / 2);
  ctx.stroke();
  for (const lockX of [x0 + width * 0.115, x0 + width * 0.885]) {
    ctx.beginPath();
    ctx.arc(lockX, y0 + height / 2, height * 0.08, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();
}

function drawBroadcastDevice(item, box) {
  const { x0, y0, width, height } = box;
  const ru = Math.max(1, Number(specFor(item)?.ru) || 1);
  const oneRuHeight = height / ru;
  const color = "#252a31";
  const lineWidth = Math.max(0.6, Math.min(3, state.zoom));
  const earWidth = width * 0.05;
  ctx.save();
  ctx.fillStyle = "#fff";
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.fillRect(x0, y0, width, height);
  ctx.strokeRect(x0, y0, width, height);
  ctx.beginPath();
  ctx.moveTo(x0 + earWidth, y0);
  ctx.lineTo(x0 + earWidth, y0 + height);
  ctx.moveTo(x0 + width - earWidth, y0);
  ctx.lineTo(x0 + width - earWidth, y0 + height);
  ctx.stroke();

  const faceX = x0 + width * 0.065;
  const faceY = y0 + height * 0.12;
  const faceWidth = width * 0.87;
  const faceHeight = height * 0.76;
  ctx.fillStyle = "#f8f9fa";
  ctx.beginPath();
  ctx.roundRect(
    faceX,
    faceY,
    faceWidth,
    faceHeight,
    Math.max(1, height * 0.035),
  );
  ctx.fill();
  ctx.stroke();

  ctx.fillStyle = "#4b5563";
  ctx.font = `${Math.max(1, oneRuHeight * 0.24)}px "Segoe UI", sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(
    item.equipment_name || specFor(item)?.name || "",
    x0 + width / 2,
    y0 + height / 2,
    faceWidth * 0.88,
  );
  ctx.restore();
}

function drawEquipment() {
  for (const item of state.items) {
    const box = itemBox(item);
    if (isRackKey(item.spec_key)) drawRack(item, box);
    else if (item.spec_key.startsWith("broadcast_")) {
      drawBroadcastDevice(item, box);
    }
    else if (item.spec_key === "drawer_2ru") drawDrawer(item, box);
    else if (item.spec_key === "pdu_2ru") drawPdu(item, box);
    else if (item.spec_key.startsWith("blank_panel_")) drawBlankPanel(item, box);
  }
}

function drawSelection() {
  ctx.save();
  ctx.setLineDash([5, 3]);
  for (const item of selectedItems()) {
    const box = itemBox(item);
    ctx.strokeStyle = item.locked ? "#7f8c8d" : "#2f6fed";
    ctx.lineWidth = 1.5;
    ctx.strokeRect(box.x0 - 4, box.y0 - 4, box.width + 8, box.height + 8);
  }
  ctx.restore();
}

function drawMarquee() {
  if (!state.marquee) return;
  const { start, current } = state.marquee;
  const x = Math.min(start.x, current.x);
  const y = Math.min(start.y, current.y);
  const width = Math.abs(current.x - start.x);
  const height = Math.abs(current.y - start.y);
  const crossing = current.x < start.x;
  ctx.save();
  ctx.fillStyle = crossing ? "rgb(39 174 96 / 10%)" : "rgb(47 111 237 / 10%)";
  ctx.strokeStyle = crossing ? "#27ae60" : "#2f6fed";
  ctx.setLineDash([6, 4]);
  ctx.fillRect(x, y, width, height);
  ctx.strokeRect(x, y, width, height);
  ctx.restore();
}

function draw() {
  drawGrid();
  drawEquipment();
  drawSelection();
  drawMarquee();
  zoomEl.textContent = `${Math.round(state.zoom * 100)}%`;
}

function renderCatalog() {
  const categories = new Map();
  for (const spec of state.types) {
    if (!categories.has(spec.category_key)) categories.set(spec.category_key, []);
    categories.get(spec.category_key).push(spec);
  }

  catalog.innerHTML = "";
  const categoryOrder = { rack: 0, broadcast_equipment: 1 };
  const categoryEntries = [...categories.entries()].sort(
    ([left], [right]) =>
      (categoryOrder[left] ?? 999) - (categoryOrder[right] ?? 999),
  );
  for (const [key, specs] of categoryEntries) {
    const first = specs[0];
    const categoryButton = document.createElement("button");
    categoryButton.className = "category-card";
    if (state.expandedCategory === key) categoryButton.classList.add("active");
    categoryButton.innerHTML = `
      ${key === "rack"
        ? ""
        : `<img src="${escapeHtml(first.category_icon_url)}" alt="">`}
      <strong>${escapeHtml(first.category_name)}</strong>
    `;
    categoryButton.addEventListener("click", () => {
      state.expandedCategory = state.expandedCategory === key ? null : key;
      renderCatalog();
    });
    catalog.appendChild(categoryButton);

    if (state.expandedCategory !== key) continue;
    const list = document.createElement("div");
    list.className = "model-list";
    list.innerHTML = "<h2>장비 목록 선택</h2>";

    const addSpecButton = (spec, parent, nested = false) => {
      const button = document.createElement("button");
      button.className = nested
        ? "model-button sub-model-button"
        : "model-button";
      if (state.placeSpec?.key === spec.key) button.classList.add("selected");
      button.textContent = spec.name;
      button.draggable = true;
      button.addEventListener("click", () => startPlacement(spec));
      button.addEventListener("dragstart", (event) => {
        event.dataTransfer.setData("text/equipmap-spec", spec.key);
        event.dataTransfer.effectAllowed = "copy";
      });
      parent.appendChild(button);
    };

    const addRuSelector = (
      label,
      variants,
      selectionKey,
      minRu = 1,
      maxRu = 10,
    ) => {
      const selector = document.createElement("div");
      selector.className = "ru-size-selector";
      const selectButton = document.createElement("button");
      selectButton.className = "model-group-button";
      if (variants.some((variant) => state.placeSpec?.key === variant.key)) {
        selectButton.classList.add("active");
      }
      selectButton.textContent = label;
      const ruInput = document.createElement("input");
      ruInput.className = "ru-size-input";
      ruInput.type = "number";
      ruInput.min = String(minRu);
      ruInput.max = String(maxRu);
      ruInput.step = "1";
      ruInput.value = String(state.ruSelections[selectionKey] || minRu);
      ruInput.setAttribute("aria-label", `${label} RU 크기`);
      const suffix = document.createElement("span");
      suffix.className = "ru-size-suffix";
      suffix.textContent = "RU";
      const selectedVariant = () => {
        const ru = Math.max(
          minRu,
          Math.min(
            maxRu,
            Math.round(Number(ruInput.value) || minRu),
          ),
        );
        state.ruSelections[selectionKey] = ru;
        ruInput.value = String(ru);
        return variants.find((variant) => Number(variant.ru) === ru);
      };
      const choose = () => {
        const selected = selectedVariant();
        if (selected) startPlacement(selected);
      };
      selectButton.addEventListener("click", choose);
      selectButton.draggable = true;
      selectButton.addEventListener("dragstart", (event) => {
        const selected = selectedVariant();
        if (!selected) return;
        event.dataTransfer.setData("text/equipmap-spec", selected.key);
        event.dataTransfer.effectAllowed = "copy";
      });
      ruInput.addEventListener("change", selectedVariant);
      ruInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          choose();
        }
      });
      selector.append(selectButton, ruInput, suffix);
      list.appendChild(selector);
    };

    if (key === "broadcast_equipment") {
      const grouped = new Map();
      for (const spec of specs) {
        if (!grouped.has(spec.name)) grouped.set(spec.name, []);
        grouped.get(spec.name).push(spec);
      }
      for (const [name, variants] of grouped) {
        addRuSelector(name, variants, `broadcast:${name}`);
      }
      catalog.appendChild(list);
      continue;
    }

    const rackSpecs = specs.filter((spec) => isRackKey(spec.key));
    const blankSpecs = specs.filter(
      (spec) => spec.key.startsWith("blank_panel_"),
    );
    let rackGroupAdded = false;
    let blankGroupAdded = false;
    for (const spec of specs) {
      if (isRackKey(spec.key)) {
        if (rackGroupAdded) continue;
        rackGroupAdded = true;
        addRuSelector("RACK", rackSpecs, "rack", 23, 46);
        continue;
      }
      if (spec.key.startsWith("blank_panel_")) {
        if (blankGroupAdded) continue;
        blankGroupAdded = true;
        addRuSelector("BLANK PANEL", blankSpecs, "blank_panel");
        continue;
      }
      addSpecButton(spec, list);
    }
    catalog.appendChild(list);
  }
}

function startPlacement(spec) {
  state.placeSpec = spec;
  clearSelection();
  board.classList.add("placing");
  placeBanner.textContent = `${spec.name} 배치: 캔버스를 클릭하세요. (Esc 취소)`;
  placeBanner.classList.remove("hidden");
  setStatus(`배치 준비: ${spec.name}`);
  renderCatalog();
}

function cancelPlacement() {
  if (!state.placeSpec) return false;
  state.placeSpec = null;
  board.classList.remove("placing");
  placeBanner.classList.add("hidden");
  renderCatalog();
  setStatus("준비됨");
  return true;
}

async function placeEquipment(spec, x, y) {
  const world = worldPoint(x, y);
  let width = Number(spec.width);
  let height = Number(spec.height);
  if (isRackKey(spec.key)) {
    width = Number(spec.width);
    height = Number(spec.height);
  } else if (spec.key.startsWith("blank_panel_")) {
    const ru = Math.max(1, Number(spec.ru) || 1);
    if (!nearestRack(world.x, world.y)) {
      const rackSpec = state.typeByKey.get("rack_46ru");
      const rackHeight = Number(rackSpec?.height || 780);
      const rackWidth = Number(rackSpec?.width || 213.114754);
      width = rackWidth * (485 / 600);
      height = rackHeight * 0.92 / 46 * ru;
    }
  }
  const placement = isRackKey(spec.key)
    ? snapRackPlacement(world.x, world.y, width, height)
    : snapRackMountedGeometry(
        spec,
        world.x,
        world.y,
        width,
        height,
      );
  try {
    const item = await api("/api/equipment", {
      method: "POST",
      body: JSON.stringify({
        spec_key: spec.key,
        equipment_name: spec.name,
        world_x: placement.x,
        world_y: placement.y,
        layout_width: placement.width,
        layout_height: placement.height,
      }),
    });
    state.items.push(item);
    cancelPlacement();
    setSelection(new Set([item.db_id]));
    setStatus(`${spec.name} 배치 완료`);
  } catch (error) {
    setStatus(error.message);
    alert(error.message);
  }
}

function nearestRack(worldX, worldY) {
  const racks = state.items.filter((item) => isRackKey(item.spec_key));
  if (!racks.length) return null;
  return racks.reduce((nearest, rack) => {
    const distance =
      (rack.world_x - worldX) ** 2 + (rack.world_y - worldY) ** 2;
    if (!nearest || distance < nearest.distance) {
      return { rack, distance };
    }
    return nearest;
  }, null).rack;
}

function snapRackPlacement(x, y, width, height, excludeId = null) {
  const racks = state.items.filter(
    (item) =>
      isRackKey(item.spec_key) &&
      item.db_id !== excludeId,
  );
  if (!racks.length) return { x, y, width, height, rack: null };

  const threshold = RACK_SNAP_DISTANCE_PX / state.zoom;
  let candidate = null;
  const candidateTop = y - height / 2;
  const candidateBottom = y + height / 2;
  for (const rack of racks) {
    const rackTop = rack.world_y - rack.layout_height / 2;
    const rackBottom = rack.world_y + rack.layout_height / 2;
    const verticalDistance = Math.abs(candidateBottom - rackBottom);
    const verticalOverlap = Math.max(
      0,
      Math.min(candidateBottom, rackBottom) -
        Math.max(candidateTop, rackTop),
    );
    if (
      verticalDistance > threshold &&
      verticalOverlap < Math.min(height, rack.layout_height) * 0.35
    ) {
      continue;
    }
    const candidateLeft = x - width / 2;
    const candidateRight = x + width / 2;
    const rackLeft = rack.world_x - rack.layout_width / 2;
    const rackRight = rack.world_x + rack.layout_width / 2;
    const rightGap = Math.abs(candidateLeft - rackRight);
    const leftGap = Math.abs(candidateRight - rackLeft);
    const gap = Math.min(rightGap, leftGap);
    if (gap > threshold) continue;
    const score = gap + Math.min(verticalDistance, threshold);
    if (!candidate || score < candidate.score) {
      candidate = {
        rack,
        score,
        placeRight: rightGap <= leftGap,
      };
    }
  }
  if (!candidate) return { x, y, width, height, rack: null };

  const anchor = candidate.rack;
  const anchorBottom = anchor.world_y + anchor.layout_height / 2;
  const row = racks.filter(
    (rack) =>
      Math.abs(
        rack.world_y + rack.layout_height / 2 - anchorBottom,
      ) < 0.01,
  );
  if (candidate.placeRight) {
    const rightEdge = Math.max(
      ...row.map((rack) => rack.world_x + rack.layout_width / 2),
    );
    return {
      x: rightEdge + width / 2,
      y: anchorBottom - height / 2,
      width,
      height,
      rack: anchor,
    };
  }
  const leftEdge = Math.min(
    ...row.map((rack) => rack.world_x - rack.layout_width / 2),
  );
  return {
    x: leftEdge - width / 2,
    y: anchorBottom - height / 2,
    width,
    height,
    rack: anchor,
  };
}

function snapRackItem(item) {
  const snapped = snapRackPlacement(
    item.world_x,
    item.world_y,
    item.layout_width,
    item.layout_height,
    item.db_id,
  );
  if (!snapped.rack) return false;
  const changed =
    Math.abs(item.world_x - snapped.x) > 0.001 ||
    Math.abs(item.world_y - snapped.y) > 0.001;
  item.world_x = snapped.x;
  item.world_y = snapped.y;
  return changed;
}

function isRackMountedSpec(spec) {
  return Boolean(
    spec &&
    !isRackKey(spec.key) &&
    Number(spec.ru) > 0,
  );
}

function rackMetrics(rack) {
  const ruCount = Math.max(1, Number(specFor(rack)?.ru) || 46);
  const structuralUnit = rack.layout_height / (ruCount + 4);
  const top =
    rack.world_y - rack.layout_height / 2 + structuralUnit * 2.25;
  const bottom =
    rack.world_y + rack.layout_height / 2 - structuralUnit * 1.75;
  return {
    top,
    bottom,
    ruCount,
    unitHeight: (bottom - top) / ruCount,
  };
}

function snapRackMountedGeometry(spec, x, y, width, height) {
  if (!isRackMountedSpec(spec)) return { x, y, width, height, rack: null };
  const rack = nearestRack(x, y);
  if (!rack) return { x, y, width, height, rack: null };

  const metrics = rackMetrics(rack);
  const ru = Math.max(
    1,
    Math.min(metrics.ruCount, Math.round(Number(spec.ru) || 1)),
  );
  let snappedWidth = width;
  if (
    spec.key.startsWith("blank_panel_") ||
    spec.key.startsWith("broadcast_") ||
    spec.key === "drawer_2ru" ||
    spec.key === "pdu_2ru"
  ) {
    snappedWidth = rack.layout_width * (485 / 600);
  }
  const snappedHeight = metrics.unitHeight * ru;
  const firstUnit = Math.max(
    0,
    Math.min(
      metrics.ruCount - ru,
      Math.round((y - metrics.top) / metrics.unitHeight - ru / 2),
    ),
  );
  return {
    x: rack.world_x,
    y: metrics.top + (firstUnit + ru / 2) * metrics.unitHeight,
    width: snappedWidth,
    height: snappedHeight,
    rack,
  };
}

function snapItemToRack(item) {
  const spec = specFor(item);
  const snapped = snapRackMountedGeometry(
    spec,
    item.world_x,
    item.world_y,
    item.layout_width,
    item.layout_height,
  );
  if (!snapped.rack) return false;
  const changed =
    Math.abs(item.world_x - snapped.x) > 0.001 ||
    Math.abs(item.world_y - snapped.y) > 0.001 ||
    Math.abs(item.layout_width - snapped.width) > 0.001 ||
    Math.abs(item.layout_height - snapped.height) > 0.001;
  item.world_x = snapped.x;
  item.world_y = snapped.y;
  item.layout_width = snapped.width;
  item.layout_height = snapped.height;
  return changed;
}

function normalizeRackSizes() {
  for (const rack of state.items) {
    if (!isRackKey(rack.spec_key)) continue;
    const spec = specFor(rack);
    if (!spec) continue;
    const width = Number(spec.width);
    const height = Number(spec.height);
    if (
      Math.abs(rack.layout_width - width) > 0.001 ||
      Math.abs(rack.layout_height - height) > 0.001
    ) {
      rack.layout_width = width;
      rack.layout_height = height;
      saveItem(rack);
    }
  }
}

function normalizeNearbyRackRows() {
  const racks = state.items
    .filter((item) => isRackKey(item.spec_key))
    .sort((a, b) => a.db_id - b.db_id);
  for (let index = 1; index < racks.length; index += 1) {
    const rack = racks[index];
    if (snapRackItem(rack)) saveItem(rack);
  }
}

function normalizeRackMountedItems() {
  for (const item of state.items) {
    if (!isRackMountedSpec(specFor(item))) continue;
    if (snapItemToRack(item)) {
      saveItem(item);
    }
  }
}

function setSelection(ids) {
  state.selected = ids;
  state.inspectorEditing = false;
  hideContextMenu();
  hideTooltip();
  renderInspector();
  draw();
  const items = selectedItems();
  if (!items.length) setStatus("준비됨");
  else if (items.length === 1) {
    setStatus(
      `선택: ${specFor(items[0])?.name || items[0].spec_key}` +
      (items[0].locked ? " — 위치 고정됨" : " — 드래그·방향키 이동"),
    );
  } else {
    setStatus(`선택: ${items.length}개 장비`);
  }
}

function clearSelection() {
  setSelection(new Set());
}

function renderInspector(editing = state.inspectorEditing) {
  const items = selectedItems();
  if (!items.length) {
    inspector.textContent = "캔버스에서 장비를 선택하면 정보가 표시됩니다.";
    return;
  }
  if (items.length > 1) {
    const locked = items.filter((item) => item.locked).length;
    const counts = new Map();
    for (const item of items) {
      const name = specFor(item)?.name || item.spec_key;
      counts.set(name, (counts.get(name) || 0) + 1);
    }
    inspector.innerHTML = `
      <div class="info-row"><span class="info-label">선택 장비</span><span class="info-value">${items.length}개</span></div>
      <div class="info-row"><span class="info-label">구성</span><span class="info-value">${[...counts].map(([name, count]) => `${escapeHtml(name)} × ${count}`).join("<br>")}</span></div>
      <div class="info-row"><span class="info-label">고정</span><span class="info-value">${locked}개</span></div>
      <div class="info-row"><span class="info-label">이동 가능</span><span class="info-value">${items.length - locked}개</span></div>
    `;
    return;
  }

  const item = items[0];
  if (
    item.spec_key.startsWith("blank_panel_") ||
    item.spec_key === "drawer_2ru"
  ) {
    inspector.innerHTML = "";
    return;
  }
  const editableRows = [
    ["장비이름", "equipment_name"],
    ["장비업체", "equipment_vendor"],
    ["장비모델", "equipment_model"],
    ["자산번호", "asset_number"],
    ["일련번호", "serial_number"],
  ];
  const detailHtml = editing
    ? editableRows.map(([label, key]) => `
        <label class="info-row">
          <span class="info-label">${label}</span>
          <input data-field="${key}" value="${escapeHtml(item[key])}">
        </label>
      `).join("")
    : editableRows.map(([label, key]) => `
        <div class="info-row">
          <span class="info-label">${label}</span>
          <span class="info-value">${escapeHtml(item[key] || "-")}</span>
        </div>
      `).join("");
  const photoUrl = item.photo_url
    ? `${item.photo_url}?v=${item._photoCacheBust || 0}`
    : "";
  const photoHtml = photoUrl
    ? `
      <img class="equipment-photo" src="${escapeHtml(photoUrl)}" alt="${escapeHtml(equipmentPhotoQuery(item) || "장비 이미지")}">
      ${item.photo_source_url
        ? `<a class="photo-source" href="${escapeHtml(item.photo_source_url)}" target="_blank" rel="noopener noreferrer">Wikimedia Commons 이미지 출처</a>`
        : ""}
    `
    : `<p class="photo-empty">${item.equipment_model
        ? "저장된 모델 이미지가 없습니다."
        : "장비 모델명을 입력하면 이미지를 검색할 수 있습니다."}</p>`;

  inspector.innerHTML = `
    <section class="info-section">
      <h2>장비 정보</h2>
      ${detailHtml}
      <div class="action-row">
        ${editing
          ? '<button id="save-details" class="primary">저장</button><button id="cancel-details">취소</button>'
          : '<button id="edit-details" class="primary">수정</button>'}
      </div>
    </section>
    <div class="info-divider"></div>
    <section class="info-section">
      <h2>읽기 전용 정보</h2>
      <div class="info-row"><span class="info-label">장비 ID</span><span class="info-value">${escapeHtml(item.equipment_id)}</span></div>
      <div class="info-row"><span class="info-label">장비 종류</span><span class="info-value">${escapeHtml(specFor(item)?.name || item.spec_key)}</span></div>
      <div class="info-row"><span class="info-label">좌표정보</span><span class="info-value">X ${item.world_x.toFixed(1)} / Y ${item.world_y.toFixed(1)}</span></div>
      <div class="info-row"><span class="info-label">위치 상태</span><span class="info-value">${item.locked ? "고정" : "이동 가능"}</span></div>
    </section>
    <div class="info-divider"></div>
    <section class="info-section equipment-photo-section">
      <h2>장비 이미지</h2>
      ${photoHtml}
      ${item._photoError ? `<p class="photo-error">${escapeHtml(item._photoError)}</p>` : ""}
      <div class="action-row photo-actions">
        <button id="search-photo" ${item.equipment_model ? "" : "disabled"}>모델 이미지 검색</button>
        <label class="upload-photo-button">
          수동 이미지 등록
          <input id="upload-photo" type="file" accept="image/jpeg,image/png,image/webp">
        </label>
      </div>
    </section>
  `;

  document.getElementById("edit-details")?.addEventListener("click", () => {
    state.inspectorEditing = true;
    renderInspector(true);
  });
  document.getElementById("cancel-details")?.addEventListener("click", () => {
    state.inspectorEditing = false;
    renderInspector(false);
  });
  document.getElementById("search-photo")?.addEventListener("click", () => {
    searchEquipmentPhoto(item);
  });
  document.getElementById("upload-photo")?.addEventListener("change", (event) => {
    const [file] = event.target.files;
    if (file) uploadEquipmentPhoto(item, file);
  });
  document.getElementById("save-details")?.addEventListener("click", async () => {
    const values = {};
    inspector.querySelectorAll("[data-field]").forEach((input) => {
      values[input.dataset.field] = input.value.trim();
    });
    try {
      const updated = await api(`/api/equipment/${item.db_id}`, {
        method: "PATCH",
        body: JSON.stringify(values),
      });
      Object.assign(item, updated);
      state.inspectorEditing = false;
      renderInspector(false);
      draw();
      setStatus(`${item.equipment_id} 장비 정보를 저장했습니다.`);
      if (
        item.equipment_model &&
        item.photo_query !== "manual" &&
        (!item.photo_url || item.photo_query !== equipmentPhotoQuery(item))
      ) {
        await searchEquipmentPhoto(item);
      }
    } catch (error) {
      alert(error.message);
    }
  });
}

async function uploadEquipmentPhoto(item, file) {
  item._photoError = "";
  setStatus(`'${file.name}' 이미지를 등록하는 중...`);
  const form = new FormData();
  form.append("photo", file);
  try {
    const response = await fetch(
      `/api/equipment/${item.db_id}/upload-image`,
      { method: "POST", body: form },
    );
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || `업로드 실패 (${response.status})`);
    }
    const updated = await response.json();
    Object.assign(item, updated);
    item._photoCacheBust = Date.now();
    renderInspector(false);
    setStatus(`${file.name} 이미지를 저장했습니다.`);
  } catch (error) {
    item._photoError = error.message;
    renderInspector(false);
    setStatus(`이미지 등록 실패: ${error.message}`);
  }
}

async function searchEquipmentPhoto(item) {
  if (!item.equipment_model) return;
  item._photoError = "";
  const query = equipmentPhotoQuery(item);
  setStatus(`'${query}' 모델 이미지를 검색하는 중...`);
  try {
    const updated = await api(
      `/api/equipment/${item.db_id}/search-image`,
      { method: "POST" },
    );
    Object.assign(item, updated);
    item._photoCacheBust = Date.now();
    renderInspector(false);
    setStatus(`${query} 이미지를 저장했습니다.`);
  } catch (error) {
    item._photoError = error.message;
    renderInspector(false);
    setStatus(`이미지 검색 실패: ${error.message}`);
  }
}

async function saveItem(item) {
  try {
    const updated = await api(`/api/equipment/${item.db_id}`, {
      method: "PATCH",
      body: JSON.stringify({
        world_x: item.world_x,
        world_y: item.world_y,
        layout_width: item.layout_width,
        layout_height: item.layout_height,
        locked: item.locked,
      }),
    });
    Object.assign(item, updated);
  } catch (error) {
    setStatus(`저장 오류: ${error.message}`);
  }
}

async function deleteSelected() {
  const items = selectedItems();
  if (!items.length) return;
  if (!confirm(`${items.length}개 장비를 삭제하시겠습니까?`)) return;
  try {
    await Promise.all(
      items.map((item) => api(`/api/equipment/${item.db_id}`, { method: "DELETE" })),
    );
    const ids = new Set(items.map((item) => item.db_id));
    pushUndo({ type: "delete", dbIds: [...ids] });
    state.items = state.items.filter((item) => !ids.has(item.db_id));
    clearSelection();
    setStatus(`${items.length}개 장비를 삭제했습니다.`);
  } catch (error) {
    alert(error.message);
  }
}

function copySelected() {
  const items = selectedItems();
  if (!items.length) return;
  state.clipboardIds = items.map((item) => item.db_id);
  setStatus(`${items.length}개 장비를 복사했습니다. Ctrl+V로 붙여넣으세요.`);
}

async function pasteEquipment() {
  if (!state.clipboardIds.length) {
    setStatus("먼저 복사할 장비를 선택하고 Ctrl+C를 누르세요.");
    return;
  }
  try {
    const offset = 24 / state.zoom;
    const pasted = await api("/api/equipment/clone", {
      method: "POST",
      body: JSON.stringify({
        db_ids: state.clipboardIds,
        offset_x: 0,
        offset_y: 0,
      }),
    });
    state.items.push(...pasted);
    const includesRack = pasted.some(
      (item) => isRackKey(item.spec_key),
    );
    for (const item of pasted) {
      item.world_x += offset;
      item.world_y += offset;
      const spec = specFor(item);
      if (isRackMountedSpec(spec) && !includesRack) {
        const rack = nearestRack(item.world_x, item.world_y);
        if (rack) {
          const minimumOffset =
            rackMetrics(rack).unitHeight * Math.max(1, Number(spec.ru) || 1);
          item.world_y += Math.max(0, minimumOffset - offset);
        }
      }
    }
    await Promise.all(
      pasted.map((item) => {
        if (isRackKey(item.spec_key)) snapRackItem(item);
        else snapItemToRack(item);
        return saveItem(item);
      }),
    );
    state.clipboardIds = pasted.map((item) => item.db_id);
    setSelection(new Set(state.clipboardIds));
    setStatus(
      `${pasted.length}개 장비를 새 ID로 붙여넣었습니다.`,
    );
  } catch (error) {
    setStatus(`붙여넣기 실패: ${error.message}`);
  }
}

async function undoLastAction() {
  const action = state.undoStack.pop();
  if (!action) {
    setStatus("되돌릴 이동 또는 삭제 작업이 없습니다.");
    return;
  }
  try {
    if (action.type === "move") {
      const byId = new Map(
        state.items.map((item) => [item.db_id, item]),
      );
      const restored = [];
      for (const change of action.changes) {
        const item = byId.get(change.db_id);
        if (!item) continue;
        Object.assign(item, change.before);
        restored.push(item);
      }
      await Promise.all(restored.map(saveItem));
      setSelection(new Set(restored.map((item) => item.db_id)));
      renderInspector();
      draw();
      setStatus(`${restored.length}개 장비의 이동을 취소했습니다.`);
      return;
    }
    if (action.type === "delete") {
      const restored = await api("/api/equipment/restore", {
        method: "POST",
        body: JSON.stringify({ db_ids: action.dbIds }),
      });
      state.items.push(...restored);
      setSelection(new Set(restored.map((item) => item.db_id)));
      setStatus(`${restored.length}개 장비의 삭제를 취소했습니다.`);
    }
  } catch (error) {
    state.undoStack.push(action);
    setStatus(`실행 취소 실패: ${error.message}`);
  }
}

function zoomAt(nextZoom, x = wrap.clientWidth / 2, y = wrap.clientHeight / 2) {
  const zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, nextZoom));
  const world = worldPoint(x, y);
  state.zoom = zoom;
  state.offsetX = x - world.x * zoom;
  state.offsetY = y - world.y * zoom;
  hideTooltip();
  draw();
}

function resetView() {
  state.zoom = 1;
  state.offsetX = 0;
  state.offsetY = 0;
  draw();
}

function finishMarquee() {
  if (!state.marquee) return;
  const { start, current, additive } = state.marquee;
  const left = Math.min(start.x, current.x);
  const right = Math.max(start.x, current.x);
  const top = Math.min(start.y, current.y);
  const bottom = Math.max(start.y, current.y);
  const crossing = current.x < start.x;
  const ids = new Set(additive);
  for (const item of state.items) {
    const box = itemBox(item);
    const contained =
      box.x0 >= left && box.x1 <= right && box.y0 >= top && box.y1 <= bottom;
    const intersects =
      box.x1 >= left && box.x0 <= right && box.y1 >= top && box.y0 <= bottom;
    if (crossing ? intersects : contained) ids.add(item.db_id);
  }
  state.marquee = null;
  setSelection(ids);
}

function showTooltip(item, x, y) {
  if (
    item.spec_key.startsWith("blank_panel_") ||
    item.spec_key === "drawer_2ru"
  ) {
    hideTooltip();
    return;
  }
  const spec = specFor(item);
  tooltip.innerHTML = `
    <strong>${escapeHtml(item.equipment_name || spec?.name || item.spec_key)}</strong><br>
    ID: ${escapeHtml(item.equipment_id)}<br>
    업체: ${escapeHtml(item.equipment_vendor || "-")}<br>
    모델: ${escapeHtml(item.equipment_model || "-")}<br>
    좌표: X ${item.world_x.toFixed(1)} / Y ${item.world_y.toFixed(1)}<br>
    상태: ${item.locked ? "고정" : "이동 가능"}
  `;
  tooltip.style.left = `${Math.min(x + 14, wrap.clientWidth - 245)}px`;
  tooltip.style.top = `${Math.min(y + 14, wrap.clientHeight - 125)}px`;
  tooltip.classList.remove("hidden");
}

function hideTooltip() {
  tooltip.classList.add("hidden");
}

function showContextMenu(x, y) {
  const items = selectedItems();
  if (!items.length) return;
  const lockButton = contextMenu.querySelector('[data-action="lock"]');
  lockButton.textContent = items.every((item) => item.locked) ? "고정 해제" : "고정";
  contextMenu.style.left = `${Math.min(x, wrap.clientWidth - 140)}px`;
  contextMenu.style.top = `${Math.min(y, wrap.clientHeight - 130)}px`;
  contextMenu.classList.remove("hidden");
}

function hideContextMenu() {
  contextMenu.classList.add("hidden");
}

board.addEventListener("wheel", (event) => {
  event.preventDefault();
  const point = screenPoint(event);
  zoomAt(
    event.deltaY < 0 ? state.zoom * ZOOM_STEP : state.zoom / ZOOM_STEP,
    point.x,
    point.y,
  );
}, { passive: false });

board.addEventListener("mousedown", (event) => {
  board.focus();
  hideContextMenu();
  hideTooltip();
  const point = screenPoint(event);

  if (event.button === 1) {
    event.preventDefault();
    state.pan = { last: point };
    board.classList.add("panning");
    return;
  }
  if (event.button !== 0) return;
  if (state.placeSpec) {
    placeEquipment(state.placeSpec, point.x, point.y);
    return;
  }

  const hit = hitTest(point.x, point.y);
  if (hit) {
    if (event.ctrlKey) {
      const ids = new Set(state.selected);
      if (ids.has(hit.db_id)) ids.delete(hit.db_id);
      else ids.add(hit.db_id);
      setSelection(ids);
    } else if (!state.selected.has(hit.db_id)) {
      setSelection(new Set([hit.db_id]));
    }
    const movable = selectedItems().filter((item) => !item.locked);
    if (movable.length) {
      state.drag = {
        last: point,
        items: movable,
        before: movable.map(geometrySnapshot),
        changed: false,
      };
    }
    return;
  }

  state.marquee = {
    start: point,
    current: point,
    additive: event.ctrlKey ? new Set(state.selected) : new Set(),
  };
  if (!event.ctrlKey) {
    state.selected = new Set();
    renderInspector();
  }
  draw();
});

window.addEventListener("mousemove", (event) => {
  const point = screenPoint(event);
  if (state.pan) {
    state.offsetX += point.x - state.pan.last.x;
    state.offsetY += point.y - state.pan.last.y;
    state.pan.last = point;
    draw();
    return;
  }
  if (state.drag) {
    const dx = (point.x - state.drag.last.x) / state.zoom;
    const dy = (point.y - state.drag.last.y) / state.zoom;
    if (dx || dy) {
      for (const item of state.drag.items) {
        item.world_x += dx;
        item.world_y += dy;
      }
      state.drag.changed = true;
      state.drag.last = point;
      renderInspector();
      draw();
    }
    return;
  }
  if (state.marquee) {
    state.marquee.current = point;
    draw();
    return;
  }
  if (
    point.x < 0 || point.y < 0 ||
    point.x > wrap.clientWidth || point.y > wrap.clientHeight
  ) {
    hideTooltip();
    return;
  }
  const hit = hitTest(point.x, point.y);
  if (hit) showTooltip(hit, point.x, point.y);
  else hideTooltip();
});

window.addEventListener("mouseup", () => {
  if (state.pan) {
    state.pan = null;
    board.classList.remove("panning");
  }
  if (state.drag) {
    if (state.drag.changed) {
      for (const item of state.drag.items) {
        if (isRackKey(item.spec_key)) snapRackItem(item);
        else snapItemToRack(item);
        saveItem(item);
      }
      recordMoveUndo(state.drag.before, state.drag.items);
      draw();
    }
    state.drag = null;
    renderInspector();
  }
  if (state.marquee) finishMarquee();
});

board.addEventListener("contextmenu", (event) => {
  event.preventDefault();
  const point = screenPoint(event);
  const hit = hitTest(point.x, point.y);
  if (!hit) {
    hideContextMenu();
    return;
  }
  if (!state.selected.has(hit.db_id)) setSelection(new Set([hit.db_id]));
  showContextMenu(point.x, point.y);
});

board.addEventListener("dragover", (event) => {
  if (event.dataTransfer.types.includes("text/equipmap-spec")) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }
});

board.addEventListener("drop", (event) => {
  event.preventDefault();
  const key = event.dataTransfer.getData("text/equipmap-spec");
  const spec = state.typeByKey.get(key);
  if (spec) {
    const point = screenPoint(event);
    placeEquipment(spec, point.x, point.y);
  }
});

contextMenu.addEventListener("click", async (event) => {
  const action = event.target.dataset.action;
  if (!action) return;
  hideContextMenu();
  if (action === "delete") {
    await deleteSelected();
  } else if (action === "lock") {
    const items = selectedItems();
    const locked = !items.every((item) => item.locked);
    for (const item of items) {
      item.locked = locked;
      saveItem(item);
    }
    setSelection(new Set(state.selected));
  } else if (action === "move") {
    board.focus();
    setStatus("방향키로 선택 장비를 이동할 수 있습니다.");
  }
});

document.addEventListener("mousedown", (event) => {
  if (!contextMenu.contains(event.target)) hideContextMenu();
});

document.addEventListener("keydown", (event) => {
  if (event.target.matches("input")) return;
  if (event.ctrlKey && event.key.toLowerCase() === "z") {
    event.preventDefault();
    undoLastAction();
    return;
  }
  if (event.ctrlKey && event.key.toLowerCase() === "c") {
    if (state.selected.size) {
      event.preventDefault();
      copySelected();
    }
    return;
  }
  if (event.ctrlKey && event.key.toLowerCase() === "v") {
    event.preventDefault();
    pasteEquipment();
    return;
  }
  if (event.key === "Escape") {
    if (!cancelPlacement()) hideContextMenu();
    return;
  }
  if (event.key === "Delete") {
    event.preventDefault();
    deleteSelected();
    return;
  }
  const directions = {
    ArrowLeft: [-1, 0],
    ArrowRight: [1, 0],
    ArrowUp: [0, -1],
    ArrowDown: [0, 1],
  };
  if (!directions[event.key]) return;
  const items = selectedItems().filter((item) => !item.locked);
  if (!items.length) return;
  event.preventDefault();
  const before = items.map(geometrySnapshot);
  const [dx, dy] = directions[event.key];
  for (const item of items) {
    const spec = specFor(item);
    if (isRackMountedSpec(spec)) {
      const rack = nearestRack(item.world_x, item.world_y);
      if (rack && dy) {
        item.world_y += dy * rackMetrics(rack).unitHeight;
      }
      if (snapItemToRack(item)) saveItem(item);
    } else {
      item.world_x += dx * 2 / state.zoom;
      item.world_y += dy * 2 / state.zoom;
      saveItem(item);
    }
  }
  recordMoveUndo(before, items);
  renderInspector();
  draw();
});

document.getElementById("zoom-in").addEventListener("click", () => {
  zoomAt(state.zoom * ZOOM_STEP);
});
document.getElementById("zoom-out").addEventListener("click", () => {
  zoomAt(state.zoom / ZOOM_STEP);
});
zoomEl.addEventListener("click", resetView);

async function initialize() {
  try {
    const [types, items] = await Promise.all([
      api("/api/equipment-types"),
      api("/api/equipment"),
    ]);
    state.types = types;
    state.typeByKey = new Map(types.map((spec) => [spec.key, spec]));
    state.items = items.filter((item) => state.typeByKey.has(item.spec_key));
    normalizeRackSizes();
    normalizeNearbyRackRows();
    normalizeRackMountedItems();
    state.expandedCategory = types[0]?.category_key || null;
    renderCatalog();
    renderInspector();
    resizeCanvas();
    setStatus("준비됨 — 마우스 휠 줌 / 가운데 버튼 이동");
  } catch (error) {
    setStatus(`초기화 오류: ${error.message}`);
  }
}

new ResizeObserver(resizeCanvas).observe(wrap);
initialize();
