"""
Draws the physical floorplan of the health monitor as an SVG picture (no extra packages needed).

Input : the CSV written by hardware/vivado/export_placement.tcl (every placed cell of regions R1..R4 with its
        slice location, plus the four Pblock rectangles).
Output: floorplan_placement.svg  - the chip's slice grid, the four Pblock rectangles, and every slice that holds
        logic of a region, coloured by region (darker = more cells in that slice). The ring oscillators are marked.

    python hardware/vivado/plot_floorplan.py [placement.csv] [floorplan_placement.svg]
"""

import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"C:\vivado_build\placement.csv")
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "floorplan_placement.svg"

COLORS = {"R1": "#ef4444", "R2": "#22c55e", "R3": "#3b82f6", "R4": "#f59e0b"}
CELL_W, CELL_H = 9, 5.2           # pixels per slice column / row
MARGIN_L, MARGIN_T = 70, 90
SLICE_RE = re.compile(r"SLICE_X(\d+)Y(\d+)")


def main() -> None:
    cells = defaultdict(Counter)      # region -> {(x, y): cells in that slice}
    osc = defaultdict(set)            # region -> slices holding ring-oscillator LUTs
    boxes = {}
    kinds = defaultdict(Counter)
    with SRC.open(newline="") as f:
        for row in csv.DictReader(f):
            region, site = row["region"], row["site"]
            if region == "PBLOCK":
                m = re.match(r"SLICE_X(\d+)Y(\d+):SLICE_X(\d+)Y(\d+)", site)
                boxes[row["cell"].replace("pblock_", "")] = tuple(int(v) for v in m.groups())
                continue
            m = SLICE_RE.match(site)
            if not m:
                continue
            xy = (int(m.group(1)), int(m.group(2)))
            cells[region][xy] += 1
            kinds[region][row["kind"]] += 1
            if "u_ring_osc" in row["cell"]:
                osc[region].add(xy)

    max_x = max(b[2] for b in boxes.values()) + 1
    max_y = max(b[3] for b in boxes.values()) + 1
    width = MARGIN_L + max_x * CELL_W + 330
    height = MARGIN_T + max_y * CELL_H + 50

    def px(x):
        return MARGIN_L + x * CELL_W

    def py(y):                         # slice Y grows upwards on the chip
        return MARGIN_T + (max_y - 1 - y) * CELL_H

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}" font-family="Segoe UI, Arial, sans-serif">',
           f'<rect width="{width}" height="{height}" fill="#0b1020"/>',
           f'<text x="{MARGIN_L}" y="36" fill="#e2e8f0" font-size="22" font-weight="700">'
           'Physical floorplan: four Pblock regions on the Artix-7 XC7A35T (Basys 3)</text>',
           f'<text x="{MARGIN_L}" y="60" fill="#94a3b8" font-size="13">Every coloured square is a slice that holds '
           'logic of that region, taken from the routed design. Darker = more cells in the slice. '
           'Black diamonds = ring-oscillator LUTs.</text>',
           # the fabric
           f'<rect x="{px(0)}" y="{py(max_y - 1)}" width="{max_x * CELL_W}" height="{max_y * CELL_H}" '
           'fill="#111a2e" stroke="#334155"/>']

    # light grid every 10 slices
    for x in range(0, max_x + 1, 10):
        out.append(f'<line x1="{px(x)}" y1="{py(max_y - 1)}" x2="{px(x)}" y2="{py(0) + CELL_H}" stroke="#1e293b"/>')
        out.append(f'<text x="{px(x)}" y="{py(0) + CELL_H + 16}" fill="#64748b" font-size="10" text-anchor="middle">X{x}</text>')
    for y in range(0, max_y + 1, 10):
        out.append(f'<line x1="{px(0)}" y1="{py(y) + CELL_H}" x2="{px(max_x)}" y2="{py(y) + CELL_H}" stroke="#1e293b"/>')
        out.append(f'<text x="{px(0) - 8}" y="{py(y) + CELL_H + 4}" fill="#64748b" font-size="10" text-anchor="end">Y{y}</text>')

    # the placed logic
    for r, per_slice in cells.items():
        peak = max(per_slice.values())
        for (x, y), n in per_slice.items():
            op = 0.25 + 0.75 * n / peak
            out.append(f'<rect x="{px(x):.1f}" y="{py(y):.1f}" width="{CELL_W - 0.8}" height="{CELL_H - 0.6}" '
                       f'fill="{COLORS[r]}" fill-opacity="{op:.2f}"/>')
    for r, sl in osc.items():
        for (x, y) in sl:
            cx, cy = px(x) + CELL_W / 2, py(y) + CELL_H / 2
            out.append(f'<path d="M{cx:.1f} {cy - 4:.1f} L{cx + 4:.1f} {cy:.1f} L{cx:.1f} {cy + 4:.1f} '
                       f'L{cx - 4:.1f} {cy:.1f} Z" fill="#000" stroke="#fff" stroke-width="1"/>')

    # the Pblock rectangles and their labels
    for r, (x0, y0, x1, y1) in sorted(boxes.items()):
        rx, ry = px(x0), py(y1)
        rw, rh = (x1 - x0 + 1) * CELL_W, (y1 - y0 + 1) * CELL_H
        out.append(f'<rect x="{rx}" y="{ry}" width="{rw}" height="{rh}" fill="{COLORS[r]}" fill-opacity="0.06" '
                   f'stroke="{COLORS[r]}" stroke-width="2.5" stroke-dasharray="7 4"/>')
        out.append(f'<text x="{rx + 8}" y="{ry + 22}" fill="{COLORS[r]}" font-size="17" font-weight="700">'
                   f'pblock_{r}</text>')
        out.append(f'<text x="{rx + 8}" y="{ry + 38}" fill="#cbd5e1" font-size="11">'
                   f'SLICE_X{x0}Y{y0}:X{x1}Y{y1}</text>')

    # legend / facts
    lx = px(max_x) + 40
    out.append(f'<text x="{lx}" y="{MARGIN_T + 10}" fill="#e2e8f0" font-size="15" font-weight="700">Regions</text>')
    yy = MARGIN_T + 34
    for r in sorted(boxes):
        x0, y0, x1, y1 = boxes[r]
        total = sum(cells[r].values())
        outside = sum(n for (x, y), n in cells[r].items() if not (x0 <= x <= x1 and y0 <= y <= y1))
        out.append(f'<rect x="{lx}" y="{yy - 12}" width="14" height="14" fill="{COLORS[r]}"/>')
        out.append(f'<text x="{lx + 22}" y="{yy}" fill="#e2e8f0" font-size="13" font-weight="600">{r}</text>')
        out.append(f'<text x="{lx + 22}" y="{yy + 17}" fill="#94a3b8" font-size="11.5">{total} cells in {len(cells[r])} slices</text>')
        out.append(f'<text x="{lx + 22}" y="{yy + 33}" fill="{"#4ade80" if outside == 0 else "#f87171"}" font-size="11.5">'
                   f'{outside} cells outside the Pblock</text>')
        yy += 62
    out.append(f'<text x="{lx}" y="{yy + 10}" fill="#94a3b8" font-size="11.5">Each region holds its own ring oscillator,</text>')
    out.append(f'<text x="{lx}" y="{yy + 26}" fill="#94a3b8" font-size="11.5">frequency counter and stress heaters.</text>')
    out.append("</svg>")
    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {OUT}")
    for r in sorted(boxes):
        x0, y0, x1, y1 = boxes[r]
        outside = sum(n for (x, y), n in cells[r].items() if not (x0 <= x <= x1 and y0 <= y <= y1))
        print(f"  {r}: {sum(cells[r].values())} cells, {len(cells[r])} slices, {outside} outside its Pblock")


if __name__ == "__main__":
    main()
