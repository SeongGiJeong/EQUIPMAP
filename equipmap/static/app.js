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
const portMenu = document.getElementById("port-menu");
const cableModeButton = document.getElementById("cable-mode");
const editCatalogButton = document.getElementById("edit-catalog");
const catalogEditorDialog = document.getElementById("catalog-editor-dialog");
const catalogEditorList = document.getElementById("catalog-editor-list");
const catalogEditorError = document.getElementById("catalog-editor-error");
const addEquipmentTypeButton = document.getElementById("add-equipment-type");
const closeCatalogEditorButton = document.getElementById(
  "close-catalog-editor",
);
const equipmentTypeDialog = document.getElementById("equipment-type-dialog");
const equipmentTypeForm = document.getElementById("equipment-type-form");
const equipmentTypeDialogTitle = document.getElementById(
  "equipment-type-dialog-title",
);
const newTypeCategory = document.getElementById("new-type-category");
const equipmentCategoryOptions = document.getElementById(
  "equipment-category-options",
);
const newTypeName = document.getElementById("new-type-name");
const newTypePrefix = document.getElementById("new-type-prefix");
const newTypePrefixField = document.getElementById("new-type-prefix-field");
const newTypePrefixHelp = document.getElementById("new-type-prefix-help");
const newTypeRu = document.getElementById("new-type-ru");
const newTypeRuField = document.getElementById("new-type-ru-field");
const newTypeRuHelp = document.getElementById("new-type-ru-help");
const newTypeHalf = document.getElementById("new-type-half");
const newTypeHalfField = document.getElementById("new-type-half-field");
const equipmentTypeError = document.getElementById("equipment-type-error");
const saveEquipmentTypeButton = document.getElementById("save-equipment-type");

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
  clipboardIds: [],
  undoStack: [],
  drag: null,
  pan: null,
  marquee: null,
  inspectorEditing: false,
  connectionEditing: false,
  expandedInterfaceType: null,
  connectionNamesByType: {},
  linkDraft: null,
  typeEditor: null,
  cableMode: false,
  links: [],
  portMenuItemId: null,
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

