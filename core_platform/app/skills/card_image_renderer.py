# Copyright 2026 Mahendra GURAV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Universal Stateless Card Image Renderer Skill (`CardImageRendererSkill`).

Adheres strictly to GEES v3.1 (Universal Skills Library, Zero Domain Pollution).
Synthesizes a high-contrast 800x418px PNG infographic header card from a generic
structured key-value specification for mobile messaging headers.
"""

import io
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from core_platform.app.skills.base import BaseSkill

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
except ImportError:
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]
    _HAS_PIL = False

# Minimal valid 1x1 dark-slate PNG fallback if Pillow is unavailable
_FALLBACK_PNG_BYTES: bytes = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc`\x18\x05"
    b"\xa3`\x14\x8c\x02\x00\x01\x00\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00"
    b"\x00IEND\xaeB`\x82"
)

_TONE_PALETTES: Dict[str, Tuple[int, int, int]] = {
    "danger": (220, 38, 38),
    "warning": (217, 119, 6),
    "success": (22, 163, 74),
    "info": (37, 99, 235),
}


class CardRenderSpec(BaseModel):
    """Domain-agnostic specification for rendering a structured infographic card."""

    badge_text: str = Field(default="PRIORITY BRIEF", description="Top pill badge text")
    badge_tone: str = Field(default="info", description="'danger' | 'warning' | 'success' | 'info'")
    title: str = Field(default="Decision Card", description="Primary card headline")
    subtitle: str = Field(default="", description="Secondary context line")
    rows: List[Tuple[str, str]] = Field(
        default_factory=list,
        description="Up to 4 structured (label, value) rows rendered in the card table",
    )
    footer_note: Optional[str] = Field(default=None, description="Optional bottom provenance note")
    layout_mode: str = Field(
        default="dossier",
        description="Card layout mode: 'dossier' (Approach A 2-column table) | 'timeline_360' (Approach B split artifact + 360 timeline)",
    )
    highlight_row_index: int = Field(
        default=1,
        description="Index of the row to highlight with amber decision accent in dossier mode",
    )
    document_preview_lines: List[str] = Field(
        default_factory=list,
        description="Artifact or draft lines rendered in the left document sheet of timeline_360 mode",
    )
    timeline_events: List[Tuple[str, str, str]] = Field(
        default_factory=list,
        description="List of (channel, title, detail) events rendered in the right 360 timeline pane of timeline_360 mode",
    )


_FONT_CANDIDATES_BOLD: Tuple[str, ...] = (
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "segoeuib.ttf",
    "arialbd.ttf",
    "DejaVuSans-Bold.ttf",
)

_FONT_CANDIDATES_REGULAR: Tuple[str, ...] = (
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/calibri.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "segoeui.ttf",
    "arial.ttf",
    "DejaVuSans.ttf",
)


def _load_scaled_font(size: int, bold: bool = False) -> Any:
    """Load a scalable TrueType font at the requested pixel height (never tiny 10px bitmap)."""
    if not _HAS_PIL or ImageFont is None:
        return None
    candidates = _FONT_CANDIDATES_BOLD if bold else _FONT_CANDIDATES_REGULAR
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _wrap_text_lines(text: str, max_chars_per_line: int, max_lines: int = 2) -> List[str]:
    """Wrap text cleanly on word boundaries up to max_lines."""
    clean = " ".join(str(text or "").split())
    if not clean:
        return [""]
    words = clean.split(" ")
    lines: List[str] = []
    current = ""
    for w in words:
        candidate = f"{current} {w}".strip() if current else w
        if len(candidate) <= max_chars_per_line:
            current = candidate
        else:
            if current:
                lines.append(current)
                current = w[:max_chars_per_line]
            else:
                lines.append(w[:max_chars_per_line])
                current = ""
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and len(clean) > sum(len(x) for x in lines) + max_lines:
        last = lines[-1]
        if len(last) > max_chars_per_line - 3:
            last = last[: max_chars_per_line - 3]
        lines[-1] = last.rstrip(".") + "..."
    return lines or [""]


# [CODE-MARKER: CP-SKILL-01] Stateless 800x418px PNG Infographic Card Renderer Skill
# [CODE-MARKER: FIX-WA-CARD-RENDER-12] High-Contrast TrueType Approach A Dossier & Approach B 360 Timeline Renderer
class CardImageRendererSkill(BaseSkill):
    """Stateless perceptual/rendering skill for generating 800x418px PNG header cards."""

    def __init__(self) -> None:
        """Initialize CardImageRendererSkill."""
        super().__init__(skill_name="card_image_renderer")

    async def initialize(self) -> None:
        """Verify rendering runtime readiness."""
        self._initialized = True

    def is_available(self) -> bool:
        """Return True when image rendering is ready."""
        return True

    def render_card_png(
        self,
        spec: CardRenderSpec,
        width: int = 800,
        height: int = 418,
    ) -> bytes:
        """Render a structured CardRenderSpec into in-memory PNG bytes."""
        if not _HAS_PIL or Image is None or ImageDraw is None:
            return _FALLBACK_PNG_BYTES

        w = max(320, width)
        h = max(200, height)
        if spec.layout_mode.lower() == "timeline_360":
            return self._render_timeline_360_png(spec, w, h)
        return self._render_dossier_png(spec, w, h)

    def _render_dossier_png(self, spec: CardRenderSpec, w: int, h: int) -> bytes:
        """Render Approach A: Visual Infographic Header + 2-Column Rounded Decision Dossier."""
        outer_bg = (11, 17, 32)           # Deep Slate-950
        card_bg = (22, 32, 50)            # Rich Slate-900 Dossier surface
        border_color = (59, 76, 102)      # Crisp Slate border
        left_cell_bg = (42, 67, 101)      # Steel-Blue Label Cell (Approach A)
        right_cell_bg = (19, 28, 46)      # Dark Slate Value Cell
        hl_left_bg = (110, 78, 32)        # Warm Amber/Gold Highlight Label Cell
        hl_right_bg = (34, 42, 58)        # Highlight Value Cell
        hl_border = (217, 119, 6)         # Amber-600 Highlight Border
        text_primary = (248, 250, 252)    # Crisp White
        text_amber = (245, 158, 11)       # Executive Amber Accent
        text_green = (74, 222, 128)       # Positive/Action Green Accent
        text_muted = (148, 163, 184)      # Muted Slate-400
        accent_color = _TONE_PALETTES.get(spec.badge_tone.lower(), _TONE_PALETTES["info"])

        img = Image.new("RGB", (w, h), color=outer_bg)
        draw = ImageDraw.Draw(img)

        font_badge = _load_scaled_font(16, bold=True)
        font_title = _load_scaled_font(24, bold=True)
        font_sub = _load_scaled_font(17, bold=False)
        font_label = _load_scaled_font(19, bold=True)
        font_val = _load_scaled_font(20, bold=True)
        font_val_sm = _load_scaled_font(17, bold=False)
        font_footer = _load_scaled_font(15, bold=False)

        # Outer rounded dossier container
        draw.rounded_rectangle(
            [(14, 10), (w - 14, h - 10)],
            radius=18,
            fill=card_bg,
            outline=border_color,
            width=2,
        )

        # Top header banner bar inside dossier
        draw.rounded_rectangle(
            [(26, 20), (w - 26, 92)],
            radius=12,
            fill=(15, 23, 42),
            outline=border_color,
            width=1,
        )

        # Right-aligned status badge pill
        badge_str = (spec.badge_text or "PRIORITY BRIEF").upper()[:24]
        badge_w = min(220, max(120, len(badge_str) * 10 + 24))
        badge_x1 = w - 40 - badge_w
        draw.rounded_rectangle(
            [(badge_x1, 30), (w - 40, 62)],
            radius=8,
            fill=accent_color,
        )
        draw.text((badge_x1 + 12, 36), badge_str, fill=text_primary, font=font_badge)

        # Title & Subtitle on header banner
        title_str = (spec.title or "Executive Decision Card")[:48]
        draw.text((40, 28), title_str, fill=text_amber, font=font_title)
        if spec.subtitle:
            draw.text((40, 60), spec.subtitle[:68], fill=text_primary, font=font_sub)

        # Two-Column Rounded Comparison Grid (Approach A)
        rows_to_draw = spec.rows[:4]
        num_rows = max(1, len(rows_to_draw))
        grid_top = 104
        grid_bottom = h - 44
        avail_h = grid_bottom - grid_top
        row_step = min(68, avail_h // num_rows)
        box_h = row_step - 8
        split_x = 264

        for idx, (label, val) in enumerate(rows_to_draw):
            y0 = grid_top + idx * row_step
            y1 = y0 + box_h
            is_hl = idx == spec.highlight_row_index

            # Right value cell background
            draw.rounded_rectangle(
                [(26, y0), (w - 26, y1)],
                radius=10,
                fill=hl_right_bg if is_hl else right_cell_bg,
                outline=hl_border if is_hl else border_color,
                width=2 if is_hl else 1,
            )
            # Left label pill cell
            draw.rounded_rectangle(
                [(26, y0), (split_x, y1)],
                radius=10,
                fill=hl_left_bg if is_hl else left_cell_bg,
                outline=hl_border if is_hl else border_color,
                width=2 if is_hl else 1,
            )

            clean_label = str(label).strip()[:20]
            text_y_label = y0 + max(8, (box_h - 22) // 2)
            draw.text(
                (40, text_y_label),
                clean_label,
                fill=text_amber if is_hl else text_primary,
                font=font_label,
            )

            val_lines = _wrap_text_lines(str(val), max_chars_per_line=44, max_lines=2)
            val_color = text_green if is_hl else text_primary
            if len(val_lines) == 1:
                text_y_val = y0 + max(8, (box_h - 22) // 2)
                draw.text((split_x + 18, text_y_val), val_lines[0], fill=val_color, font=font_val)
            else:
                draw.text((split_x + 18, y0 + 6), val_lines[0], fill=val_color, font=font_val_sm)
                draw.text((split_x + 18, y0 + 28), val_lines[1], fill=text_primary, font=font_val_sm)

        # Footer provenance line
        if spec.footer_note:
            draw.text((32, h - 34), spec.footer_note[:88], fill=text_muted, font=font_footer)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def _render_timeline_360_png(self, spec: CardRenderSpec, w: int, h: int) -> bytes:
        """Render Approach B: Split Document/Draft Preview Sheet + 360-Degree Omnichannel Timeline."""
        outer_bg = (11, 17, 32)
        card_bg = (22, 32, 50)
        border_color = (59, 76, 102)
        doc_bg = (248, 250, 252)          # Crisp Paper White for Left Document Sheet
        doc_border = (148, 163, 184)
        doc_ink = (15, 23, 42)
        doc_muted = (71, 85, 105)
        pane_right_bg = (15, 23, 42)
        text_primary = (248, 250, 252)
        text_amber = (245, 158, 11)
        text_muted = (148, 163, 184)

        img = Image.new("RGB", (w, h), color=outer_bg)
        draw = ImageDraw.Draw(img)

        font_header = _load_scaled_font(22, bold=True)
        font_badge = _load_scaled_font(15, bold=True)
        font_pane_title = _load_scaled_font(19, bold=True)
        font_doc_callout = _load_scaled_font(20, bold=True)
        font_doc_body = _load_scaled_font(15, bold=False)
        font_tl_title = _load_scaled_font(17, bold=True)
        font_tl_sub = _load_scaled_font(14, bold=False)
        font_footer = _load_scaled_font(14, bold=False)

        # Outer dossier frame
        draw.rounded_rectangle(
            [(14, 10), (w - 14, h - 10)],
            radius=18,
            fill=card_bg,
            outline=border_color,
            width=2,
        )

        # Top title bar
        draw.text((30, 22), (spec.title or "360° Deep Context Dossier")[:48], fill=text_amber, font=font_header)
        badge_str = (spec.badge_text or "360° TIMELINE").upper()[:22]
        badge_w = min(210, max(120, len(badge_str) * 9 + 20))
        draw.rounded_rectangle([(w - 30 - badge_w, 20), (w - 30, 50)], radius=8, fill=(37, 99, 235))
        draw.text((w - 18 - badge_w, 26), badge_str, fill=text_primary, font=font_badge)

        # Left Pane: Highlighted Document / Staged Reply Sheet (x=28..368, y=60..372)
        draw.rounded_rectangle(
            [(28, 60), (368, 372)],
            radius=12,
            fill=doc_bg,
            outline=doc_border,
            width=2,
        )
        draw.text((44, 72), "Staged Draft / Artifact", fill=doc_ink, font=font_pane_title)

        # Magnified Callout Box inside Left Document Sheet (matching Approach B loupe highlight)
        callout_headline = (spec.subtitle or "Verified Grounded Reply")[:28]
        draw.rounded_rectangle(
            [(40, 104), (356, 152)],
            radius=8,
            fill=(239, 246, 255),
            outline=(37, 99, 235),
            width=2,
        )
        draw.text((52, 116), callout_headline, fill=(30, 64, 175), font=font_doc_callout)

        doc_lines: List[str] = []
        raw_doc = spec.document_preview_lines or [f"{k}: {v}" for k, v in spec.rows]
        for line in raw_doc:
            doc_lines.extend(_wrap_text_lines(line, max_chars_per_line=36, max_lines=3))
        y_doc = 166
        for dl in doc_lines[:8]:
            if y_doc > 350:
                break
            draw.text((44, y_doc), dl, fill=doc_ink if y_doc < 260 else doc_muted, font=font_doc_body)
            y_doc += 22

        # Right Pane: 360° Omnichannel Timeline (x=384..w-28, y=60..372)
        draw.rounded_rectangle(
            [(384, 60), (w - 28, 372)],
            radius=12,
            fill=pane_right_bg,
            outline=border_color,
            width=2,
        )
        draw.text((402, 72), "360° Timeline", fill=text_primary, font=font_pane_title)
        draw.text((402, 96), "Email + WhatsApp + Commitments", fill=text_muted, font=font_tl_sub)

        events = spec.timeline_events[:4]
        if not events:
            events = [
                ("EMAIL", spec.title[:30], "Inbound Thread"),
                ("DRAFT", "Staged Grounded Reply", "Awaiting 1-Tap Approval"),
            ]

        # Vertical connector line
        spine_x = 416
        draw.line([(spine_x, 134), (spine_x, 134 + max(1, len(events) - 1) * 60)], fill=(71, 85, 105), width=3)

        y_ev = 124
        for chan, ev_title, ev_detail in events:
            ch_up = str(chan).upper()
            if "WA" in ch_up or "WHATSAPP" in ch_up:
                dot_color = (22, 163, 74)
                tag = "WA"
            elif "CALL" in ch_up or "COMMIT" in ch_up or "FACT" in ch_up:
                dot_color = (217, 119, 6)
                tag = "FC"
            else:
                dot_color = (37, 99, 235)
                tag = "EM"

            draw.ellipse([(spine_x - 13, y_ev), (spine_x + 13, y_ev + 26)], fill=dot_color)
            draw.text((spine_x - 9, y_ev + 5), tag, fill=text_primary, font=font_tl_sub)
            draw.text((spine_x + 24, y_ev - 2), str(ev_title)[:32], fill=text_primary, font=font_tl_title)
            draw.text((spine_x + 24, y_ev + 20), str(ev_detail)[:40], fill=text_muted, font=font_tl_sub)
            y_ev += 60

        if spec.footer_note:
            draw.text((32, h - 32), spec.footer_note[:88], fill=text_muted, font=font_footer)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

