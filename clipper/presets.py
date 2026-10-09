"""Preset gaya satu klik."""
from __future__ import annotations

PRESETS = {
    "CapCut Klasik": {},   # nilai bawaan Style
    "Podcast Viral": {
        "layout": "face", "sub_font": "Lilita One", "sub_size": 66, "sub_anim": "emphasis",
        "sub_uppercase": False, "sub_max_words": 5, "sub_fill": "#FFFFFF", "sub_active": "#FFE600",
        "sub_inner": "#000000", "sub_inner_w": 6, "sub_outer_w": 0, "sub_pos": [1, 3], "sub_dy": -0.08,
        "fx_shots": True, "fx_punch": False, "fx_slowzoom": False, "fx_progress": False, "fx_grade": True,
        "hook_style": "yellow", "hook_pos": [1, 0],
    },
    "Karaoke Neon": {
        "sub_font": "Poppins ExtraBold", "sub_anim": "karaoke", "sub_uppercase": True, "sub_max_words": 3,
        "sub_box": "#FF2D55", "sub_inner_w": 5, "sub_outer_w": 8, "sub_outer": "#6A1BFF", "sub_dy": 0.0,
        "fx_shots": False, "fx_punch": True, "fx_slowzoom": True,
    },
}