function instanceRu(item, fallbackSpec = null) {
  const spec = fallbackSpec || specFor(item);
  if (!spec) return 1;
  const typeRu = Math.max(1, Number(spec.ru) || 1);
  const layoutHeight = Number(item.layout_height) || 0;
  if (layoutHeight <= 0) return typeRu;
  if (isRackKey(item.spec_key || spec.key)) {
    const unit = Number(spec.height) / (typeRu + 4);
    if (unit > 0) {
      return Math.max(1, Math.round(layoutHeight / unit - 4));
    }
    return typeRu;
  }
  const unit = Number(spec.height) / typeRu;
  if (unit > 0) {
    return Math.max(1, Math.round(layoutHeight / unit));
  }
  return typeRu;
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

  const ruCount = Math.max(1, instanceRu(item));
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
  const ru = Math.max(1, instanceRu(item));
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
  const ru = Math.max(1, instanceRu(item));
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
    else drawBroadcastDevice(item, box);
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

function edgeAnchor(box, targetX, targetY) {
  const cx = (box.x0 + box.x1) / 2;
  const cy = (box.y0 + box.y1) / 2;
  const dx = targetX - cx;
  const dy = targetY - cy;
  if (dx === 0 && dy === 0) return { x: cx, y: cy };
  const hw = (box.x1 - box.x0) / 2;
  const hh = (box.y1 - box.y0) / 2;
  const scale = 1 / Math.max(Math.abs(dx) / hw || 0, Math.abs(dy) / hh || 0);
  return { x: cx + dx * scale, y: cy + dy * scale };
}

function drawCables() {
  if (!state.links.length) return;
  const byId = new Map(state.items.map((item) => [item.db_id, item]));
  const pairOffset = new Map();
  for (const link of state.links) {
    const key = [link.a_equipment_db_id, link.b_equipment_db_id]
      .sort((a, b) => a - b)
      .join("-");
    pairOffset.set(key, (pairOffset.get(key) || 0) + 1);
  }
  const pairSeen = new Map();
  const gap = Math.max(5, 8 * state.zoom);
  ctx.save();
  ctx.lineWidth = Math.max(1.4, state.zoom * 1.6);
  ctx.lineCap = "round";
  for (const link of state.links) {
    const a = byId.get(link.a_equipment_db_id);
    const b = byId.get(link.b_equipment_db_id);
    if (!a || !b) continue;
    const boxA = itemBox(a);
    const boxB = itemBox(b);
    const ca = { x: (boxA.x0 + boxA.x1) / 2, y: (boxA.y0 + boxA.y1) / 2 };
    const cb = { x: (boxB.x0 + boxB.x1) / 2, y: (boxB.y0 + boxB.y1) / 2 };
    const key = [link.a_equipment_db_id, link.b_equipment_db_id]
      .sort((n, m) => n - m)
      .join("-");
    const total = pairOffset.get(key) || 1;
    const seen = pairSeen.get(key) || 0;
    pairSeen.set(key, seen + 1);
    let ox = 0;
    let oy = 0;
    if (total > 1) {
      const len = Math.hypot(cb.x - ca.x, cb.y - ca.y) || 1;
      const shift = (seen - (total - 1) / 2) * gap;
      ox = (-(cb.y - ca.y) / len) * shift;
      oy = ((cb.x - ca.x) / len) * shift;
    }
    const pa = edgeAnchor(boxA, cb.x + ox, cb.y + oy);
    const pb = edgeAnchor(boxB, ca.x + ox, ca.y + oy);
    pa.x += ox; pa.y += oy;
    pb.x += ox; pb.y += oy;
    ctx.strokeStyle = "#f59e0b";
    ctx.beginPath();
    ctx.moveTo(pa.x, pa.y);
    ctx.lineTo(pb.x, pb.y);
    ctx.stroke();
    const dot = Math.max(2, state.zoom * 2.2);
    ctx.fillStyle = "#d97706";
    for (const point of [pa, pb]) {
      ctx.beginPath();
      ctx.arc(point.x, point.y, dot, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.restore();
}

function draw() {
  drawGrid();
  drawEquipment();
  drawCables();
  drawSelection();
  drawMarquee();
  zoomEl.textContent = `${Math.round(state.zoom * 100)}%`;
}

function categoryOrderValue(key) {
  const categoryOrder = {
    rack: 0,
    broadcast_equipment: 1,
    custom_equipment: 2,
  };
  return categoryOrder[key] ?? 999;
}

function sortedCategories() {
  const categories = new Map();
  for (const spec of state.types) {
    if (!categories.has(spec.category_key)) {
      categories.set(spec.category_key, []);
    }
    categories.get(spec.category_key).push(spec);
  }
  return [...categories.entries()].sort(
    ([left], [right]) => categoryOrderValue(left) - categoryOrderValue(right),
  );
}

function groupedVariants(specs) {
  const grouped = new Map();
  for (const spec of specs) {
    const groupKey = isRackKey(spec.key)
      ? "rack"
      : spec.key.startsWith("blank_panel_")
        ? "blank_panel"
        : `${spec.id_prefix || spec.name}`;
    if (!grouped.has(groupKey)) grouped.set(groupKey, []);
    grouped.get(groupKey).push(spec);
  }
  return [...grouped.values()].map((variants) =>
    variants.sort((left, right) => Number(left.ru) - Number(right.ru)),
  );
}

function renderCatalog() {
  catalog.innerHTML = "";
  for (const [key, specs] of sortedCategories()) {
    const first = specs[0];
    const categoryButton = document.createElement("button");
    categoryButton.className = "category-card";
    if (state.expandedCategory === key) categoryButton.classList.add("active");
    categoryButton.innerHTML = `
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

    for (const variants of groupedVariants(specs)) {
      const spec = isRackKey(variants[0].key)
        ? variants[variants.length - 1]
        : variants[0];
      const button = document.createElement("button");
      button.className = "model-button";
      if (state.placeSpec?.key === spec.key) button.classList.add("selected");
      button.textContent = spec.name;
      button.draggable = true;
      button.addEventListener("click", () => startPlacement(spec));
      button.addEventListener("dragstart", (event) => {
        event.dataTransfer.setData("text/equipmap-spec", spec.key);
        event.dataTransfer.effectAllowed = "copy";
      });
      list.appendChild(button);
    }
    catalog.appendChild(list);
  }
}

function suggestedIdPrefix(name) {
  return String(name || "")
    .normalize("NFKD")
    .toUpperCase()
    .replaceAll(/[^A-Z0-9]+/g, "_")
    .replaceAll(/^_+|_+$/g, "")
    .replaceAll(/^[^A-Z]+/g, "")
    .slice(0, 20);
}

function replaceEquipmentTypes(records) {
  const updates = new Map(records.map((record) => [record.key, record]));
  state.types = state.types.map((spec) => updates.get(spec.key) || spec);
  for (const record of records) state.typeByKey.set(record.key, record);
  if (state.placeSpec && updates.has(state.placeSpec.key)) {
    state.placeSpec = updates.get(state.placeSpec.key);
  }
}

function removeEquipmentTypes(keys) {
  const removed = new Set(keys);
  state.types = state.types.filter((spec) => !removed.has(spec.key));
  for (const key of removed) state.typeByKey.delete(key);
  if (state.placeSpec && removed.has(state.placeSpec.key)) {
    cancelPlacement();
  }
}

function refreshCategoryOptions() {
  const categoryNames = [
    ...new Set(state.types.map((spec) => spec.category_name)),
  ];
  equipmentCategoryOptions.innerHTML = categoryNames
    .map((name) => `<option value="${escapeHtml(name)}"></option>`)
    .join("");
}

function openCatalogEditor() {
  catalogEditorError.textContent = "";
  renderCatalogEditor();
  catalogEditorDialog.showModal();
}

function renderCatalogEditor() {
  catalogEditorList.innerHTML = "";
  for (const [categoryKey, specs] of sortedCategories()) {
    const section = document.createElement("section");
    section.className = "catalog-editor-section";
    const header = document.createElement("div");
    header.className = "catalog-editor-category";
    const title = document.createElement("strong");
    title.textContent = specs[0].category_name;
    const renameButton = document.createElement("button");
    renameButton.type = "button";
    renameButton.textContent = "대그룹 이름";
    renameButton.addEventListener("click", () => {
      editCategoryName(categoryKey, specs[0]);
    });
    header.append(title, renameButton);
    section.appendChild(header);

    for (const variants of groupedVariants(specs)) {
      const row = document.createElement("div");
      row.className = "catalog-editor-row";
      const info = document.createElement("div");
      info.className = "catalog-editor-info";
      const name = document.createElement("strong");
      name.textContent = variants[0].name;
      const meta = document.createElement("span");
      const preferred = isRackKey(variants[0].key)
        ? variants[variants.length - 1]
        : variants[0];
      meta.textContent = `${preferred.ru} RU${
        preferred.is_half ? " · Half" : ""
      } · ${preferred.id_prefix}`;
      info.append(name, meta);

      const actions = document.createElement("div");
      actions.className = "catalog-editor-actions";
      const editButton = document.createElement("button");
      editButton.type = "button";
      editButton.textContent = "수정";
      editButton.addEventListener("click", () => {
        openEquipmentTypeDialog(variants);
      });
      const deleteButton = document.createElement("button");
      deleteButton.type = "button";
      deleteButton.className = "danger";
      deleteButton.textContent = "삭제";
      deleteButton.addEventListener("click", () => {
        deleteEquipmentGroup(variants);
      });
      actions.append(editButton, deleteButton);
      row.append(info, actions);
      section.appendChild(row);
    }
    catalogEditorList.appendChild(section);
  }
  if (!state.types.length) {
    catalogEditorList.innerHTML =
      '<p class="field-help">등록된 장비가 없습니다. 장비를 추가해주세요.</p>';
  }
}

function openEquipmentTypeDialog(variants = null) {
  equipmentTypeForm.reset();
  equipmentTypeError.textContent = "";
  refreshCategoryOptions();
  state.typeEditor = variants
    ? { specKeys: variants.map((variant) => variant.key) }
    : null;

  if (variants) {
    const first = variants[0];
    const preferred = isRackKey(first.key)
      ? variants[variants.length - 1]
      : first;
    equipmentTypeDialogTitle.textContent = "장비 종류 수정";
    saveEquipmentTypeButton.textContent = "저장";
    newTypeCategory.value = first.category_name;
    newTypeCategory.disabled = false;
    newTypeName.value = first.name;
    newTypePrefixField.hidden = true;
    newTypePrefixHelp.hidden = true;
    newTypePrefix.required = false;
    newTypeRuField.hidden = false;
    newTypeRu.disabled = false;
    newTypeRuHelp.classList.add("hidden");
    newTypeRu.value = String(preferred.ru);
    newTypeRu.min = "1";
    newTypeRu.max = "46";
    const canBeHalf = !isRackKey(first.key);
    newTypeHalfField.hidden = !canBeHalf;
    newTypeHalf.disabled = !canBeHalf;
    newTypeHalf.checked = Boolean(preferred.is_half);
  } else {
    equipmentTypeDialogTitle.textContent = "장비 종류 추가";
    saveEquipmentTypeButton.textContent = "추가";
    newTypeCategory.disabled = false;
    newTypePrefixField.hidden = false;
    newTypePrefixHelp.hidden = false;
    newTypePrefix.required = true;
    newTypePrefix.dataset.manual = "false";
    newTypeRuField.hidden = false;
    newTypeRu.disabled = false;
    newTypeRuHelp.classList.add("hidden");
    newTypeRu.min = "1";
    newTypeRu.max = "46";
    newTypeHalfField.hidden = false;
    newTypeHalf.disabled = false;
    newTypeHalf.checked = false;
  }
  equipmentTypeDialog.showModal();
  (variants ? newTypeName : newTypeCategory).focus();
}

async function saveEquipmentType(event) {
  event.preventDefault();
  equipmentTypeError.textContent = "";
  saveEquipmentTypeButton.disabled = true;
  try {
    if (state.typeEditor) {
      const oldKeys = state.typeEditor.specKeys;
      const payload = {
        spec_keys: oldKeys,
        name: newTypeName.value.trim(),
        category_name: newTypeCategory.value.trim(),
        ru: Number(newTypeRu.value),
        is_half: Boolean(newTypeHalf.checked),
      };
      const records = await api("/api/equipment-types/group", {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      const keptKeys = new Set(records.map((record) => record.key));
      const previousPlaceKey = state.placeSpec?.key || null;
      removeEquipmentTypes(oldKeys.filter((key) => !keptKeys.has(key)));
      replaceEquipmentTypes(records);
      const survivor =
        records.find((record) => record.key === previousPlaceKey) ||
        records[records.length - 1] ||
        records[0];
      if (survivor && previousPlaceKey && oldKeys.includes(previousPlaceKey)) {
        state.placeSpec = survivor;
      }
      // 배치된 장비의 이름/크기는 목록 수정과 무관하게 유지한다.
      state.expandedCategory =
        survivor?.category_key || state.expandedCategory;
      setStatus(`${survivor?.name || "장비"} 종류를 수정했습니다.`);
    } else {
      const spec = await api("/api/equipment-types", {
        method: "POST",
        body: JSON.stringify({
          category_name: newTypeCategory.value.trim(),
          name: newTypeName.value.trim(),
          id_prefix: newTypePrefix.value.trim().toUpperCase(),
          ru: Number(newTypeRu.value),
          is_half: Boolean(newTypeHalf.checked),
        }),
      });
      state.types.push(spec);
      state.typeByKey.set(spec.key, spec);
      state.expandedCategory = spec.category_key;
      setStatus(`${spec.name} 장비 종류가 추가되었습니다.`);
    }
    equipmentTypeDialog.close();
    renderCatalog();
    if (catalogEditorDialog.open) renderCatalogEditor();
    draw();
  } catch (error) {
    equipmentTypeError.textContent = error.message;
  } finally {
    saveEquipmentTypeButton.disabled = false;
  }
}

async function editCategoryName(categoryKey, firstSpec) {
  const categoryName = window.prompt(
    "대그룹 이름을 입력하세요.",
    firstSpec.category_name,
  );
  if (categoryName === null || !categoryName.trim()) return;
  catalogEditorError.textContent = "";
  try {
    const records = await api("/api/equipment-types/category", {
      method: "PATCH",
      body: JSON.stringify({
        category_key: categoryKey,
        category_name: categoryName.trim(),
      }),
    });
    replaceEquipmentTypes(records);
    renderCatalog();
    if (catalogEditorDialog.open) renderCatalogEditor();
    setStatus(`${categoryName.trim()} 대그룹 이름을 저장했습니다.`);
  } catch (error) {
    if (catalogEditorDialog.open) {
      catalogEditorError.textContent = error.message;
    } else {
      alert(error.message);
    }
  }
}

async function deleteEquipmentGroup(variants) {
  const name = variants[0].name;
  if (!window.confirm(`"${name}" 장비 종류를 목록에서 삭제할까요?`)) return;
  catalogEditorError.textContent = "";
  try {
    const result = await api("/api/equipment-types/group", {
      method: "DELETE",
      body: JSON.stringify({
        spec_keys: variants.map((variant) => variant.key),
      }),
    });
    removeEquipmentTypes(result.deleted || []);
    renderCatalog();
    renderCatalogEditor();
    setStatus(`${name} 장비 종류를 삭제했습니다.`);
  } catch (error) {
    catalogEditorError.textContent = error.message;
  }
}

function startPlacement(spec) {
  state.linkDraft = null;
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
  if (state.linkDraft) {
    updateLinkDraftBanner();
  } else {
    placeBanner.classList.add("hidden");
  }
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
  const ruCount = Math.max(1, instanceRu(rack));
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
  const inferredRu = Math.max(
    1,
    Math.round(Number(height) / Math.max(metrics.unitHeight, 0.0001)),
  );
  const ru = Math.max(
    1,
    Math.min(
      metrics.ruCount,
      Number(height) > 0 ? inferredRu : Math.round(Number(spec.ru) || 1),
    ),
  );
  const fullMountWidth = rack.layout_width * (485 / 600);
  const treatAsHalf =
    Boolean(spec.is_half) ||
    (Number(width) > 0 && Number(width) < fullMountWidth * 0.7);
  const snappedWidth = treatAsHalf ? fullMountWidth / 2 : fullMountWidth;
  const snappedHeight = metrics.unitHeight * ru;
  const firstUnit = Math.max(
    0,
    Math.min(
      metrics.ruCount - ru,
      Math.round((y - metrics.top) / metrics.unitHeight - ru / 2),
    ),
  );
  const mountLeft = rack.world_x - fullMountWidth / 2;
  const mountRight = rack.world_x + fullMountWidth / 2;
  let snappedX = rack.world_x;
  if (treatAsHalf) {
    const leftX = mountLeft + snappedWidth / 2;
    const centerX = rack.world_x;
    const rightX = mountRight - snappedWidth / 2;
    const candidates = [
      { x: leftX, distance: Math.abs(x - leftX) },
      { x: centerX, distance: Math.abs(x - centerX) },
      { x: rightX, distance: Math.abs(x - rightX) },
    ];
    candidates.sort((left, right) => left.distance - right.distance);
    snappedX = candidates[0].x;
  }
  return {
    x: snappedX,
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
  // 배치된 장비 크기는 인스턴스별로 유지한다. 목록 RU 변경과 동기화하지 않음.
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
  state.connectionEditing = false;
  state.expandedInterfaceType = null;
  state.connectionNamesByType = {};
  hideContextMenu();
  hideTooltip();
  renderInspector();
  draw();
  const items = selectedItems();
  if (state.linkDraft) {
    updateLinkDraftBanner();
    if (items.length === 1 && items[0].db_id !== state.linkDraft.db_id) {
      setStatus(
        `연결 대상: ${items[0].equipment_id} — 연결할 포트를 클릭하세요.`,
      );
    } else if (items.length === 1) {
      setStatus("같은 장비입니다. 다른 장비를 선택한 뒤 포트를 클릭하세요.");
    } else {
      setStatus("연결 대상 장비를 선택한 뒤 포트를 클릭하세요.");
    }
    return;
  }
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

function interfaceTotals(spec) {
  const interfaces = Array.isArray(spec?.interfaces) ? [...spec.interfaces] : [];
  const totals = new Map();
  const order = [];
  const sorted = interfaces.sort(
    (a, b) => (a.sort_order - b.sort_order) || (a.interface_id - b.interface_id),
  );
  for (const item of sorted) {
    const type = item.interface_type || "기타";
    if (!totals.has(type)) {
      totals.set(type, 0);
      order.push(type);
    }
    totals.set(type, totals.get(type) + (Number(item.port_count) || 0));
  }
  return order.map((type) => ({
    interface_type: type,
    port_count: totals.get(type),
  }));
}

function portLinkFor(item, interfaceType, portIndex) {
  const links = item?._portLinks || [];
  return links.find((link) => (
    (
      link.a_equipment_db_id === item.db_id
      && link.a_interface_type === interfaceType
      && link.a_port_index === portIndex
    ) || (
      link.b_equipment_db_id === item.db_id
      && link.b_interface_type === interfaceType
      && link.b_port_index === portIndex
    )
  )) || null;
}

function portPeerSummary(link, equipmentDbId) {
  if (!link) return null;
  const isA = link.a_equipment_db_id === equipmentDbId;
  return {
    linkId: link.link_id,
    equipmentDbId: isA ? link.b_equipment_db_id : link.a_equipment_db_id,
    equipmentId: isA ? link.b_equipment_id : link.a_equipment_id,
    equipmentName: isA ? link.b_equipment_name : link.a_equipment_name,
    interfaceType: isA ? link.b_interface_type : link.a_interface_type,
    portIndex: isA ? link.b_port_index : link.a_port_index,
    connectionName: isA ? link.b_connection_name : link.a_connection_name,
  };
}

function formatPortLabel(interfaceType, portIndex, connectionName = "") {
  const base = `${interfaceType}${portIndex}`;
  return connectionName ? `${base} ${connectionName}` : base;
}

function isLinkDraftPort(equipmentDbId, interfaceType, portIndex) {
  const draft = state.linkDraft;
  return Boolean(
    draft
    && draft.db_id === equipmentDbId
    && draft.interface_type === interfaceType
    && draft.port_index === portIndex,
  );
}

function updateLinkDraftBanner() {
  if (!state.linkDraft) {
    if (state.placeSpec) {
      placeBanner.textContent = (
        `${state.placeSpec.name} 배치: 캔버스를 클릭하세요. (Esc 취소)`
      );
      placeBanner.classList.remove("hidden");
    } else {
      placeBanner.classList.add("hidden");
      placeBanner.textContent = "";
    }
    return;
  }
  if (state.placeSpec) {
    state.placeSpec = null;
    board.classList.remove("placing");
    renderCatalog();
  }
  const draft = state.linkDraft;
  placeBanner.classList.remove("hidden");
  placeBanner.innerHTML = `
    연결 중: ${escapeHtml(draft.equipment_id)} /
    ${escapeHtml(formatPortLabel(draft.interface_type, draft.port_index, draft.connection_name))}
    — 대상 장비를 선택한 뒤 포트를 클릭하세요
    <button type="button" id="cancel-link-draft" class="link-draft-cancel">취소</button>
  `;
  document.getElementById("cancel-link-draft")?.addEventListener("click", () => {
    clearLinkDraft();
  });
}

function clearLinkDraft() {
  state.linkDraft = null;
  updateLinkDraftBanner();
  const item = selectedItems()[0];
  if (item) refreshConnectionPanel(item);
  else setStatus("준비됨");
}

function renderInterfaceGroupsHtml(item, spec) {
  const interfaces = interfaceTotals(spec);
  if (!interfaces.length) {
    return '<p class="connection-empty">등록된 인터페이스가 없습니다.</p>';
  }
  return `
    <ul class="interface-list">
      ${interfaces.map((iface) => {
        const expanded = state.expandedInterfaceType === iface.interface_type;
        const names = state.connectionNamesByType[iface.interface_type] || [];
        return `
          <li class="interface-item${expanded ? " is-expanded" : ""}"
              data-interface-type="${escapeHtml(iface.interface_type)}">
            <button type="button" class="interface-type-toggle"
                    data-interface-type="${escapeHtml(iface.interface_type)}"
                    aria-expanded="${expanded ? "true" : "false"}">
              ${escapeHtml(iface.interface_type)}
            </button>
            <span class="interface-count">${iface.port_count}</span>
            ${expanded ? `
              <div class="interface-ports">
                ${Array.from({ length: iface.port_count }, (_, index) => {
                  const portIndex = index + 1;
                  const name = names[index] || "";
                  const peer = portPeerSummary(
                    portLinkFor(item, iface.interface_type, portIndex),
                    item.db_id,
                  );
                  const drafting = isLinkDraftPort(
                    item.db_id,
                    iface.interface_type,
                    portIndex,
                  );
                  return `
                    <div class="interface-port${drafting ? " is-draft" : ""}${peer ? " is-linked" : ""}">
                      <span class="port-index">${portIndex}</span>
                      <input class="connection-name-input" type="text" maxlength="80"
                             data-port-index="${portIndex}"
                             value="${escapeHtml(name)}"
                             placeholder="연결 이름"
                             aria-label="${escapeHtml(iface.interface_type)} ${portIndex} 연결 이름">
                      <button type="button" class="port-link-button"
                              data-interface-type="${escapeHtml(iface.interface_type)}"
                              data-port-index="${portIndex}"
                              data-connection-name="${escapeHtml(name)}"
                              title="${peer ? "다시 연결" : "연결 시작/완료"}">
                        ${drafting ? "선택됨" : "연결"}
                      </button>
                      ${peer ? `
                        <span class="port-peer" title="연결된 포트">
                          → ${escapeHtml(peer.equipmentName || peer.equipmentId)} /
                          ${escapeHtml(formatPortLabel(
                            peer.interfaceType,
                            peer.portIndex,
                            peer.connectionName,
                          ))}
                        </span>
                        <button type="button" class="port-unlink-button"
                                data-link-id="${peer.linkId}"
                                title="연결 해제" aria-label="연결 해제">해제</button>
                      ` : '<span class="port-peer"></span>'}
                    </div>
                  `;
                }).join("")}
                <div class="action-row connection-port-actions">
                  <button type="button" class="primary save-connection-names"
                          data-interface-type="${escapeHtml(iface.interface_type)}">이름 저장</button>
                </div>
                <p class="form-error connection-name-error" role="alert"></p>
              </div>
            ` : ""}
          </li>
        `;
      }).join("")}
    </ul>
  `;
}

function interfaceEditorRowHtml(item = { interface_type: "", port_count: 1 }) {
  return `
    <div class="interface-edit-row">
      <input class="interface-type-input" type="text" maxlength="40"
             placeholder="종류 (예: BNC)" required
             value="${escapeHtml(item.interface_type)}" aria-label="인터페이스 종류">
      <input class="interface-count-input" type="number" min="1" max="9999"
             value="${Number(item.port_count) || 1}" required aria-label="연결 수량">
      <button type="button" class="interface-remove" title="항목 제거"
              aria-label="인터페이스 항목 제거">×</button>
    </div>
  `;
}

function renderConnectionHtml(item, spec) {
  const editable = spec?.category_key === "broadcast_equipment";
  if (!state.connectionEditing || !editable) {
    return `
      ${state.linkDraft ? `
        <p class="link-draft-note">
          연결 모드: 대상 장비의 포트를 클릭하세요.
          <button type="button" id="cancel-link-draft-panel">취소</button>
        </p>
      ` : ""}
      ${renderInterfaceGroupsHtml(item, spec)}
      ${editable
        ? '<div class="action-row"><button id="edit-interfaces">수정</button></div>'
        : ""}
    `;
  }
  const interfaces = interfaceTotals(spec);
  return `
    <form id="interface-edit-form">
      <div id="interface-edit-list">
        ${interfaces.map((entry) => interfaceEditorRowHtml(entry)).join("")}
      </div>
      <button type="button" id="add-interface" class="interface-add">+ 항목 추가</button>
      <div class="action-row">
        <button type="submit" class="primary">저장</button>
        <button type="button" id="cancel-interface-edit">취소</button>
      </div>
      <p id="interface-edit-error" class="form-error" role="alert"></p>
    </form>
  `;
}

function syncConnectionNamesFromDom() {
  const expanded = state.expandedInterfaceType;
  if (!expanded) return;
  const inputs = document.querySelectorAll(
    `.interface-item[data-interface-type="${CSS.escape(expanded)}"] .connection-name-input`,
  );
  if (!inputs.length) return;
  state.connectionNamesByType[expanded] = [...inputs].map(
    (input) => input.value.trim(),
  );
}

async function ensurePortLinks(item) {
  if (item._portLinksLoaded) return item._portLinks || [];
  const links = await api(`/api/equipment/${item.db_id}/port-links`);
  item._portLinks = links;
  item._portLinksLoaded = true;
  return links;
}

async function loadEquipmentConnections(item) {
  try {
    const [rows] = await Promise.all([
      api(`/api/equipment/${item.db_id}/connections`),
      ensurePortLinks(item),
    ]);
    if (selectedItems()[0]?.db_id !== item.db_id) return;
    const byType = {};
    for (const row of rows) {
      if (!byType[row.interface_type]) byType[row.interface_type] = [];
      byType[row.interface_type][row.port_index - 1] = row.connection_name || "";
    }
    const next = {};
    for (const iface of interfaceTotals(specFor(item))) {
      const names = [];
      for (let index = 0; index < iface.port_count; index += 1) {
        names.push(byType[iface.interface_type]?.[index] || "");
      }
      next[iface.interface_type] = names;
    }
    state.connectionNamesByType = next;
    if (!state.connectionEditing) {
      refreshConnectionPanel(item);
    }
  } catch (error) {
    const panel = document.getElementById("connection-panel");
    if (panel && !state.connectionEditing) {
      const empty = panel.querySelector(".connection-empty");
      if (empty) empty.textContent = error.message;
    }
  }
}

function refreshConnectionPanel(item, editing = state.inspectorEditing) {
  const panel = document.getElementById("connection-panel");
  if (!panel) return;
  panel.innerHTML = renderConnectionHtml(item, specFor(item));
  bindConnectionPanel(item, editing);
  updateLinkDraftBanner();
}

async function completePortLink(fromDraft, toItem, interfaceType, portIndex, connectionName) {
  const link = await api("/api/equipment/port-links", {
    method: "POST",
    body: JSON.stringify({
      from: {
        db_id: fromDraft.db_id,
        interface_type: fromDraft.interface_type,
        port_index: fromDraft.port_index,
      },
      to: {
        db_id: toItem.db_id,
        interface_type: interfaceType,
        port_index: portIndex,
      },
    }),
  });
  const touch = (equipment) => {
    if (!equipment) return;
    equipment._portLinksLoaded = false;
    equipment._portLinks = [];
  };
  touch(state.items.find((entry) => entry.db_id === fromDraft.db_id));
  touch(toItem);
  state.linkDraft = null;
  updateLinkDraftBanner();
  await ensurePortLinks(toItem);
  const source = state.items.find((entry) => entry.db_id === fromDraft.db_id);
  if (source) await ensurePortLinks(source);
  refreshConnectionPanel(toItem);
  loadAllLinks();
  setStatus(
    `연결 완료: ${fromDraft.equipment_id}/${formatPortLabel(
      fromDraft.interface_type,
      fromDraft.port_index,
      fromDraft.connection_name,
    )} ↔ ${toItem.equipment_id}/${formatPortLabel(
      interfaceType,
      portIndex,
      connectionName,
    )}`,
  );
  return link;
}

function bindConnectionPanel(item, editing) {
  document.getElementById("cancel-link-draft-panel")?.addEventListener("click", () => {
    clearLinkDraft();
  });
  document.getElementById("edit-interfaces")?.addEventListener("click", () => {
    syncConnectionNamesFromDom();
    state.connectionEditing = true;
    state.expandedInterfaceType = null;
    state.linkDraft = null;
    updateLinkDraftBanner();
    refreshConnectionPanel(item, editing);
  });
  document.getElementById("cancel-interface-edit")?.addEventListener("click", () => {
    state.connectionEditing = false;
    refreshConnectionPanel(item, editing);
  });
  document.getElementById("add-interface")?.addEventListener("click", () => {
    document
      .getElementById("interface-edit-list")
      ?.insertAdjacentHTML("beforeend", interfaceEditorRowHtml());
  });

  const interfaceForm = document.getElementById("interface-edit-form");
  interfaceForm?.addEventListener("click", (event) => {
    const removeButton = event.target.closest(".interface-remove");
    if (removeButton) removeButton.closest(".interface-edit-row")?.remove();
  });
  interfaceForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const errorEl = document.getElementById("interface-edit-error");
    if (errorEl) errorEl.textContent = "";
    const rows = [...interfaceForm.querySelectorAll(".interface-edit-row")];
    const interfaces = rows.map((row) => ({
      interface_type: row.querySelector(".interface-type-input").value.trim(),
      port_count: Number(row.querySelector(".interface-count-input").value),
    }));
    const submitButton = interfaceForm.querySelector("[type='submit']");
    submitButton.disabled = true;
    try {
      const result = await api(
        `/api/equipment-types/${encodeURIComponent(item.spec_key)}/interfaces`,
        {
          method: "PUT",
          body: JSON.stringify({ interfaces }),
        },
      );
      for (const key of result.spec_keys) {
        const type = state.typeByKey.get(key);
        if (type) {
          type.interfaces = result.interfaces.map((entry) => ({ ...entry }));
        }
      }
      state.connectionEditing = false;
      await loadEquipmentConnections(item);
      setStatus(
        `${specFor(item)?.name || item.spec_key} 연결 정보를 저장했습니다.`,
      );
    } catch (error) {
      if (errorEl) errorEl.textContent = error.message;
      submitButton.disabled = false;
    }
  });

  document.querySelectorAll(".interface-type-toggle").forEach((button) => {
    button.addEventListener("click", () => {
      const typeName = button.dataset.interfaceType;
      syncConnectionNamesFromDom();
      state.expandedInterfaceType =
        state.expandedInterfaceType === typeName ? null : typeName;
      refreshConnectionPanel(item, editing);
    });
  });

  document.querySelectorAll(".save-connection-names").forEach((button) => {
    button.addEventListener("click", async () => {
      const typeName = button.dataset.interfaceType;
      const errorEl = button
        .closest(".interface-ports")
        ?.querySelector(".connection-name-error");
      if (errorEl) errorEl.textContent = "";
      const inputs = [
        ...document.querySelectorAll(
          `.interface-item[data-interface-type="${CSS.escape(typeName)}"] .connection-name-input`,
        ),
      ];
      const connectionNames = inputs.map((input) => input.value.trim());
      button.disabled = true;
      try {
        const saved = await api(`/api/equipment/${item.db_id}/connections`, {
          method: "PUT",
          body: JSON.stringify({
            interface_type: typeName,
            connection_names: connectionNames,
          }),
        });
        state.connectionNamesByType[typeName] = connectionNames;
        const byIndex = [];
        for (const row of saved) {
          byIndex[row.port_index - 1] = row.connection_name || "";
        }
        state.connectionNamesByType[typeName] = connectionNames.map(
          (name, index) => byIndex[index] ?? name,
        );
        setStatus(`${typeName} 연결 이름을 저장했습니다.`);
      } catch (error) {
        if (errorEl) errorEl.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });
  });

  document.querySelectorAll(".port-link-button").forEach((button) => {
    button.addEventListener("click", async () => {
      const interfaceType = button.dataset.interfaceType;
      const portIndex = Number(button.dataset.portIndex);
      const connectionName = button.dataset.connectionName || "";
      const errorEl = button
        .closest(".interface-ports")
        ?.querySelector(".connection-name-error");
      if (errorEl) errorEl.textContent = "";
      const draft = state.linkDraft;
      if (
        draft
        && draft.db_id === item.db_id
        && draft.interface_type === interfaceType
        && draft.port_index === portIndex
      ) {
        clearLinkDraft();
        setStatus("연결을 취소했습니다.");
        return;
      }
      if (draft && draft.db_id !== item.db_id) {
        button.disabled = true;
        try {
          await completePortLink(
            draft,
            item,
            interfaceType,
            portIndex,
            connectionName,
          );
        } catch (error) {
          if (errorEl) errorEl.textContent = error.message;
          setStatus(`연결 실패: ${error.message}`);
        } finally {
          button.disabled = false;
        }
        return;
      }
      state.linkDraft = {
        db_id: item.db_id,
        equipment_id: item.equipment_id,
        interface_type: interfaceType,
        port_index: portIndex,
        connection_name: connectionName,
      };
      updateLinkDraftBanner();
      refreshConnectionPanel(item, editing);
      setStatus(
        `${item.equipment_id}/${formatPortLabel(interfaceType, portIndex, connectionName)} 연결 시작 — 대상 장비를 선택한 뒤 포트를 클릭하세요.`,
      );
    });
  });

  document.querySelectorAll(".port-unlink-button").forEach((button) => {
    button.addEventListener("click", async () => {
      const linkId = Number(button.dataset.linkId);
      if (!window.confirm("이 포트 연결을 해제할까요?")) return;
      const errorEl = button
        .closest(".interface-ports")
        ?.querySelector(".connection-name-error");
      if (errorEl) errorEl.textContent = "";
      button.disabled = true;
      try {
        await api(`/api/equipment/port-links/${linkId}`, { method: "DELETE" });
        item._portLinksLoaded = false;
        await ensurePortLinks(item);
        for (const other of state.items) {
          if (other.db_id !== item.db_id && other._portLinksLoaded) {
            other._portLinksLoaded = false;
            other._portLinks = [];
          }
        }
        refreshConnectionPanel(item, editing);
        loadAllLinks();
        setStatus("포트 연결을 해제했습니다.");
      } catch (error) {
        if (errorEl) errorEl.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });
  });
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
  const photoSourceLabel = photoSourceCaption(item);
  const photoHtml = photoUrl
    ? `
      <div class="equipment-photo-wrap">
        <img class="equipment-photo" src="${escapeHtml(photoUrl)}"
             alt="${escapeHtml(equipmentPhotoQuery(item) || "장비 이미지")}">
        <button type="button" id="clear-photo" class="photo-clear"
                title="이미지 제거" aria-label="이미지 제거">×</button>
      </div>
      ${photoSourceLabel}
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
    <section class="info-section connection-section">
      <h2>연결 정보</h2>
      <div id="connection-panel">
        ${renderConnectionHtml(item, specFor(item))}
      </div>
    </section>
    <div class="info-divider"></div>
    <section class="info-section equipment-photo-section">
      <h2>장비 이미지</h2>
      ${photoHtml}
      ${item._photoError ? `<p class="photo-error">${escapeHtml(item._photoError)}</p>` : ""}
      ${item._googleImagesUrl
        ? `<a class="photo-google-link" href="${escapeHtml(item._googleImagesUrl)}" target="_blank" rel="noopener noreferrer">Google 이미지에서 직접 검색</a>`
        : ""}
      <div class="action-row photo-actions">
        <button id="search-photo" ${item.equipment_model ? "" : "disabled"}>모델 이미지 검색</button>
        <label class="upload-photo-button">
          수동 이미지 등록
          <input id="upload-photo" type="file" accept="image/jpeg,image/png,image/webp">
        </label>
      </div>
    </section>
    <div class="info-divider"></div>
    <section class="info-section equipment-log-section">
      <h2>장비 로그</h2>
      <div class="log-table" aria-label="장비 로그">
        <div class="log-row log-header">
          <span>날짜</span>
          <span>구분</span>
          <span>조치사항</span>
          <span></span>
        </div>
        <div id="equipment-log-list" class="log-list">
          <p class="log-empty">로그를 불러오는 중...</p>
        </div>
      </div>
      <form id="equipment-log-form" class="log-form" data-editing-log-id="">
        <input id="log-date" name="log_date" type="date" required
               value="${todayLogDateInput()}" aria-label="날짜">
        <input id="log-category" name="category" type="text" maxlength="40"
               placeholder="구분" required list="log-category-options"
               aria-label="구분">
        <datalist id="log-category-options">
          <option value="고장"></option>
          <option value="변경"></option>
          <option value="설치"></option>
          <option value="점검"></option>
          <option value="수리"></option>
        </datalist>
        <input id="log-action" name="action" type="text" maxlength="200"
               placeholder="조치사항" required aria-label="조치사항">
        <div class="log-form-actions">
          <button class="primary" id="log-submit" type="submit">추가</button>
          <button type="button" id="log-cancel-edit" class="log-cancel-edit" hidden>취소</button>
        </div>
      </form>
      <p id="equipment-log-error" class="form-error" role="alert"></p>
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
  bindConnectionPanel(item, editing);
  loadEquipmentConnections(item);
  document.getElementById("search-photo")?.addEventListener("click", () => {
    searchEquipmentPhoto(item);
  });
  document.getElementById("clear-photo")?.addEventListener("click", () => {
    clearEquipmentPhoto(item);
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
  bindEquipmentLogForm(item);
  loadEquipmentLogs(item);
}

function todayLogDateInput() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function logDateToInput(value) {
  const digits = String(value || "").replace(/\D/g, "");
  if (digits.length !== 8) return todayLogDateInput();
  return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6, 8)}`;
}

function logDateFromInput(value) {
  return String(value || "").replace(/\D/g, "");
}

function resetEquipmentLogForm() {
  const form = document.getElementById("equipment-log-form");
  if (!form) return;
  form.dataset.editingLogId = "";
  form.reset();
  document.getElementById("log-date").value = todayLogDateInput();
  const submitButton = document.getElementById("log-submit");
  const cancelButton = document.getElementById("log-cancel-edit");
  if (submitButton) submitButton.textContent = "추가";
  if (cancelButton) cancelButton.hidden = true;
  document.querySelectorAll(".log-row.is-editing").forEach((row) => {
    row.classList.remove("is-editing");
  });
}

function fillEquipmentLogForm(log) {
  const form = document.getElementById("equipment-log-form");
  if (!form) return;
  form.dataset.editingLogId = String(log.log_id);
  document.getElementById("log-date").value = logDateToInput(log.log_date);
  document.getElementById("log-category").value = log.category;
  document.getElementById("log-action").value = log.action;
  const submitButton = document.getElementById("log-submit");
  const cancelButton = document.getElementById("log-cancel-edit");
  if (submitButton) submitButton.textContent = "저장";
  if (cancelButton) cancelButton.hidden = false;
  document.querySelectorAll(".log-row.is-editing").forEach((row) => {
    row.classList.remove("is-editing");
  });
  document
    .querySelector(`.log-row[data-log-id="${log.log_id}"]`)
    ?.classList.add("is-editing");
  document.getElementById("log-category")?.focus();
}

function renderEquipmentLogRows(item, logs) {
  const list = document.getElementById("equipment-log-list");
  const form = document.getElementById("equipment-log-form");
  if (!list) return;
  if (!logs.length) {
    list.innerHTML = '<p class="log-empty">등록된 로그가 없습니다.</p>';
    return;
  }
  const editingId = form?.dataset.editingLogId || "";
  list.innerHTML = logs.map((log) => `
    <div class="log-row${String(log.log_id) === editingId ? " is-editing" : ""}"
         data-log-id="${log.log_id}">
      <span class="log-date">${escapeHtml(log.log_date)}</span>
      <span class="log-category">${escapeHtml(log.category)}</span>
      <span class="log-action">${escapeHtml(log.action)}</span>
      <div class="log-row-actions">
        <button type="button" class="log-edit" data-log-id="${log.log_id}"
                title="로그 수정" aria-label="로그 수정">✎</button>
        <button type="button" class="log-delete" data-log-id="${log.log_id}"
                title="로그 삭제" aria-label="로그 삭제">×</button>
      </div>
    </div>
  `).join("");

  list.querySelectorAll(".log-edit").forEach((button) => {
    button.addEventListener("click", () => {
      const logId = Number(button.dataset.logId);
      const log = logs.find((entry) => entry.log_id === logId);
      if (log) fillEquipmentLogForm(log);
    });
  });

  list.querySelectorAll(".log-delete").forEach((button) => {
    button.addEventListener("click", async () => {
      const logId = Number(button.dataset.logId);
      if (!window.confirm("이 로그를 삭제할까요?")) return;
      try {
        await api(`/api/equipment/${item.db_id}/logs/${logId}`, {
          method: "DELETE",
        });
        if (form?.dataset.editingLogId === String(logId)) {
          resetEquipmentLogForm();
        }
        await loadEquipmentLogs(item);
        setStatus("장비 로그를 삭제했습니다.");
      } catch (error) {
        const errorEl = document.getElementById("equipment-log-error");
        if (errorEl) errorEl.textContent = error.message;
      }
    });
  });
}

async function loadEquipmentLogs(item) {
  const list = document.getElementById("equipment-log-list");
  const errorEl = document.getElementById("equipment-log-error");
  if (errorEl) errorEl.textContent = "";
  try {
    const logs = await api(`/api/equipment/${item.db_id}/logs`);
    if (selectedItems()[0]?.db_id !== item.db_id) return;
    renderEquipmentLogRows(item, logs);
  } catch (error) {
    if (list) {
      list.innerHTML = `<p class="log-empty">${escapeHtml(error.message)}</p>`;
    }
  }
}

function bindEquipmentLogForm(item) {
  const form = document.getElementById("equipment-log-form");
  const errorEl = document.getElementById("equipment-log-error");
  const cancelButton = document.getElementById("log-cancel-edit");
  if (!form) return;
  cancelButton?.addEventListener("click", () => {
    resetEquipmentLogForm();
    if (errorEl) errorEl.textContent = "";
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (errorEl) errorEl.textContent = "";
    const submitButton = document.getElementById("log-submit");
    const editingLogId = form.dataset.editingLogId;
    const payload = {
      log_date: logDateFromInput(document.getElementById("log-date").value),
      category: document.getElementById("log-category").value.trim(),
      action: document.getElementById("log-action").value.trim(),
    };
    if (!payload.log_date || payload.log_date.length !== 8) {
      if (errorEl) errorEl.textContent = "날짜를 선택해주세요.";
      return;
    }
    submitButton.disabled = true;
    try {
      if (editingLogId) {
        await api(`/api/equipment/${item.db_id}/logs/${editingLogId}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        setStatus("장비 로그를 수정했습니다.");
      } else {
        await api(`/api/equipment/${item.db_id}/logs`, {
          method: "POST",
          body: JSON.stringify(payload),
        });
        setStatus("장비 로그를 추가했습니다.");
      }
      resetEquipmentLogForm();
      await loadEquipmentLogs(item);
    } catch (error) {
      if (errorEl) errorEl.textContent = error.message;
    } finally {
      submitButton.disabled = false;
    }
  });
}

function photoSourceCaption(item) {
  if (!item.photo_source_url) {
    return item.photo_query === "manual"
      ? '<span class="photo-source photo-source-muted">수동 등록</span>'
      : "";
  }
  let label = item.photo_source_label || "";
  if (!label) {
    try {
      const host = new URL(item.photo_source_url).hostname.replace(/^www\./, "");
      if (host.includes("google.")) label = "Google";
      else if (host.includes("wikimedia") || host.includes("wikipedia")) label = "Wikimedia";
      else label = host || "웹";
    } catch {
      label = "웹";
    }
  }
  return `<a class="photo-source" href="${escapeHtml(item.photo_source_url)}"
             target="_blank" rel="noopener noreferrer">© ${escapeHtml(label)}</a>`;
}

async function clearEquipmentPhoto(item) {
  if (!item.photo_url) return;
  if (!window.confirm("등록된 장비 이미지를 제거할까요?")) return;
  item._photoError = "";
  try {
    const updated = await api(`/api/equipment/${item.db_id}/clear-photo`, {
      method: "POST",
    });
    Object.assign(item, updated);
    item._photoCacheBust = Date.now();
    renderInspector(false);
    setStatus("장비 이미지를 제거했습니다.");
  } catch (error) {
    item._photoError = error.message;
    renderInspector(false);
    setStatus(`이미지 제거 실패: ${error.message}`);
  }
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
    const response = await fetch(`/api/equipment/${item.db_id}/search-image`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const googleUrl = payload.google_images_url
        || `https://www.google.com/search?tbm=isch&q=${encodeURIComponent(query)}`;
      item._photoError = payload.error || `검색 실패 (${response.status})`;
      item._googleImagesUrl = googleUrl;
      renderInspector(false);
      setStatus(`이미지 검색 실패: ${item._photoError}`);
      window.open(googleUrl, "_blank", "noopener,noreferrer");
      return;
    }
    Object.assign(item, payload);
    item._photoCacheBust = Date.now();
    item._photoError = "";
    item._googleImagesUrl = "";
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
    loadAllLinks();
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
            rackMetrics(rack).unitHeight * Math.max(1, instanceRu(item, spec));
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

function tooltipConnectionLines(item, links) {
  const lines = [];
  for (const link of links) {
    const peer = portPeerSummary(link, item.db_id);
    if (!peer) continue;
    const localIsA = link.a_equipment_db_id === item.db_id;
    const localType = localIsA ? link.a_interface_type : link.b_interface_type;
    const localIndex = localIsA ? link.a_port_index : link.b_port_index;
    const localName = localIsA ? link.a_connection_name : link.b_connection_name;
    lines.push(
      `${formatPortLabel(localType, localIndex, localName)} → `
      + `${peer.equipmentName || peer.equipmentId} / `
      + `${formatPortLabel(peer.interfaceType, peer.portIndex, peer.connectionName)}`,
    );
  }
  return lines;
}

async function showTooltip(item, x, y) {
  if (
    item.spec_key.startsWith("blank_panel_") ||
    item.spec_key === "drawer_2ru"
  ) {
    hideTooltip();
    return;
  }
  const hoverToken = `${item.db_id}:${x}:${y}`;
  state._tooltipToken = hoverToken;
  const spec = specFor(item);
  let linkHtml = "";
  try {
    const links = await ensurePortLinks(item);
    if (state._tooltipToken !== hoverToken) return;
    const lines = tooltipConnectionLines(item, links);
    if (lines.length) {
      const visible = lines.slice(0, 5);
      const extra = lines.length - visible.length;
      linkHtml = `<br>${visible.map((line) => (
        `연결: ${escapeHtml(line)}`
      )).join("<br>")}`;
      if (extra > 0) {
        linkHtml += `<br>연결: 외 ${extra}건`;
      }
    }
  } catch {
    // tooltip still shows name/id
  }
  if (state._tooltipToken !== hoverToken) return;
  tooltip.innerHTML = `
    <strong>${escapeHtml(item.equipment_name || spec?.name || item.spec_key)}</strong><br>
    ID: ${escapeHtml(item.equipment_id)}${linkHtml}
  `;
  tooltip.style.left = `${Math.min(x + 14, wrap.clientWidth - 260)}px`;
  tooltip.style.top = `${Math.min(y + 14, wrap.clientHeight - 140)}px`;
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

async function loadAllLinks() {
  try {
    state.links = await api("/api/port-links");
  } catch {
    state.links = [];
  }
  draw();
}

function setCableMode(active) {
  state.cableMode = active;
  cableModeButton.classList.toggle("is-active", active);
  cableModeButton.setAttribute("aria-pressed", active ? "true" : "false");
  board.classList.toggle("cabling", active);
  if (active) {
    cancelPlacement();
    hideTooltip();
    setStatus("케이블 연결 모드: 장비를 클릭해 포트를 선택하세요. (Esc 종료)");
  } else {
    closePortMenu();
    if (state.linkDraft) clearLinkDraft();
    setStatus("준비됨");
  }
}

function closePortMenu() {
  portMenu.classList.add("hidden");
  portMenu.innerHTML = "";
  state.portMenuItemId = null;
}

async function fetchConnectionNames(item) {
  try {
    const rows = await api(`/api/equipment/${item.db_id}/connections`);
    const byType = {};
    for (const row of rows) {
      (byType[row.interface_type] ||= [])[row.port_index - 1] =
        row.connection_name || "";
    }
    return byType;
  } catch {
    return {};
  }
}

function portMenuHtml(item, byType) {
  const spec = specFor(item);
  const title = escapeHtml(item.equipment_name || spec?.name || item.spec_key);
  let html =
    `<div class="port-menu-title">${title} · ${escapeHtml(item.equipment_id)}</div>`;
  const ifaces = interfaceTotals(spec);
  if (!ifaces.length) {
    return `${html}<div class="port-menu-empty">등록된 포트가 없습니다.</div>`;
  }
  const draft = state.linkDraft;
  if (draft && draft.db_id !== item.db_id) {
    html += `<div class="port-menu-hint">${escapeHtml(
      `${draft.equipment_id}/${formatPortLabel(
        draft.interface_type,
        draft.port_index,
        draft.connection_name,
      )} → 연결할 포트 선택`,
    )}</div>`;
  } else {
    html += '<div class="port-menu-hint">시작할 포트를 선택하세요</div>';
  }
  const rows = [];
  for (const iface of ifaces) {
    for (let index = 1; index <= iface.port_count; index += 1) {
      const name = byType[iface.interface_type]?.[index - 1] || "";
      const link = portLinkFor(item, iface.interface_type, index);
      const peer = portPeerSummary(link, item.db_id);
      const isDraft = Boolean(
        draft
        && draft.db_id === item.db_id
        && draft.interface_type === iface.interface_type
        && draft.port_index === index,
      );
      rows.push(`
        <div class="port-menu-row${peer ? " is-linked" : ""}${isDraft ? " is-draft" : ""}">
          <button type="button" class="port-menu-select"
                  data-interface-type="${escapeHtml(iface.interface_type)}"
                  data-port-index="${index}"
                  data-connection-name="${escapeHtml(name)}">
            <span class="port-menu-label">${escapeHtml(
              formatPortLabel(iface.interface_type, index, name),
            )}</span>
            ${peer ? `<span class="port-menu-peer">→ ${escapeHtml(peer.equipmentId)} / ${escapeHtml(
              formatPortLabel(peer.interfaceType, peer.portIndex, peer.connectionName),
            )}</span>` : ""}
          </button>
          ${peer ? `<button type="button" class="port-menu-unlink" data-link-id="${peer.linkId}">해제</button>` : ""}
        </div>
      `);
    }
  }
  return `${html}<div class="port-menu-list">${rows.join("")}</div>`;
}

async function openPortMenu(item, x, y) {
  hideTooltip();
  hideContextMenu();
  item._portLinksLoaded = false;
  await ensurePortLinks(item);
  const byType = await fetchConnectionNames(item);
  state.portMenuItemId = item.db_id;
  portMenu.innerHTML = portMenuHtml(item, byType);
  portMenu.classList.remove("hidden");
  const menuWidth = portMenu.offsetWidth || 236;
  const menuHeight = portMenu.offsetHeight || 200;
  portMenu.style.left =
    `${Math.max(4, Math.min(x, wrap.clientWidth - menuWidth - 4))}px`;
  portMenu.style.top =
    `${Math.max(4, Math.min(y, wrap.clientHeight - menuHeight - 4))}px`;
}

async function handlePortSelect(item, interfaceType, portIndex, connectionName) {
  const draft = state.linkDraft;
  if (
    draft
    && draft.db_id === item.db_id
    && draft.interface_type === interfaceType
    && draft.port_index === portIndex
  ) {
    clearLinkDraft();
    closePortMenu();
    setStatus("연결을 취소했습니다.");
    return;
  }
  if (draft && draft.db_id !== item.db_id) {
    try {
      await completePortLink(draft, item, interfaceType, portIndex, connectionName);
      closePortMenu();
    } catch (error) {
      setStatus(`연결 실패: ${error.message}`);
    }
    return;
  }
  state.linkDraft = {
    db_id: item.db_id,
    equipment_id: item.equipment_id,
    interface_type: interfaceType,
    port_index: portIndex,
    connection_name: connectionName,
  };
  updateLinkDraftBanner();
  closePortMenu();
  setStatus(
    `${item.equipment_id}/${formatPortLabel(interfaceType, portIndex, connectionName)}`
    + " 연결 시작 — 다른 장비를 클릭해 포트를 선택하세요.",
  );
}

portMenu.addEventListener("click", async (event) => {
  const item = state.items.find(
    (entry) => entry.db_id === state.portMenuItemId,
  );
  if (!item) return;
  const unlinkButton = event.target.closest(".port-menu-unlink");
  if (unlinkButton) {
    const linkId = Number(unlinkButton.dataset.linkId);
    try {
      await api(`/api/equipment/port-links/${linkId}`, { method: "DELETE" });
      for (const entry of state.items) {
        entry._portLinksLoaded = false;
        entry._portLinks = [];
      }
      await loadAllLinks();
      await ensurePortLinks(item);
      const byType = await fetchConnectionNames(item);
      portMenu.innerHTML = portMenuHtml(item, byType);
      setStatus("포트 연결을 해제했습니다.");
    } catch (error) {
      setStatus(`해제 실패: ${error.message}`);
    }
    return;
  }
  const selectButton = event.target.closest(".port-menu-select");
  if (selectButton) {
    await handlePortSelect(
      item,
      selectButton.dataset.interfaceType,
      Number(selectButton.dataset.portIndex),
      selectButton.dataset.connectionName || "",
    );
  }
});

cableModeButton.addEventListener("click", () => setCableMode(!state.cableMode));

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
  if (state.cableMode) {
    const target = hitTest(point.x, point.y);
    if (target) openPortMenu(target, point.x, point.y);
    else closePortMenu();
    return;
  }
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
  if (state.cableMode) {
    hideTooltip();
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
  if (!portMenu.contains(event.target) && !board.contains(event.target)) {
    closePortMenu();
  }
});

function isTextFieldTarget(target) {
  return Boolean(
    target?.closest?.("input, textarea, select, [contenteditable='true']"),
  );
}

function hasTextSelection() {
  const selection = window.getSelection();
  return Boolean(
    selection && !selection.isCollapsed && selection.toString().length,
  );
}

function isInspectorTarget(target) {
  return Boolean(target?.closest?.(".inspector"));
}

document.addEventListener("keydown", (event) => {
  if (isTextFieldTarget(event.target)) return;
  if (event.ctrlKey && event.key.toLowerCase() === "z") {
    event.preventDefault();
    undoLastAction();
    return;
  }
  if (event.ctrlKey && event.key.toLowerCase() === "c") {
    // 우측 장비 정보 등에서 드래그 선택한 텍스트는 브라우저 기본 복사 사용
    if (hasTextSelection() || isInspectorTarget(event.target)) return;
    if (state.selected.size) {
      event.preventDefault();
      copySelected();
    }
    return;
  }
  if (event.ctrlKey && event.key.toLowerCase() === "v") {
    if (isInspectorTarget(event.target)) return;
    event.preventDefault();
    pasteEquipment();
    return;
  }
  if (event.key === "Escape") {
    if (!portMenu.classList.contains("hidden")) {
      closePortMenu();
      return;
    }
    if (state.linkDraft) {
      clearLinkDraft();
      setStatus("연결을 취소했습니다.");
      return;
    }
    if (state.cableMode) {
      setCableMode(false);
      return;
    }
    if (!cancelPlacement()) hideContextMenu();
    return;
  }
  if (event.key === "Delete") {
    if (hasTextSelection() || isInspectorTarget(event.target)) return;
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
  if (isInspectorTarget(event.target)) return;
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

editCatalogButton.addEventListener("click", openCatalogEditor);
closeCatalogEditorButton.addEventListener("click", () => {
  catalogEditorDialog.close();
});
addEquipmentTypeButton.addEventListener("click", () => {
  openEquipmentTypeDialog();
});
document
  .getElementById("cancel-equipment-type")
  .addEventListener("click", () => equipmentTypeDialog.close());
newTypeName.addEventListener("input", () => {
  if (newTypePrefix.dataset.manual !== "true") {
    newTypePrefix.value = suggestedIdPrefix(newTypeName.value);
  }
});
newTypePrefix.addEventListener("input", () => {
  newTypePrefix.dataset.manual = "true";
  newTypePrefix.value = newTypePrefix.value.toUpperCase();
});
equipmentTypeForm.addEventListener("submit", saveEquipmentType);
equipmentTypeDialog.addEventListener("close", () => {
  state.typeEditor = null;
});

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
    loadAllLinks();
    setStatus("준비됨 — 마우스 휠 줌 / 가운데 버튼 이동");
  } catch (error) {
    setStatus(`초기화 오류: ${error.message}`);
  }
}

new ResizeObserver(resizeCanvas).observe(wrap);
initialize();
