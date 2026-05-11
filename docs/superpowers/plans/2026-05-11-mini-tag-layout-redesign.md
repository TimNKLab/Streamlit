# Mini Tag Layout Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign `_draw_mini_tag` in `PriceTagService` to use a cleaner vertical layout (name/price/code/date) for 55mm × 25mm mini tags.

**Architecture:** Replace the current 3-zone horizontal strip layout with a vertical 3-zone layout: top=name, middle=price, bottom row split for code (left) and last update date (right). No barcode graphic. Discount shows only final price (big).

**Tech Stack:** Python, ReportLab, existing `price_tag_service.py` codebase

---

## File Structure

| File | Responsibility |
|------|----------------|
| `logic/price_tag_service.py` | Contains `_draw_mini_tag()` method to be rewritten |

---

### Task 1: Rewrite `_draw_mini_tag` Method

**Files:**
- Modify: `d:\NKLabs\Streamlit\logic\price_tag_service.py:648-760` (entire `_draw_mini_tag` method)

**Design Specification:**

For mini tag 55mm × 25mm:
- **Zone 1 (Top ~30% height)**: Product name
  - centered horizontally
  - bold font (use `self.MAIN_FONT_BOLD`)
  - auto-truncate with ellipsis if overflow
  - font size: `min(9, int(H * 0.35))` where H is tag height in points
- **Zone 2 (Middle ~45% height)**: Price
  - centered horizontally
  - if `diskon` exists: show **only diskon** (big)
  - else: show `het` (big)
  - font size: `min(14, int(H * 0.50))`
- **Zone 3 (Bottom ~25% height)**: Bottom row split 50/50
  - **Left**: `barcode_short` (last 6 digits of barcode)
  - **Right**: `date_str` (today's date, format from `self.today_str()`)
  - both small font, gray color
  - font size: `min(6, int(H * 0.20))`

**Padding:** Use `PAD = 1.0` (1 point padding)

**Border:** Same as standard - thin dark stroke (`#333333`, linewidth 0.3)

---

- [ ] **Step 1: Read current `_draw_mini_tag` implementation**

Read: `d:\NKLabs\Streamlit\logic\price_tag_service.py` lines 648-760
Understand: current 3-zone horizontal layout to be replaced

- [ ] **Step 2: Write new vertical layout implementation**

Replace entire `_draw_mini_tag` method with:

```python
    def _draw_mini_tag(
        self,
        c,
        item: Dict[str, Any],
        tx: float,
        ty: float,
        W: float,
        H: float,
    ):
        """Draw a mini price tag (55mm x 25mm) - vertical name/price/code layout."""
        if not HAS_REPORTLAB:
            return

        barcode_val = str(item.get("barcode", "")).strip()
        name = str(item.get("name", "")).strip()
        het = item.get("het")
        diskon = item.get("diskon")
        barcode_short = barcode_val[-6:] if len(barcode_val) >= 6 else barcode_val
        date_str = self.today_str()

        # Padding
        PAD = 1.0
        inner_w = W - 2 * PAD
        inner_h = H - 2 * PAD

        # Draw border
        c.setStrokeColorRGB(*_hex_to_rgb("#333333"))
        c.setLineWidth(0.3)
        c.rect(tx, ty, W, H, stroke=1, fill=0)

        # Zone heights (percentages)
        name_zone_h = inner_h * 0.30
        price_zone_h = inner_h * 0.45
        bottom_zone_h = inner_h * 0.25

        # Vertical positions (from bottom)
        bottom_y = ty + PAD
        price_y = bottom_y + bottom_zone_h
        name_y = price_y + price_zone_h

        # Zone 1: Product name (top)
        name_fs = min(9, int(H * 0.35))
        c.setFont(self.MAIN_FONT_BOLD, name_fs)
        c.setFillColorRGB(*_hex_to_rgb("#000000"))
        
        # Truncate name if too long
        display_name = name
        while _str_width(display_name, self.MAIN_FONT_BOLD, name_fs) > inner_w and len(display_name) > 3:
            display_name = display_name[:-1]
        if len(display_name) < len(name):
            display_name = display_name[:-1] + "…"
        
        name_w = _str_width(display_name, self.MAIN_FONT_BOLD, name_fs)
        name_x = tx + PAD + (inner_w - name_w) / 2
        name_text_y = name_y + (name_zone_h - name_fs) / 2
        c.drawString(name_x, name_text_y, display_name)

        # Zone 2: Price (middle)
        price_fs = min(14, int(H * 0.50))
        c.setFont(self.MAIN_FONT_BOLD, price_fs)
        c.setFillColorRGB(*_hex_to_rgb("#000000"))
        
        # Show diskon if exists, otherwise het
        price_text = self.format_price(diskon) if diskon else self.format_price(het)
        price_w = _str_width(price_text, self.MAIN_FONT_BOLD, price_fs)
        price_x = tx + PAD + (inner_w - price_w) / 2
        price_text_y = price_y + (price_zone_h - price_fs) / 2
        c.drawString(price_x, price_text_y, price_text)

        # Zone 3: Bottom row (code left, date right)
        bottom_fs = min(6, int(H * 0.20))
        c.setFont(self.MAIN_FONT, bottom_fs)
        c.setFillColorRGB(*_hex_to_rgb("#666666"))

        # Left: barcode short
        bc_w = _str_width(barcode_short, self.MAIN_FONT, bottom_fs)
        bc_x = tx + PAD + 2  # slight inset from left
        bc_text_y = bottom_y + (bottom_zone_h - bottom_fs) / 2
        c.drawString(bc_x, bc_text_y, barcode_short)

        # Right: date
        date_w = _str_width(date_str, self.MAIN_FONT, bottom_fs)
        date_x = tx + PAD + inner_w - date_w - 2  # slight inset from right
        c.drawString(date_x, bc_text_y, date_str)
```

- [ ] **Step 3: Verify method signature unchanged**

Confirm: method signature matches original (same parameters, return type None)

- [ ] **Step 4: Test by running Streamlit app**

Run: `streamlit run app.py`

Test steps:
1. Go to Price Tag Generator page
2. Select "Mini (55mm × 25mm)" from size dropdown
3. Add a test item with barcode, name, HET
4. Click "Generate PDF"
5. Download and view PDF - verify:
   - Name appears at top
   - Price appears in middle (big)
   - Bottom left shows last 6 digits of barcode
   - Bottom right shows date
   - No barcode graphic
   - Layout is clean, not "humongous"

- [ ] **Step 5: Commit changes**

```bash
git add logic/price_tag_service.py
git commit -m "refactor: redesign mini tag layout (55x25mm) to vertical name/price/code/date"
```

---

## Spec Coverage Check

| Requirement | Task |
|-------------|------|
| Vertical layout (name/price/code/date) | Task 1 |
| No barcode graphic | Task 1 |
| Discount shows only final price (big) | Task 1 |
| 55mm × 25mm size maintained | Task 1 (uses existing preset) |
| Clean, compact layout | Task 1 |

**No placeholders found.**
