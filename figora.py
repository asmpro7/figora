"""
Figora - Figure Assembly Tool for Publication
=======================================================

Arrange multiple photos/micrographs/panels into a single labeled grid
figure for manuscripts, posters, and presentations.

Requirements:
    pip install customtkinter pillow

Run:
    python figora.py

Keyboard shortcuts:
    Ctrl+O        Add photos
    Ctrl+S        Save figure
    Ctrl+=/Ctrl+-  Zoom preview in/out
    Ctrl+0        Reset preview zoom to 100%
    Double-click preview  Zoom to fit

Developed by Ahmed Abdelmageed (https://github.com/asmpro7).
Builds on an original single-file version by the same author.
"""

import json
import math
import os
import subprocess
import sys
import traceback
import webbrowser

import customtkinter
from tkinter import filedialog, messagebox, colorchooser, Canvas
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageTk

# Pillow renamed its resampling constants at v9.1; support both old and new.
try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
except AttributeError:  # Pillow < 9.1
    RESAMPLE_LANCZOS = Image.LANCZOS


# ---------------------------------------------------------------------------
# Font resolution helpers
# ---------------------------------------------------------------------------
# PIL's ImageFont.truetype() needs a real font *file*, not a display name
# like "Times New Roman" - passing a bare display name fails silently on
# every OS and falls back to a tiny, non-scalable bitmap font. This table
# maps common display names to the actual file names used on Windows /
# macOS / Linux so a real, scalable font can usually be found without the
# user having to hunt for a .ttf file themselves.
FONT_CANDIDATES = {
    "Arial": [
        "arial.ttf", "Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "LiberationSans-Regular.ttf",
    ],
    "Arial Bold": [
        "arialbd.ttf", "Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "LiberationSans-Bold.ttf",
    ],
    "Times New Roman": [
        "times.ttf", "Times New Roman.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        "LiberationSerif-Regular.ttf",
    ],
    "Times New Roman Bold": [
        "timesbd.ttf", "Times New Roman Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "LiberationSerif-Bold.ttf",
    ],
    "Helvetica": [
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "arial.ttf",
    ],
    "Helvetica Bold": [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "arialbd.ttf",
    ],
    "Calibri": ["calibri.ttf", "Calibri.ttf"],
    "Calibri Bold": ["calibrib.ttf", "Calibri Bold.ttf"],
    "Courier New": [
        "cour.ttf", "Courier New.ttf",
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ],
    "Courier New Bold": [
        "courbd.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
    ],
    "Georgia": ["georgia.ttf", "Georgia.ttf"],
    "Georgia Bold": ["georgiab.ttf"],
    "Verdana": ["verdana.ttf", "Verdana.ttf"],
    "Verdana Bold": ["verdanab.ttf"],
    "DejaVu Sans": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf",
    ],
    "DejaVu Sans Bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf",
    ],
    "DejaVu Serif": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "DejaVuSerif.ttf",
    ],
}

FONT_FAMILY_CHOICES = [
    "Arial", "Times New Roman", "Helvetica", "Calibri",
    "Courier New", "Georgia", "Verdana", "DejaVu Sans", "DejaVu Serif",
]

# Directories to search, as a last resort, for ANY real scalable font file
# when neither a custom font file nor a known-family match can be found.
_SYSTEM_FONT_DIRS = [
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
    "/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts",
    os.path.expanduser("~/Library/Fonts"),
    "/usr/share/fonts", "/usr/local/share/fonts",
    os.path.expanduser("~/.fonts"), os.path.expanduser("~/.local/share/fonts"),
]
_PREFERRED_FALLBACK_MARKERS = [
    "dejavusans", "notosans-regular", "notosans", "arial",
    "liberationsans", "helvetica", "verdana", "segoeui",
]


def resolve_font(display_name, size, bold=False):
    """Try hard to find a real TrueType font file for a display name."""
    keys = []
    if bold:
        keys.append(f"{display_name} Bold")
    keys.append(display_name)

    candidates = []
    for k in keys:
        candidates.extend(FONT_CANDIDATES.get(k, []))
    candidates.append(display_name)
    candidates.append(display_name.replace(" ", "") + ".ttf")

    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return None


def find_any_system_font(bold=False):
    """Last resort: locate any real .ttf/.otf file anywhere on this system."""
    markers = list(_PREFERRED_FALLBACK_MARKERS)
    if bold:
        markers = [m + "-bold" for m in markers] + \
            [m + "bd" for m in markers] + markers

    first_found = None
    for d in _SYSTEM_FONT_DIRS:
        if not d or not os.path.isdir(d):
            continue
        try:
            for walkroot, _dirs, files in os.walk(d):
                for fn in files:
                    if not fn.lower().endswith((".ttf", ".otf")):
                        continue
                    full = os.path.join(walkroot, fn)
                    if first_found is None:
                        first_found = full
                    lower = fn.lower()
                    if any(marker in lower for marker in markers):
                        return full
        except OSError:
            continue
    return first_found


def load_fallback_font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------
class FigoraApp:
    VERSION = "1.0.1"

    CELL_SIZE_MODES = ["Fit to largest photo",
                       "Fit to smallest photo", "Custom size"]
    LABEL_STYLES = ["None", "Uppercase (A, B, C\u2026)", "Lowercase (a, b, c\u2026)",
                    "Numbers (1, 2, 3\u2026)", "Custom list"]
    LABEL_FORMATS = ["A", "A.", "(A)", "A)"]
    LABEL_POSITIONS = ["Above panel", "Top-left (inside)", "Top-right (inside)",
                       "Bottom-left (inside)", "Bottom-right (inside)"]
    OUTPUT_FORMATS = ["PNG", "TIFF", "JPEG", "PDF"]  # PNG first = default
    CAPTION_POSITIONS = ["Bottom", "Top"]
    SCALE_BAR_POSITIONS = ["Bottom-right",
                           "Bottom-left", "Top-right", "Top-left"]
    PANEL_ORDERS = ["By row", "By column"]

    PREVIEW_BASE_DIM = 1000   # px cap used when composing the cached preview image
    ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 25, 300, 10   # percent

    def __init__(self, root):
        self.root = root
        self.root.title(f"Figora (v{self.VERSION})")
        self.root.geometry("1380x900")
        self.root.minsize(1060, 680)
        self._set_app_icon()

        # ---- state ----
        self.images = []          # list[PIL.Image.Image]
        self.image_paths = []     # list[str], parallel to self.images
        self._thumb_refs = []     # keep CTkImage refs alive for the list UI
        self._preview_after_id = None
        self.font_resolution_status = ""

        # preview viewer state (view-only, not saved with the project)
        self._preview_base_image = None     # cached composed PIL image
        self._preview_photo_image = None    # currently displayed ImageTk.PhotoImage
        self.preview_zoom = 1.0             # 1.0 == 100%

        self._set_defaults()

        # ---- layout: sidebar (scrollable) + preview area ----
        self.sidebar = customtkinter.CTkScrollableFrame(
            root, width=380, label_text="Controls")
        self.sidebar.pack(side="left", fill="y", padx=(10, 5), pady=10)

        self.preview_frame = customtkinter.CTkFrame(root)
        self.preview_frame.pack(side="right", fill="both",
                                expand=True, padx=(5, 10), pady=10)

        self._build_project_section()
        self._build_images_section()
        self._build_grid_section()
        self._build_background_border_section()
        self._build_adjustments_section()
        self._build_labels_section()
        self._build_caption_section()
        self._build_scale_bar_section()
        self._build_output_section()

        self.about_button = customtkinter.CTkButton(
            self.sidebar, text="About", command=self.show_about)
        self.about_button.pack(pady=(15, 10), fill="x")

        self._build_preview_area()

        self.root.bind("<Control-o>", lambda e: self.add_photos())
        self.root.bind("<Control-s>", lambda e: self.save_figure())
        self.root.bind("<Control-equal>", lambda e: self.zoom_in())
        self.root.bind("<Control-plus>", lambda e: self.zoom_in())
        self.root.bind("<Control-minus>", lambda e: self.zoom_out())
        self.root.bind("<Control-0>", lambda e: self.zoom_reset())

        self.refresh_image_list_ui()
        self.update_preview()

    def _set_defaults(self):
        """Set every FIGURE setting to its default value (used at startup and
        by 'Reset to Defaults'). Does not touch loaded photos or view state
        (zoom) since those aren't part of the figure itself."""
        self.rows = 2
        self.cols = 2
        self.auto_rows = True
        self.panel_order = self.PANEL_ORDERS[0]
        self.h_spacing = 20
        self.v_spacing = 20
        self.margin = 0
        self.cell_size_mode = self.CELL_SIZE_MODES[0]
        self.custom_cell_width = ""
        self.custom_cell_height = ""

        self.label_style = self.LABEL_STYLES[1]
        self.label_format = self.LABEL_FORMATS[0]
        self.label_position = self.LABEL_POSITIONS[0]
        self.custom_labels_text = ""
        self.font_family = "Times New Roman"
        self.font_bold = False
        self.font_size = 32
        self.font_color = (0, 0, 0)
        self.custom_font_path = None

        self.bg_color = (255, 255, 255)
        self.transparent_bg = False

        self.panel_border_enabled = False
        self.panel_border_width = 3
        self.panel_border_color = (0, 0, 0)

        self.grayscale_enabled = False
        self.auto_contrast_enabled = False

        self.figure_caption_text = ""
        self.figure_caption_position = self.CAPTION_POSITIONS[0]
        self.caption_font_size = 32
        self.caption_color = (0, 0, 0)

        self.scale_bar_enabled = False
        self.scale_bar_length_px = 100
        self.scale_bar_label = "100 \u00b5m"
        self.scale_bar_position = self.SCALE_BAR_POSITIONS[0]
        self.scale_bar_color = (255, 255, 255)
        self.scale_bar_thickness = 6

        self.output_format = self.OUTPUT_FORMATS[0]   # PNG
        self.dpi_text = "300"
        self.target_width_text = ""

    # ------------------------------------------------------------------
    # Collapsible section helper
    # ------------------------------------------------------------------
    def _add_collapsible_section(self, title, expanded=True):
        """Create an accordion-style settings section in the sidebar and
        return its body frame - add this section's controls to the body,
        not directly to self.sidebar. `expanded` sets the default state:
        commonly-needed sections should default to True, more specialized
        ones to False, so the sidebar isn't overwhelming at first glance."""
        outer = customtkinter.CTkFrame(self.sidebar, fg_color="transparent")
        outer.pack(fill="x", pady=(10, 0))

        state = {"expanded": expanded}
        header = customtkinter.CTkButton(
            outer, text="", anchor="w", height=30,
            fg_color=("gray80", "gray24"), hover_color=("gray72", "gray30"),
            text_color=("gray10", "gray92"),
            font=customtkinter.CTkFont(weight="bold", size=13))
        header.pack(fill="x")

        body = customtkinter.CTkFrame(outer, fg_color="transparent")

        def set_header_text():
            arrow = "\u25be" if state["expanded"] else "\u25b8"
            header.configure(text=f"  {arrow}  {title}")

        def toggle():
            state["expanded"] = not state["expanded"]
            if state["expanded"]:
                body.pack(fill="x", padx=(6, 0), pady=(6, 2))
            else:
                body.pack_forget()
            set_header_text()

        header.configure(command=toggle)
        set_header_text()
        if expanded:
            body.pack(fill="x", padx=(6, 0), pady=(6, 2))

        return body

    # ------------------------------------------------------------------
    # App icon
    # ------------------------------------------------------------------
    @staticmethod
    def _resource_dir():
        """Directory to look for bundled assets (icon, logo) in. When
        frozen by PyInstaller with --add-data, bundled files are extracted
        at runtime to sys._MEIPASS, not to wherever the original script
        lived - this returns the right directory for either case."""
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return sys._MEIPASS
        return os.path.dirname(os.path.abspath(__file__))

    def _set_app_icon(self):
        """Use the Figora logo as the window/taskbar/dock icon instead of
        the default Tk icon. Looks for figora.ico and figora-logo.png in
        _resource_dir() - next to this script when run from source, or in
        PyInstaller's extracted bundle directory when run as a onefile
        executable built with --add-data "figora.ico:." --add-data
        "figora-logo.png:. ". Windows gets the native multi-resolution
        .ico via iconbitmap (best quality for the taskbar); macOS/Linux
        get the PNG via iconphoto, which is what those platforms' window
        managers actually expect. Every step is wrapped defensively - a
        missing or unreadable icon file should never prevent the app from
        starting."""
        base_dir = self._resource_dir()
        ico_path = os.path.join(base_dir, "figora.ico")
        png_path = os.path.join(base_dir, "figora-logo.png")

        if sys.platform == "win32" and os.path.isfile(ico_path):
            try:
                self.root.iconbitmap(ico_path)
                return
            except Exception:
                pass  # fall through and try the PNG instead

        for path in (png_path, ico_path):
            if not os.path.isfile(path):
                continue
            try:
                icon_img = Image.open(path).convert("RGBA")
                icon_img.thumbnail((256, 256), RESAMPLE_LANCZOS)
                # keep a reference alive for the life of the app - once the
                # last Python reference to a PhotoImage is dropped, Tk
                # deletes the underlying image and the icon can vanish
                self._app_icon_photo = ImageTk.PhotoImage(icon_img)
                self.root.iconphoto(True, self._app_icon_photo)
                return
            except Exception:
                continue
        # neither file is present/readable - keep Tk's default icon rather
        # than raise, since a missing icon shouldn't block the app opening

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------
    def _build_project_section(self):
        body = self._add_collapsible_section("Project", expanded=False)
        row1 = customtkinter.CTkFrame(body, fg_color="transparent")
        row1.pack(fill="x", pady=2)
        customtkinter.CTkButton(row1, text="Load Project\u2026", command=self.load_project).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        customtkinter.CTkButton(row1, text="Save Project\u2026", command=self.save_project).pack(
            side="left", expand=True, fill="x", padx=(4, 0))
        customtkinter.CTkButton(
            body, text="Reset All Settings to Defaults",
            fg_color="transparent", border_width=1, command=self.reset_to_defaults
        ).pack(fill="x", pady=(4, 2))

    def _build_images_section(self):
        body = self._add_collapsible_section("Photos", expanded=True)
        btn_row = customtkinter.CTkFrame(body, fg_color="transparent")
        btn_row.pack(fill="x", pady=2)
        customtkinter.CTkButton(btn_row, text="Add Photos", command=self.add_photos).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        customtkinter.CTkButton(btn_row, text="Clear All", fg_color="#8b2c2c",
                                hover_color="#6e2222", command=self.clear_all).pack(
            side="left", expand=True, fill="x", padx=(4, 0))

        self.list_container = customtkinter.CTkFrame(
            body, fg_color="transparent")
        self.list_container.pack(fill="x", pady=(6, 2))

    def _build_grid_section(self):
        body = self._add_collapsible_section("Grid & Spacing", expanded=True)

        self.auto_rows_checkbox = customtkinter.CTkCheckBox(
            body, text="Auto-fit rows to number of photos",
            command=self._on_auto_rows_toggle)
        self.auto_rows_checkbox.select()
        self.auto_rows_checkbox.pack(anchor="w", pady=(0, 6))

        self.rows_slider, self.rows_value_label = self._build_slider_row(
            body, "Rows", 1, 10, self.rows, 9, self._on_rows_slider)
        self.rows_slider.configure(state="disabled")

        self.cols_slider, self.cols_value_label = self._build_slider_row(
            body, "Columns", 1, 10, self.cols, 9, self._on_cols_slider)

        customtkinter.CTkLabel(body, text="Fill order").pack(
            anchor="w", pady=(8, 2))
        self.panel_order_menu = customtkinter.CTkOptionMenu(
            body, values=self.PANEL_ORDERS, command=self._on_panel_order_change)
        self.panel_order_menu.set(self.panel_order)
        self.panel_order_menu.pack(fill="x", pady=(0, 2))
        customtkinter.CTkLabel(
            body, text="Row: left-to-right, then down. Column: top-to-bottom, then across.",
            text_color="gray60", wraplength=330, justify="left"
        ).pack(anchor="w", pady=(0, 4))

        self.hspacing_slider, self.hspacing_value_label = self._build_slider_row(
            body, "Horizontal spacing (px)", 0, 100, self.h_spacing, 100, self._on_hspacing_slider)

        self.vspacing_slider, self.vspacing_value_label = self._build_slider_row(
            body, "Vertical spacing (px)", 0, 100, self.v_spacing, 100, self._on_vspacing_slider)

        self.margin_slider, self.margin_value_label = self._build_slider_row(
            body, "Outer margin (px)", 0, 100, self.margin, 100, self._on_margin_slider)

        customtkinter.CTkLabel(body, text="Panel size").pack(
            anchor="w", pady=(8, 2))
        self.cell_size_menu = customtkinter.CTkOptionMenu(
            body, values=self.CELL_SIZE_MODES, command=self._on_cell_size_mode_change)
        self.cell_size_menu.set(self.cell_size_mode)
        self.cell_size_menu.pack(fill="x", pady=(0, 2))

        self.custom_size_frame = customtkinter.CTkFrame(
            body, fg_color="transparent")
        self.custom_width_entry = customtkinter.CTkEntry(
            self.custom_size_frame, placeholder_text="width px")
        self.custom_width_entry.pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        self.custom_width_entry.bind(
            "<KeyRelease>", self.request_preview_update)
        self.custom_height_entry = customtkinter.CTkEntry(
            self.custom_size_frame, placeholder_text="height px")
        self.custom_height_entry.pack(
            side="left", expand=True, fill="x", padx=(4, 0))
        self.custom_height_entry.bind(
            "<KeyRelease>", self.request_preview_update)
        # custom_size_frame is packed/unpacked on demand by _on_cell_size_mode_change

    def _build_background_border_section(self):
        body = self._add_collapsible_section(
            "Background & Border", expanded=False)

        customtkinter.CTkLabel(body, text="Background").pack(
            anchor="w", pady=(0, 2))
        bg_row = customtkinter.CTkFrame(body, fg_color="transparent")
        bg_row.pack(fill="x")
        self.bg_swatch = customtkinter.CTkButton(
            bg_row, text="Color\u2026", width=90, command=self.choose_bg_color,
            fg_color=self._rgb_to_hex(self.bg_color),
            hover_color=self._rgb_to_hex(self.bg_color),
            text_color=self._contrast_text_color(self.bg_color))
        self.bg_swatch.pack(side="left", padx=(0, 8))
        self.transparent_checkbox = customtkinter.CTkCheckBox(
            bg_row, text="Transparent (PNG only)", command=self._on_transparent_toggle)
        self.transparent_checkbox.pack(side="left")

        customtkinter.CTkLabel(body, text="Panel border").pack(
            anchor="w", pady=(10, 2))
        self.border_checkbox = customtkinter.CTkCheckBox(
            body, text="Draw a border around each panel",
            command=self._on_border_toggle)
        self.border_checkbox.pack(anchor="w", pady=(0, 4))
        self.border_width_slider, self.border_width_value_label = self._build_slider_row(
            body, "Border width (px)", 1, 20, self.panel_border_width, 19, self._on_border_width_slider)
        self.border_width_slider.configure(state="disabled")
        border_color_row = customtkinter.CTkFrame(body, fg_color="transparent")
        border_color_row.pack(fill="x", pady=(2, 2))
        customtkinter.CTkLabel(
            border_color_row, text="Border color").pack(side="left")
        self.border_color_swatch = customtkinter.CTkButton(
            border_color_row, text="Color\u2026", width=90, command=self.choose_border_color,
            fg_color=self._rgb_to_hex(self.panel_border_color),
            hover_color=self._rgb_to_hex(self.panel_border_color),
            text_color=self._contrast_text_color(self.panel_border_color))
        self.border_color_swatch.pack(side="right")

    def _build_adjustments_section(self):
        body = self._add_collapsible_section("Adjustments", expanded=False)
        self.grayscale_checkbox = customtkinter.CTkCheckBox(
            body, text="Convert photos to grayscale", command=self._on_grayscale_toggle)
        self.grayscale_checkbox.pack(anchor="w", pady=(0, 2))
        self.auto_contrast_checkbox = customtkinter.CTkCheckBox(
            body, text="Auto-enhance contrast", command=self._on_auto_contrast_toggle)
        self.auto_contrast_checkbox.pack(anchor="w", pady=(0, 2))

    def _build_labels_section(self):
        body = self._add_collapsible_section("Panel Labels", expanded=True)

        customtkinter.CTkLabel(body, text="Style").pack(anchor="w")
        self.label_style_menu = customtkinter.CTkOptionMenu(
            body, values=self.LABEL_STYLES, command=self._on_label_style_change)
        self.label_style_menu.set(self.label_style)
        self.label_style_menu.pack(fill="x", pady=(0, 6))

        self.custom_labels_entry = customtkinter.CTkEntry(
            body, placeholder_text="e.g. A,B,C,D or 1,2,3,4")
        self.custom_labels_entry.bind(
            "<KeyRelease>", self.request_preview_update)
        # packed only when style == "Custom list"

        customtkinter.CTkLabel(body, text="Format").pack(anchor="w")
        self.label_format_menu = customtkinter.CTkOptionMenu(
            body, values=self.LABEL_FORMATS, command=self._on_label_format_change)
        self.label_format_menu.set(self.label_format)
        self.label_format_menu.pack(fill="x", pady=(0, 6))

        customtkinter.CTkLabel(body, text="Position").pack(anchor="w")
        self.label_position_menu = customtkinter.CTkOptionMenu(
            body, values=self.LABEL_POSITIONS, command=self._on_label_position_change)
        self.label_position_menu.set(self.label_position)
        self.label_position_menu.pack(fill="x", pady=(0, 6))

        customtkinter.CTkLabel(body, text="Font family").pack(anchor="w")
        self.font_family_menu = customtkinter.CTkOptionMenu(
            body, values=FONT_FAMILY_CHOICES, command=self._on_font_family_change)
        self.font_family_menu.set(self.font_family)
        self.font_family_menu.pack(fill="x", pady=(0, 4))

        font_file_row = customtkinter.CTkFrame(body, fg_color="transparent")
        font_file_row.pack(fill="x", pady=(0, 2))
        customtkinter.CTkButton(font_file_row, text="Browse font file\u2026", width=130,
                                command=self.browse_font_file).pack(side="left")
        customtkinter.CTkButton(font_file_row, text="Clear", width=50,
                                command=self.clear_custom_font).pack(side="left", padx=(4, 0))
        self.font_file_label = customtkinter.CTkLabel(
            body, text="(none \u2014 using dropdown font)", text_color="gray60",
            wraplength=330, justify="left")
        self.font_file_label.pack(anchor="w", pady=(0, 6))

        self.bold_checkbox = customtkinter.CTkCheckBox(
            body, text="Bold", command=self._on_bold_toggle)
        self.bold_checkbox.pack(anchor="w", pady=(0, 6))

        self.font_size_slider, self.font_size_value_label = self._build_slider_row(
            body, "Font size (px)", 8, 400, self.font_size, 392, self._on_font_size_slider)

        self.font_size_physical_label = customtkinter.CTkLabel(
            body, text="", text_color="gray60")
        self.font_size_physical_label.pack(anchor="w", pady=(0, 2))

        self.font_resolution_label = customtkinter.CTkLabel(
            body, text="", text_color="#d9a441", wraplength=330, justify="left")
        self.font_resolution_label.pack(anchor="w", pady=(0, 6))

        color_row = customtkinter.CTkFrame(body, fg_color="transparent")
        color_row.pack(fill="x", pady=(4, 2))
        customtkinter.CTkLabel(color_row, text="Label color").pack(side="left")
        self.font_color_swatch = customtkinter.CTkButton(
            color_row, text="Color\u2026", width=90, command=self.choose_font_color,
            fg_color=self._rgb_to_hex(self.font_color),
            hover_color=self._rgb_to_hex(self.font_color),
            text_color=self._contrast_text_color(self.font_color))
        self.font_color_swatch.pack(side="right")

    def _build_caption_section(self):
        body = self._add_collapsible_section("Figure Caption", expanded=False)
        self.caption_entry = customtkinter.CTkEntry(
            body, placeholder_text="Optional title/caption for the whole figure")
        self.caption_entry.bind("<KeyRelease>", self._on_caption_text_change)
        self.caption_entry.pack(fill="x", pady=(0, 6))

        customtkinter.CTkLabel(body, text="Position").pack(anchor="w")
        self.caption_position_menu = customtkinter.CTkOptionMenu(
            body, values=self.CAPTION_POSITIONS, command=self._on_caption_position_change)
        self.caption_position_menu.set(self.figure_caption_position)
        self.caption_position_menu.pack(fill="x", pady=(0, 6))

        self.caption_font_size_slider, self.caption_font_size_value_label = self._build_slider_row(
            body, "Caption font size (px)", 8, 400, self.caption_font_size, 392,
            self._on_caption_font_size_slider)

        caption_color_row = customtkinter.CTkFrame(
            body, fg_color="transparent")
        caption_color_row.pack(fill="x", pady=(4, 4))
        customtkinter.CTkLabel(
            caption_color_row, text="Caption color").pack(side="left")
        self.caption_color_swatch = customtkinter.CTkButton(
            caption_color_row, text="Color\u2026", width=90, command=self.choose_caption_color,
            fg_color=self._rgb_to_hex(self.caption_color),
            hover_color=self._rgb_to_hex(self.caption_color),
            text_color=self._contrast_text_color(self.caption_color))
        self.caption_color_swatch.pack(side="right")

        customtkinter.CTkLabel(
            body, text="Wraps to a new line automatically to stay within the figure "
                       "width. Uses the same font family as panel labels.",
            text_color="gray60", wraplength=330, justify="left"
        ).pack(anchor="w", pady=(4, 4))

    def _build_scale_bar_section(self):
        body = self._add_collapsible_section("Scale Bar", expanded=False)
        self.scale_bar_checkbox = customtkinter.CTkCheckBox(
            body, text="Add a scale bar to every panel",
            command=self._on_scale_bar_toggle)
        self.scale_bar_checkbox.pack(anchor="w", pady=(0, 4))

        customtkinter.CTkLabel(
            body,
            text="Length is in pixels of the ORIGINAL photo (not the output) \u2014 "
                 "use the pixel length that you know corresponds to your label, "
                 "e.g. from a microscope/camera calibration.",
            text_color="gray60", wraplength=330, justify="left"
        ).pack(anchor="w", pady=(0, 4))

        len_row = customtkinter.CTkFrame(body, fg_color="transparent")
        len_row.pack(fill="x", pady=(0, 4))
        customtkinter.CTkLabel(
            len_row, text="Length (source px)").pack(side="left")
        self.scale_bar_length_entry = customtkinter.CTkEntry(len_row, width=90)
        self.scale_bar_length_entry.insert(0, str(self.scale_bar_length_px))
        self.scale_bar_length_entry.bind(
            "<KeyRelease>", self._on_scale_bar_length_change)
        self.scale_bar_length_entry.pack(side="right")

        self.scale_bar_label_entry = customtkinter.CTkEntry(
            body, placeholder_text="Label text, e.g. 100 \u00b5m")
        self.scale_bar_label_entry.insert(0, self.scale_bar_label)
        self.scale_bar_label_entry.bind(
            "<KeyRelease>", self._on_scale_bar_label_change)
        self.scale_bar_label_entry.pack(fill="x", pady=(0, 4))

        customtkinter.CTkLabel(body, text="Position").pack(anchor="w")
        self.scale_bar_position_menu = customtkinter.CTkOptionMenu(
            body, values=self.SCALE_BAR_POSITIONS, command=self._on_scale_bar_position_change)
        self.scale_bar_position_menu.set(self.scale_bar_position)
        self.scale_bar_position_menu.pack(fill="x", pady=(0, 4))

        self.scale_bar_thickness_slider, self.scale_bar_thickness_value_label = self._build_slider_row(
            body, "Bar thickness (px)", 1, 30, self.scale_bar_thickness, 29,
            self._on_scale_bar_thickness_slider)

        sb_color_row = customtkinter.CTkFrame(body, fg_color="transparent")
        sb_color_row.pack(fill="x", pady=(2, 2))
        customtkinter.CTkLabel(
            sb_color_row, text="Bar/label color").pack(side="left")
        self.scale_bar_color_swatch = customtkinter.CTkButton(
            sb_color_row, text="Color\u2026", width=90, command=self.choose_scale_bar_color,
            fg_color=self._rgb_to_hex(self.scale_bar_color),
            hover_color=self._rgb_to_hex(self.scale_bar_color),
            text_color=self._contrast_text_color(self.scale_bar_color))
        self.scale_bar_color_swatch.pack(side="right")

        for widget in (self.scale_bar_length_entry, self.scale_bar_label_entry,
                       self.scale_bar_thickness_slider, self.scale_bar_position_menu,
                       self.scale_bar_color_swatch):
            widget.configure(state="disabled")

    def _build_output_section(self):
        body = self._add_collapsible_section("Output", expanded=True)

        customtkinter.CTkLabel(body, text="Format").pack(anchor="w")
        self.format_menu = customtkinter.CTkOptionMenu(
            body, values=self.OUTPUT_FORMATS, command=self._on_format_change)
        self.format_menu.set(self.output_format)
        self.format_menu.pack(fill="x", pady=(0, 6))

        customtkinter.CTkLabel(
            body, text="DPI (embedded resolution)").pack(anchor="w")
        self.dpi_entry = customtkinter.CTkEntry(body)
        self.dpi_entry.insert(0, self.dpi_text)
        self.dpi_entry.bind("<KeyRelease>", self.request_preview_update)
        self.dpi_entry.pack(fill="x", pady=(0, 6))

        customtkinter.CTkLabel(
            body, text="Target width, px (optional)").pack(anchor="w")
        self.target_width_entry = customtkinter.CTkEntry(
            body, placeholder_text="leave blank to keep native size")
        self.target_width_entry.bind(
            "<KeyRelease>", self.request_preview_update)
        self.target_width_entry.pack(fill="x", pady=(0, 6))

        self.save_button = customtkinter.CTkButton(
            body, text="Save Figure", command=self.save_figure)
        self.save_button.pack(fill="x", pady=(6, 2))

    def _build_slider_row(self, parent, label_text, frm, to, initial, steps, callback):
        header = customtkinter.CTkFrame(parent, fg_color="transparent")
        header.pack(fill="x", pady=(6, 0))
        customtkinter.CTkLabel(header, text=label_text).pack(side="left")
        value_label = customtkinter.CTkLabel(header, text=str(initial))
        value_label.pack(side="right")

        slider = customtkinter.CTkSlider(
            parent, from_=frm, to=to, number_of_steps=steps, command=callback)
        slider.set(initial)
        slider.pack(fill="x", pady=(0, 2))
        return slider, value_label

    # ------------------------------------------------------------------
    # Preview area: zoomable/pannable canvas
    # ------------------------------------------------------------------
    def _build_preview_area(self):
        self.dimensions_label = customtkinter.CTkLabel(
            self.preview_frame, text="", justify="center")
        self.dimensions_label.pack(pady=(10, 2))

        zoom_row = customtkinter.CTkFrame(
            self.preview_frame, fg_color="transparent")
        zoom_row.pack(fill="x", padx=10, pady=(0, 6))
        customtkinter.CTkButton(
            zoom_row, text="\u2212", width=32, command=self.zoom_out).pack(side="left")
        self.zoom_slider = customtkinter.CTkSlider(
            zoom_row, from_=self.ZOOM_MIN, to=self.ZOOM_MAX,
            number_of_steps=self.ZOOM_MAX - self.ZOOM_MIN, command=self._on_zoom_slider)
        self.zoom_slider.set(100)
        self.zoom_slider.pack(side="left", fill="x", expand=True, padx=6)
        customtkinter.CTkButton(
            zoom_row, text="+", width=32, command=self.zoom_in).pack(side="left")
        self.zoom_pct_label = customtkinter.CTkLabel(
            zoom_row, text="100%", width=48)
        self.zoom_pct_label.pack(side="left", padx=(6, 0))
        customtkinter.CTkButton(zoom_row, text="Fit", width=46, command=self.zoom_fit).pack(
            side="left", padx=(6, 0))
        customtkinter.CTkButton(zoom_row, text="100%", width=54, command=self.zoom_reset).pack(
            side="left", padx=(4, 0))

        canvas_container = customtkinter.CTkFrame(self.preview_frame)
        canvas_container.pack(expand=True, fill="both", padx=10, pady=(0, 10))
        canvas_container.grid_rowconfigure(0, weight=1)
        canvas_container.grid_columnconfigure(0, weight=1)

        canvas_bg = self._resolve_appearance_color(
            canvas_container.cget("fg_color"))
        self.preview_canvas = Canvas(
            canvas_container, bg=canvas_bg, highlightthickness=0)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")

        self.preview_vscroll = customtkinter.CTkScrollbar(
            canvas_container, orientation="vertical", command=self.preview_canvas.yview)
        self.preview_vscroll.grid(row=0, column=1, sticky="ns")
        self.preview_hscroll = customtkinter.CTkScrollbar(
            canvas_container, orientation="horizontal", command=self.preview_canvas.xview)
        self.preview_hscroll.grid(row=1, column=0, sticky="ew")
        self.preview_canvas.configure(
            yscrollcommand=self.preview_vscroll.set, xscrollcommand=self.preview_hscroll.set)

        # pan by click-drag, zoom-to-fit on double-click
        self.preview_canvas.bind(
            "<ButtonPress-1>", lambda e: self.preview_canvas.scan_mark(e.x, e.y))
        self.preview_canvas.bind(
            "<B1-Motion>", lambda e: self.preview_canvas.scan_dragto(e.x, e.y, gain=1))
        self.preview_canvas.bind(
            "<Double-Button-1>", lambda e: self.zoom_fit())
        # zoom with the mouse wheel (Windows/macOS send <MouseWheel>, Linux sends Button-4/5)
        self.preview_canvas.bind("<MouseWheel>", self._on_mousewheel_zoom)
        self.preview_canvas.bind(
            "<Button-4>", lambda e: self._on_mousewheel_zoom(e, direction=1))
        self.preview_canvas.bind(
            "<Button-5>", lambda e: self._on_mousewheel_zoom(e, direction=-1))
        # keep the empty-state message/button centered if the window is resized
        self.preview_canvas.bind("<Configure>", self._on_preview_canvas_resize)

        # Created once and re-placed (never re-created) by _show_canvas_message,
        # so repeated empty-state redraws don't pile up orphaned button widgets.
        self.empty_state_button = customtkinter.CTkButton(
            self.preview_canvas, text="+  Add Photos", command=self.add_photos,
            width=180, height=40, font=customtkinter.CTkFont(size=14, weight="bold"))

        self._show_canvas_message(
            "Add photos to see\na preview here", show_add_button=True)

    def _resolve_appearance_color(self, color):
        if isinstance(color, (list, tuple)):
            mode = customtkinter.get_appearance_mode()
            return color[0] if mode == "Light" else color[1]
        return color

    def _on_preview_canvas_resize(self, event=None):
        if not self.images:
            self._show_canvas_message(
                "Add photos to see\na preview here", show_add_button=True)

    def _show_canvas_message(self, text, error=False, show_add_button=False):
        self.preview_canvas.delete("all")
        self.preview_canvas.update_idletasks()
        w = max(240, self.preview_canvas.winfo_width())
        h = max(180, self.preview_canvas.winfo_height())
        cx, cy = w / 2, h / 2

        text_y = (cy - 34) if show_add_button else cy
        self.preview_canvas.create_text(
            cx, text_y, text=text, fill="#e0706f" if error else "#999999",
            anchor="center", justify="center",
            font=("Helvetica", 20), width=max(260, w - 80))

        if show_add_button:
            self.preview_canvas.create_window(
                cx, cy + 36, window=self.empty_state_button, anchor="center")

        self.preview_canvas.configure(scrollregion=(0, 0, 0, 0))

    # ---- zoom controls ----
    def _on_zoom_slider(self, value):
        self.preview_zoom = float(value) / 100.0
        self.zoom_pct_label.configure(text=f"{int(round(float(value)))}%")
        self._render_preview_at_zoom()

    def zoom_in(self):
        new_val = min(self.ZOOM_MAX, self.zoom_slider.get() + self.ZOOM_STEP)
        self.zoom_slider.set(new_val)
        self._on_zoom_slider(new_val)

    def zoom_out(self):
        new_val = max(self.ZOOM_MIN, self.zoom_slider.get() - self.ZOOM_STEP)
        self.zoom_slider.set(new_val)
        self._on_zoom_slider(new_val)

    def zoom_reset(self):
        self.zoom_slider.set(100)
        self._on_zoom_slider(100)

    def zoom_fit(self):
        if self._preview_base_image is None:
            return
        self.preview_canvas.update_idletasks()
        view_w = max(50, self.preview_canvas.winfo_width())
        view_h = max(50, self.preview_canvas.winfo_height())
        img_w, img_h = self._preview_base_image.size
        fit_pct = min(view_w / img_w, view_h / img_h) * 100
        fit_pct = max(self.ZOOM_MIN, min(self.ZOOM_MAX, fit_pct))
        self.zoom_slider.set(fit_pct)
        self._on_zoom_slider(fit_pct)

    def _on_mousewheel_zoom(self, event, direction=None):
        if direction is None:
            direction = 1 if event.delta > 0 else -1
        new_val = max(self.ZOOM_MIN, min(
            self.ZOOM_MAX, self.zoom_slider.get() + direction * self.ZOOM_STEP))
        self.zoom_slider.set(new_val)
        self._on_zoom_slider(new_val)
        return "break"

    def _render_preview_at_zoom(self):
        if self._preview_base_image is None:
            self._show_canvas_message(
                "Add photos to see\na preview here", show_add_button=True)
            return
        base_w, base_h = self._preview_base_image.size
        disp_w = max(1, int(round(base_w * self.preview_zoom)))
        disp_h = max(1, int(round(base_h * self.preview_zoom)))

        if disp_w == base_w and disp_h == base_h:
            display_img = self._preview_base_image
        else:
            display_img = self._preview_base_image.resize(
                (disp_w, disp_h), RESAMPLE_LANCZOS)

        self._preview_photo_image = ImageTk.PhotoImage(display_img)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(
            0, 0, anchor="nw", image=self._preview_photo_image)
        self.preview_canvas.configure(scrollregion=(0, 0, disp_w, disp_h))

    # ------------------------------------------------------------------
    # Image list management
    # ------------------------------------------------------------------
    def add_photos(self):
        file_paths = filedialog.askopenfilenames(
            title="Select Photos",
            filetypes=[
                ("Image Files", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
                ("All Files", "*.*"),
            ],
        )
        if not file_paths:
            return

        failed = []
        for file_path in file_paths:
            try:
                img = self._load_image_file(file_path)
                self.images.append(img)
                self.image_paths.append(file_path)
            except Exception as e:
                failed.append(f"{os.path.basename(file_path)}: {e}")

        self.refresh_image_list_ui()
        self.request_preview_update()

        if failed:
            messagebox.showwarning(
                "Some files could not be loaded",
                "The following files were skipped:\n\n" + "\n".join(failed),
            )

    @staticmethod
    def _load_image_file(file_path):
        img = Image.open(file_path)
        # fix sideways/upside-down phone photos
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")
        img.load()
        return img

    def clear_all(self):
        if not self.images:
            return
        if messagebox.askyesno("Clear All", "Remove all photos from the list?"):
            self.images.clear()
            self.image_paths.clear()
            self.refresh_image_list_ui()
            self.request_preview_update()

    def remove_image(self, index):
        if 0 <= index < len(self.images):
            del self.images[index]
            del self.image_paths[index]
            self.refresh_image_list_ui()
            self.request_preview_update()

    def move_image_up(self, index):
        if index > 0:
            self.images[index -
                        1], self.images[index] = self.images[index], self.images[index - 1]
            self.image_paths[index - 1], self.image_paths[index] = (
                self.image_paths[index], self.image_paths[index - 1])
            self.refresh_image_list_ui()
            self.request_preview_update()

    def move_image_down(self, index):
        if index < len(self.images) - 1:
            self.images[index +
                        1], self.images[index] = self.images[index], self.images[index + 1]
            self.image_paths[index + 1], self.image_paths[index] = (
                self.image_paths[index], self.image_paths[index + 1])
            self.refresh_image_list_ui()
            self.request_preview_update()

    def refresh_image_list_ui(self):
        for child in self.list_container.winfo_children():
            child.destroy()
        self._thumb_refs = []

        if not self.images:
            customtkinter.CTkLabel(
                self.list_container, text="No photos added yet.", text_color="gray60"
            ).pack(pady=16)
            return

        for index, (img, path) in enumerate(zip(self.images, self.image_paths)):
            row = customtkinter.CTkFrame(self.list_container)
            row.pack(fill="x", pady=3)

            thumb_pil = self._make_thumbnail(img, size=44)
            ctk_thumb = customtkinter.CTkImage(
                light_image=thumb_pil, dark_image=thumb_pil, size=(44, 44))
            self._thumb_refs.append(ctk_thumb)

            customtkinter.CTkLabel(row, image=ctk_thumb, text="").grid(
                row=0, column=0, rowspan=2, padx=6, pady=4)

            name = os.path.basename(path)
            if len(name) > 22:
                name = name[:19] + "..."
            customtkinter.CTkLabel(
                row, text=f"{self._index_to_letters(index)}: {name}", anchor="w"
            ).grid(row=0, column=1, columnspan=3, sticky="w", padx=(0, 6))

            customtkinter.CTkButton(
                row, text="\u2191", width=26, height=24,
                command=lambda i=index: self.move_image_up(i)
            ).grid(row=1, column=1, padx=2, pady=(0, 4))
            customtkinter.CTkButton(
                row, text="\u2193", width=26, height=24,
                command=lambda i=index: self.move_image_down(i)
            ).grid(row=1, column=2, padx=2, pady=(0, 4))
            customtkinter.CTkButton(
                row, text="\u2715", width=26, height=24, fg_color="#8b2c2c",
                hover_color="#6e2222", command=lambda i=index: self.remove_image(i)
            ).grid(row=1, column=3, padx=2, pady=(0, 4))

    def _make_thumbnail(self, img, size=44):
        thumb = ImageOps.contain(img, (size, size), method=RESAMPLE_LANCZOS)
        canvas = Image.new("RGB", (size, size), "#2b2b2b")
        x = (size - thumb.width) // 2
        y = (size - thumb.height) // 2
        if thumb.mode == "RGBA":
            canvas.paste(thumb, (x, y), thumb)
        else:
            canvas.paste(thumb.convert("RGB"), (x, y))
        return canvas

    # ------------------------------------------------------------------
    # Control callbacks
    # ------------------------------------------------------------------
    def _on_auto_rows_toggle(self):
        self.auto_rows = bool(self.auto_rows_checkbox.get())
        self.rows_slider.configure(
            state="disabled" if self.auto_rows else "normal")
        self.request_preview_update()

    def _on_rows_slider(self, value):
        self.rows = int(round(value))
        self.rows_value_label.configure(text=str(self.rows))
        self.request_preview_update()

    def _on_cols_slider(self, value):
        self.cols = int(round(value))
        self.cols_value_label.configure(text=str(self.cols))
        self.request_preview_update()

    def _on_panel_order_change(self, choice):
        self.panel_order = choice
        self.request_preview_update()

    def _on_hspacing_slider(self, value):
        self.h_spacing = int(round(value))
        self.hspacing_value_label.configure(text=str(self.h_spacing))
        self.request_preview_update()

    def _on_vspacing_slider(self, value):
        self.v_spacing = int(round(value))
        self.vspacing_value_label.configure(text=str(self.v_spacing))
        self.request_preview_update()

    def _on_margin_slider(self, value):
        self.margin = int(round(value))
        self.margin_value_label.configure(text=str(self.margin))
        self.request_preview_update()

    def _on_font_size_slider(self, value):
        self.font_size = int(round(value))
        self.font_size_value_label.configure(text=str(self.font_size))
        self.request_preview_update()

    def _on_cell_size_mode_change(self, choice):
        self.cell_size_mode = choice
        if choice == "Custom size":
            self.custom_size_frame.pack(
                fill="x", pady=(0, 6), after=self.cell_size_menu)
        else:
            self.custom_size_frame.pack_forget()
        self.request_preview_update()

    def _on_label_style_change(self, choice):
        self.label_style = choice
        if choice == "Custom list":
            self.custom_labels_entry.pack(
                fill="x", pady=(0, 6), after=self.label_style_menu)
        else:
            self.custom_labels_entry.pack_forget()
        self.request_preview_update()

    def _on_label_format_change(self, choice):
        self.label_format = choice
        self.request_preview_update()

    def _on_label_position_change(self, choice):
        self.label_position = choice
        self.request_preview_update()

    def _on_font_family_change(self, choice):
        self.font_family = choice
        self.request_preview_update()

    def _on_bold_toggle(self):
        self.font_bold = bool(self.bold_checkbox.get())
        self.request_preview_update()

    def _on_transparent_toggle(self):
        self.transparent_bg = bool(self.transparent_checkbox.get())
        self.request_preview_update()

    def _on_border_toggle(self):
        self.panel_border_enabled = bool(self.border_checkbox.get())
        self.border_width_slider.configure(
            state="normal" if self.panel_border_enabled else "disabled")
        self.request_preview_update()

    def _on_border_width_slider(self, value):
        self.panel_border_width = int(round(value))
        self.border_width_value_label.configure(
            text=str(self.panel_border_width))
        self.request_preview_update()

    def _on_grayscale_toggle(self):
        self.grayscale_enabled = bool(self.grayscale_checkbox.get())
        self.request_preview_update()

    def _on_auto_contrast_toggle(self):
        self.auto_contrast_enabled = bool(self.auto_contrast_checkbox.get())
        self.request_preview_update()

    def _on_caption_text_change(self, event=None):
        self.figure_caption_text = self.caption_entry.get()
        self.request_preview_update()

    def _on_caption_position_change(self, choice):
        self.figure_caption_position = choice
        self.request_preview_update()

    def _on_caption_font_size_slider(self, value):
        self.caption_font_size = int(round(value))
        self.caption_font_size_value_label.configure(
            text=str(self.caption_font_size))
        self.request_preview_update()

    def choose_caption_color(self):
        _, hex_color = colorchooser.askcolor(
            color=self._rgb_to_hex(self.caption_color), title="Choose Caption Color")
        if hex_color:
            self.caption_color = self._hex_to_rgb(hex_color)
            self.caption_color_swatch.configure(
                fg_color=hex_color, hover_color=hex_color,
                text_color=self._contrast_text_color(self.caption_color))
            self.request_preview_update()

    def _on_scale_bar_toggle(self):
        self.scale_bar_enabled = bool(self.scale_bar_checkbox.get())
        state = "normal" if self.scale_bar_enabled else "disabled"
        for widget in (self.scale_bar_length_entry, self.scale_bar_label_entry,
                       self.scale_bar_thickness_slider, self.scale_bar_position_menu,
                       self.scale_bar_color_swatch):
            widget.configure(state=state)
        self.request_preview_update()

    def _on_scale_bar_length_change(self, event=None):
        self.scale_bar_length_px = self._safe_int(
            self.scale_bar_length_entry.get(), self.scale_bar_length_px)
        self.request_preview_update()

    def _on_scale_bar_label_change(self, event=None):
        self.scale_bar_label = self.scale_bar_label_entry.get()
        self.request_preview_update()

    def _on_scale_bar_position_change(self, choice):
        self.scale_bar_position = choice
        self.request_preview_update()

    def _on_scale_bar_thickness_slider(self, value):
        self.scale_bar_thickness = int(round(value))
        self.scale_bar_thickness_value_label.configure(
            text=str(self.scale_bar_thickness))
        self.request_preview_update()

    def _on_format_change(self, choice):
        self.output_format = choice
        self.request_preview_update()

    def choose_bg_color(self):
        _, hex_color = colorchooser.askcolor(
            color=self._rgb_to_hex(self.bg_color), title="Choose Background Color")
        if hex_color:
            self.bg_color = self._hex_to_rgb(hex_color)
            self.bg_swatch.configure(
                fg_color=hex_color, hover_color=hex_color,
                text_color=self._contrast_text_color(self.bg_color))
            self.request_preview_update()

    def choose_font_color(self):
        _, hex_color = colorchooser.askcolor(
            color=self._rgb_to_hex(self.font_color), title="Choose Label Color")
        if hex_color:
            self.font_color = self._hex_to_rgb(hex_color)
            self.font_color_swatch.configure(
                fg_color=hex_color, hover_color=hex_color,
                text_color=self._contrast_text_color(self.font_color))
            self.request_preview_update()

    def choose_border_color(self):
        _, hex_color = colorchooser.askcolor(
            color=self._rgb_to_hex(self.panel_border_color), title="Choose Border Color")
        if hex_color:
            self.panel_border_color = self._hex_to_rgb(hex_color)
            self.border_color_swatch.configure(
                fg_color=hex_color, hover_color=hex_color,
                text_color=self._contrast_text_color(self.panel_border_color))
            self.request_preview_update()

    def choose_scale_bar_color(self):
        _, hex_color = colorchooser.askcolor(
            color=self._rgb_to_hex(self.scale_bar_color), title="Choose Scale Bar Color")
        if hex_color:
            self.scale_bar_color = self._hex_to_rgb(hex_color)
            self.scale_bar_color_swatch.configure(
                fg_color=hex_color, hover_color=hex_color,
                text_color=self._contrast_text_color(self.scale_bar_color))
            self.request_preview_update()

    def browse_font_file(self):
        path = filedialog.askopenfilename(
            title="Select Font File",
            filetypes=[("Font Files", "*.ttf *.otf"), ("All Files", "*.*")])
        if path:
            self.custom_font_path = path
            self.font_file_label.configure(text=os.path.basename(path))
            self.request_preview_update()

    def clear_custom_font(self):
        self.custom_font_path = None
        self.font_file_label.configure(
            text="(none \u2014 using dropdown font)")
        self.request_preview_update()

    # ------------------------------------------------------------------
    # Layout / composition math
    # ------------------------------------------------------------------
    def _compute_natural_cell_size(self):
        if not self.images:
            return 400, 400
        if self.cell_size_mode == "Custom size":
            w = self._safe_int(self.custom_width_entry.get(), None)
            h = self._safe_int(self.custom_height_entry.get(), None)
            if not w or w <= 0:
                w = max(img.width for img in self.images)
            if not h or h <= 0:
                h = max(img.height for img in self.images)
            return w, h
        widths = [img.width for img in self.images]
        heights = [img.height for img in self.images]
        if self.cell_size_mode == "Fit to smallest photo":
            return min(widths), min(heights)
        return max(widths), max(heights)

    def _natural_metrics(self):
        cols = max(1, self.cols)
        if self.auto_rows:
            rows = max(1, math.ceil(len(self.images) / cols)
                       ) if self.images else 1
        else:
            rows = max(1, self.rows)

        cell_w, cell_h = self._compute_natural_cell_size()
        h_spacing = max(0, self.h_spacing)
        v_spacing = max(0, self.v_spacing)
        margin = max(0, self.margin)
        font_size = max(1, self.font_size)
        border_width = max(
            0, self.panel_border_width) if self.panel_border_enabled else 0
        scale_bar_thickness = max(
            1, self.scale_bar_thickness) if self.scale_bar_enabled else 0

        needs_top_space = (self.label_style !=
                           "None" and self.label_position == "Above panel")
        top_pad = int(font_size * 1.6) if needs_top_space else 0

        grid_w = cols * cell_w + max(0, cols - 1) * h_spacing
        grid_h = rows * (cell_h + top_pad) + max(0, rows - 1) * v_spacing
        canvas_w = margin * 2 + grid_w  # width doesn't depend on the caption

        caption_text = self.figure_caption_text.strip()
        caption_font_size = max(
            1, self.caption_font_size) if caption_text else 0
        caption_lines, caption_pad = self._compute_caption_layout(
            caption_text, caption_font_size, canvas_w, margin)

        canvas_h = margin * 2 + caption_pad + grid_h

        grid_start_y = margin + \
            (caption_pad if self.figure_caption_position == "Top" else 0)

        return {
            "rows": rows, "cols": cols, "cell_w": cell_w, "cell_h": cell_h,
            "h_spacing": h_spacing, "v_spacing": v_spacing, "margin": margin,
            "font_size": font_size, "top_pad": top_pad,
            "border_width": border_width, "scale_bar_thickness": scale_bar_thickness,
            "caption_font_size": caption_font_size, "caption_pad": caption_pad,
            "caption_lines": caption_lines,
            "grid_start_y": grid_start_y,
            "canvas_w": canvas_w, "canvas_h": canvas_h,
        }

    def _scaled_metrics(self, natural, max_dim):
        """Build preview-resolution metrics the SAME way _natural_metrics
        builds full-resolution ones (component-by-component, then summed),
        rather than independently rescaling the natural totals. This keeps
        the canvas size always exactly consistent with its parts, and lets
        each component enforce its own minimum-visible-size floor so thin
        elements (a 1-3px border, small spacing, etc.) don't silently round
        away to 0 and "disappear" in a heavily shrunk preview. The caption
        is re-wrapped at the scaled font size/width rather than reusing the
        natural line count, so preview wrapping always matches what's
        actually drawn at this resolution."""
        largest = max(natural["canvas_w"], natural["canvas_h"], 1)
        scale = min(1.0, max_dim / largest) if max_dim else 1.0

        def floored(v, floor=1):
            if v <= 0:
                return 0
            return max(floor, int(round(v * scale)))

        cols, rows = natural["cols"], natural["rows"]
        cell_w = max(1, int(round(natural["cell_w"] * scale)))
        cell_h = max(1, int(round(natural["cell_h"] * scale)))
        h_spacing = floored(natural["h_spacing"])
        v_spacing = floored(natural["v_spacing"])
        margin = floored(natural["margin"])
        font_size = max(6, int(round(natural["font_size"] * scale)))
        top_pad = floored(natural["top_pad"],
                          floor=font_size) if natural["top_pad"] else 0
        border_width = floored(natural["border_width"])
        scale_bar_thickness = floored(natural["scale_bar_thickness"])

        grid_w = cols * cell_w + max(0, cols - 1) * h_spacing
        grid_h = rows * (cell_h + top_pad) + max(0, rows - 1) * v_spacing
        canvas_w = margin * 2 + grid_w

        caption_text = self.figure_caption_text.strip()
        caption_font_size = (max(6, int(round(natural["caption_font_size"] * scale)))
                             if natural["caption_font_size"] else 0)
        caption_lines, caption_pad = self._compute_caption_layout(
            caption_text, caption_font_size, canvas_w, margin)

        canvas_h = margin * 2 + caption_pad + grid_h
        grid_start_y = margin + \
            (caption_pad if self.figure_caption_position == "Top" else 0)

        return {
            "rows": rows, "cols": cols, "cell_w": cell_w, "cell_h": cell_h,
            "h_spacing": h_spacing, "v_spacing": v_spacing, "margin": margin,
            "font_size": font_size, "top_pad": top_pad,
            "border_width": border_width, "scale_bar_thickness": scale_bar_thickness,
            "caption_font_size": caption_font_size, "caption_pad": caption_pad,
            "caption_lines": caption_lines,
            "grid_start_y": grid_start_y,
            "canvas_w": canvas_w, "canvas_h": canvas_h,
        }

    def _get_label_text(self, index):
        style = self.label_style
        if style == "None":
            return ""
        if style == "Custom list":
            parts = [p.strip()
                     for p in self.custom_labels_entry.get().split(",")]
            return parts[index] if index < len(parts) and parts[index] else ""

        if style == "Numbers (1, 2, 3\u2026)":
            base = str(index + 1)
        elif style == "Lowercase (a, b, c\u2026)":
            base = self._index_to_letters(index).lower()
        else:
            base = self._index_to_letters(index)

        fmt = self.label_format
        if fmt == "A.":
            return base + "."
        if fmt == "(A)":
            return f"({base})"
        if fmt == "A)":
            return base + ")"
        return base

    def _panel_position(self, index, cols, rows):
        """Map a photo's position in the list to a (row, col) grid cell.
        'By row' fills left-to-right then down (the classic order); 'By
        column' fills top-to-bottom then across, which groups a run of
        consecutive photos into the same column instead of the same row.
        Labels still follow the photo's list order either way - only the
        spatial placement changes."""
        if self.panel_order == "By column":
            col, row = divmod(index, rows)
            out_of_bounds = col >= cols
        else:
            row, col = divmod(index, cols)
            out_of_bounds = row >= rows
        return row, col, out_of_bounds

    @staticmethod
    def _index_to_letters(index):
        letters = ""
        n = index
        while True:
            n, rem = divmod(n, 26)
            letters = chr(65 + rem) + letters
            if n == 0:
                break
            n -= 1
        return letters

    def _get_pil_font(self, size):
        if self.custom_font_path:
            try:
                font = ImageFont.truetype(self.custom_font_path, size)
                self.font_resolution_status = f"Using custom file: {os.path.basename(self.custom_font_path)}"
                return font
            except Exception:
                self.font_resolution_status = "\u26a0 Custom font file failed to load \u2014 falling back."

        font = resolve_font(self.font_family, size, bold=self.font_bold)
        if font is not None:
            self.font_resolution_status = ""
            return font

        fallback_path = find_any_system_font(bold=self.font_bold)
        if fallback_path:
            try:
                font = ImageFont.truetype(fallback_path, size)
                self.font_resolution_status = (
                    f"\u26a0 \u201c{self.font_family}\u201d wasn't found on this system \u2014 "
                    f"using {os.path.basename(fallback_path)} instead so size still works. "
                    "Use \u201cBrowse font file\u2026\u201d to pick an exact font."
                )
                return font
            except Exception:
                pass

        self.font_resolution_status = (
            "\u26a0 No scalable font file found on this system \u2014 labels will stay a "
            "small fixed size regardless of the slider. Click \u201cBrowse font file\u2026\u201d "
            "and pick any .ttf/.otf file (there's usually one under your OS's Fonts folder) to fix this."
        )
        return load_fallback_font(size)

    def _apply_image_adjustments(self, img):
        if not (self.auto_contrast_enabled or self.grayscale_enabled):
            return img
        has_alpha = img.mode == "RGBA"
        alpha = img.split()[3] if has_alpha else None
        rgb = img.convert("RGB")
        if self.auto_contrast_enabled:
            try:
                rgb = ImageOps.autocontrast(rgb, cutoff=1)
            except Exception:
                pass
        if self.grayscale_enabled:
            rgb = ImageOps.grayscale(rgb).convert("RGB")
        if has_alpha:
            return Image.merge("RGBA", (*rgb.split(), alpha))
        return rgb

    def _draw_anchored_text(self, draw, xy, text, font, fill, h_align="left", v_align="top"):
        x, y = xy
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            off_x, off_y = bbox[0], bbox[1]
        except Exception:
            w, h = draw.textsize(text, font=font)
            off_x = off_y = 0

        if h_align == "center":
            x -= w / 2
        elif h_align == "right":
            x -= w
        if v_align == "middle":
            y -= h / 2
        elif v_align == "bottom":
            y -= h

        draw.text((x - off_x, y - off_y), text, font=font, fill=fill)

    def _text_width(self, draw, text, font):
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0]
        except Exception:
            return draw.textsize(text, font=font)[0]

    def _wrap_text_lines(self, text, font, max_width):
        """Word-wrap text to fit within max_width at the given font.
        Returns at least one line (an empty string for empty input), and
        never breaks in the middle of a word - a single word wider than
        max_width on its own is simply left to overflow that one line,
        the same way most text renderers handle an unbreakable run."""
        scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        words = text.split()
        if not words:
            return [""]
        lines = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if self._text_width(scratch, candidate, font) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def _compute_caption_layout(self, caption_text, caption_font_size, canvas_w, margin):
        """Resolve the caption font at caption_font_size, word-wrap
        caption_text so it stays within the figure width with a small
        safety margin before the edge, and return (lines, vertical space
        needed). Called from both _natural_metrics and _scaled_metrics so
        the space reserved in the layout always matches what compose_figure
        actually draws, at either full or preview resolution."""
        if not caption_text or caption_font_size <= 0:
            return [], 0
        side_pad = max(16, round(caption_font_size * 0.4))
        max_width = max(20, canvas_w - 2 * margin - 2 * side_pad)
        font = self._get_pil_font(caption_font_size)
        lines = self._wrap_text_lines(caption_text, font, max_width)
        line_height = int(caption_font_size * 1.35)
        pad = line_height * len(lines) + int(caption_font_size * 0.6)
        return lines, pad

    def _draw_label(self, draw, text, font, position, cell_x, img_y, cell_w, cell_h, cell_y, top_pad):
        pad = 4
        if position == "Above panel":
            self._draw_anchored_text(
                draw, (cell_x + cell_w / 2, cell_y + top_pad / 2), text, font,
                self.font_color, h_align="center", v_align="middle")
        elif position == "Top-left (inside)":
            self._draw_anchored_text(
                draw, (cell_x + pad, img_y + pad), text, font, self.font_color,
                h_align="left", v_align="top")
        elif position == "Top-right (inside)":
            self._draw_anchored_text(
                draw, (cell_x + cell_w - pad, img_y +
                       pad), text, font, self.font_color,
                h_align="right", v_align="top")
        elif position == "Bottom-left (inside)":
            self._draw_anchored_text(
                draw, (cell_x + pad, img_y + cell_h -
                       pad), text, font, self.font_color,
                h_align="left", v_align="bottom")
        else:  # Bottom-right (inside)
            self._draw_anchored_text(
                draw, (cell_x + cell_w - pad, img_y + cell_h -
                       pad), text, font, self.font_color,
                h_align="right", v_align="bottom")

    def _draw_scale_bar(self, draw, paste_x, paste_y, fitted, effective_scale, font, metrics):
        bar_len = max(
            1, int(round(self.scale_bar_length_px * effective_scale)))
        thickness = max(1, metrics["scale_bar_thickness"])
        pad = max(4, thickness)
        fw, fh = fitted.size

        position = self.scale_bar_position
        if position == "Bottom-right":
            x2 = paste_x + fw - pad
            x1 = x2 - bar_len
            y2 = paste_y + fh - pad
            y1 = y2 - thickness
            text_xy, h_align, v_align = (x2, y1 - 4), "right", "bottom"
        elif position == "Bottom-left":
            x1 = paste_x + pad
            x2 = x1 + bar_len
            y2 = paste_y + fh - pad
            y1 = y2 - thickness
            text_xy, h_align, v_align = (x1, y1 - 4), "left", "bottom"
        elif position == "Top-right":
            x2 = paste_x + fw - pad
            x1 = x2 - bar_len
            y1 = paste_y + pad
            y2 = y1 + thickness
            text_xy, h_align, v_align = (x2, y2 + 4), "right", "top"
        else:  # Top-left
            x1 = paste_x + pad
            x2 = x1 + bar_len
            y1 = paste_y + pad
            y2 = y1 + thickness
            text_xy, h_align, v_align = (x1, y2 + 4), "left", "top"

        draw.rectangle([x1, y1, x2, y2], fill=self.scale_bar_color)
        label = self.scale_bar_label.strip()
        if label:
            self._draw_anchored_text(draw, text_xy, label, font, self.scale_bar_color,
                                     h_align=h_align, v_align=v_align)

    def compose_figure(self, preview_max_dim=None):
        if not self.images:
            return None

        natural = self._natural_metrics()
        metrics = self._scaled_metrics(
            natural, preview_max_dim) if preview_max_dim else natural

        transparent = self.transparent_bg and self.output_format == "PNG"
        mode = "RGBA" if transparent else "RGB"
        bg = (0, 0, 0, 0) if transparent else self.bg_color

        canvas = Image.new(
            mode, (metrics["canvas_w"], metrics["canvas_h"]), bg)
        draw = ImageDraw.Draw(canvas)
        label_font = self._get_pil_font(metrics["font_size"])

        cell_w, cell_h, top_pad = metrics["cell_w"], metrics["cell_h"], metrics["top_pad"]
        cols, rows = metrics["cols"], metrics["rows"]
        border_w = metrics["border_width"]

        for index, img in enumerate(self.images):
            row, col, out_of_bounds = self._panel_position(index, cols, rows)
            if out_of_bounds:
                break

            cell_x = metrics["margin"] + col * (cell_w + metrics["h_spacing"])
            cell_y = metrics["grid_start_y"] + row * \
                (cell_h + top_pad + metrics["v_spacing"])
            img_y = cell_y + top_pad

            fitted = ImageOps.contain(
                img, (max(cell_w, 1), max(cell_h, 1)), method=RESAMPLE_LANCZOS)
            fitted = self._apply_image_adjustments(fitted)
            effective_scale = (fitted.width / img.width) if img.width else 1.0

            paste_x = cell_x + (cell_w - fitted.width) // 2
            paste_y = img_y + (cell_h - fitted.height) // 2

            if canvas.mode == "RGBA":
                if fitted.mode != "RGBA":
                    fitted = fitted.convert("RGBA")
                canvas.paste(fitted, (paste_x, paste_y), fitted)
            else:
                if fitted.mode == "RGBA":
                    canvas.paste(fitted, (paste_x, paste_y), fitted)
                else:
                    canvas.paste(fitted, (paste_x, paste_y))

            if self.panel_border_enabled and border_w > 0:
                draw.rectangle(
                    [cell_x, img_y, cell_x + cell_w - 1, img_y + cell_h - 1],
                    outline=self.panel_border_color, width=border_w)

            if self.scale_bar_enabled:
                self._draw_scale_bar(
                    draw, paste_x, paste_y, fitted, effective_scale, label_font, metrics)

            label_text = self._get_label_text(index)
            if label_text:
                self._draw_label(draw, label_text, label_font, self.label_position,
                                 cell_x, img_y, cell_w, cell_h, cell_y, top_pad)

        caption_lines = metrics.get("caption_lines") or []
        if caption_lines:
            caption_font = self._get_pil_font(metrics["caption_font_size"])
            line_height = int(metrics["caption_font_size"] * 1.35)
            block_height = line_height * len(caption_lines)
            if self.figure_caption_position == "Top":
                block_top = metrics["margin"] + \
                    (metrics["caption_pad"] - block_height) / 2
            else:
                block_top = (metrics["canvas_h"] - metrics["margin"] - metrics["caption_pad"]
                             + (metrics["caption_pad"] - block_height) / 2)
            for i, line in enumerate(caption_lines):
                line_cy = block_top + line_height * i + line_height / 2
                self._draw_anchored_text(
                    draw, (metrics["canvas_w"] / 2,
                           line_cy), line, caption_font,
                    self.caption_color, h_align="center", v_align="middle")

        return canvas

    # ------------------------------------------------------------------
    # Preview & save
    # ------------------------------------------------------------------
    def request_preview_update(self, *_args):
        if self._preview_after_id is not None:
            self.root.after_cancel(self._preview_after_id)
        self._preview_after_id = self.root.after(150, self.update_preview)

    def update_preview(self):
        self._preview_after_id = None
        natural = self._natural_metrics()

        if not self.images:
            self._preview_base_image = None
            self._show_canvas_message(
                "Add photos to see\na preview here", show_add_button=True)
            self.dimensions_label.configure(text="")
            self.font_size_physical_label.configure(text="")
            self.font_resolution_label.configure(text="")
            return

        was_empty = self._preview_base_image is None
        try:
            preview_img = self.compose_figure(
                preview_max_dim=self.PREVIEW_BASE_DIM)
        except Exception as e:
            traceback.print_exc()
            self._preview_base_image = None
            self._show_canvas_message(f"Preview error:\n{e}", error=True)
            return

        self._preview_base_image = preview_img
        self._render_preview_at_zoom()
        if was_empty:
            self.root.after(30, self.zoom_fit)

        canvas_w, canvas_h = natural["canvas_w"], natural["canvas_h"]
        dpi_val = self._safe_int(self.dpi_entry.get(), 300)
        info = f"Output size: {canvas_w} \u00d7 {canvas_h} px"

        target_raw = self.target_width_entry.get().strip()
        if target_raw:
            tw = self._safe_int(target_raw, None)
            if tw and tw > 0 and tw != canvas_w:
                th = max(1, round(canvas_h * (tw / canvas_w)))
                info += f"  \u2192  resized to {tw} \u00d7 {th} px"
                canvas_w, canvas_h = tw, th

        info += (f"   \u2022   {dpi_val} DPI   \u2022   "
                 f"~{canvas_w / dpi_val:.2f} \u00d7 {canvas_h / dpi_val:.2f} in")

        if not self.auto_rows and len(self.images) > natural["rows"] * natural["cols"]:
            shown = natural["rows"] * natural["cols"]
            info += (f"\n\u26a0 Showing {shown} of {len(self.images)} photos "
                     "\u2014 increase rows/columns, or enable auto-fit, to include them all.")

        self.dimensions_label.configure(text=info)

        self.font_size_physical_label.configure(
            text=f"Label text is {self.font_size}px tall at save resolution "
                 f"(~{self.font_size / dpi_val:.2f}in @ {dpi_val} DPI)")
        self.font_resolution_label.configure(text=self.font_resolution_status)

    def save_figure(self):
        if not self.images:
            messagebox.showinfo(
                "No Photos", "Add at least one photo before saving.")
            return

        fmt = self.output_format
        ext_map = {"TIFF": ".tiff", "PNG": ".png",
                   "JPEG": ".jpg", "PDF": ".pdf"}
        filetypes_map = {
            "TIFF": [("TIFF Files", "*.tiff *.tif")],
            "PNG": [("PNG Files", "*.png")],
            "JPEG": [("JPEG Files", "*.jpg *.jpeg")],
            "PDF": [("PDF Files", "*.pdf")],
        }
        file_path = filedialog.asksaveasfilename(
            defaultextension=ext_map[fmt], filetypes=filetypes_map[fmt])
        if not file_path:
            return

        try:
            final_image = self.compose_figure(preview_max_dim=None)
            if final_image is None:
                return

            target_w = self._safe_int(self.target_width_entry.get(), None)
            if target_w and target_w > 0 and target_w != final_image.width:
                ratio = target_w / final_image.width
                target_h = max(1, int(round(final_image.height * ratio)))
                final_image = final_image.resize(
                    (target_w, target_h), RESAMPLE_LANCZOS)

            dpi_val = self._safe_int(self.dpi_entry.get(), 300)
            save_kwargs = {}

            if fmt in ("JPEG", "PDF") and final_image.mode == "RGBA":
                flattened = Image.new("RGB", final_image.size, self.bg_color)
                flattened.paste(final_image, mask=final_image.split()[3])
                final_image = flattened
            elif fmt in ("JPEG", "PDF") and final_image.mode != "RGB":
                final_image = final_image.convert("RGB")

            if fmt == "JPEG":
                save_kwargs["dpi"] = (dpi_val, dpi_val)
                save_kwargs["quality"] = 95
                save_kwargs["optimize"] = True
            elif fmt == "TIFF":
                save_kwargs["dpi"] = (dpi_val, dpi_val)
                save_kwargs["compression"] = "tiff_lzw"
            elif fmt == "PNG":
                save_kwargs["dpi"] = (dpi_val, dpi_val)
            elif fmt == "PDF":
                # Pillow's PDF writer uses "resolution" (dots per inch) to
                # size the page - "dpi" is not a recognized kwarg here.
                save_kwargs["resolution"] = float(dpi_val)

            final_image.save(file_path, format=fmt, **save_kwargs)
            self._show_save_success_dialog(file_path)

        except Exception as e:
            traceback.print_exc()
            messagebox.showerror(
                "Save Failed", f"Could not save the figure:\n{e}")

    def _show_save_success_dialog(self, file_path):
        dialog = customtkinter.CTkToplevel(self.root)
        dialog.title("Figure Saved")
        dialog.geometry("440x190")
        dialog.resizable(False, False)

        customtkinter.CTkLabel(
            dialog, text=f"Figure saved to:\n{file_path}", wraplength=400, justify="center"
        ).pack(padx=20, pady=(20, 14))

        btn_row = customtkinter.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(pady=(0, 14))
        customtkinter.CTkButton(
            btn_row, text="Open Folder", width=140,
            command=lambda: self._open_containing_folder(file_path)
        ).pack(side="left", padx=6)
        customtkinter.CTkButton(
            btn_row, text="Open File", width=140,
            command=lambda: self._open_file(file_path)
        ).pack(side="left", padx=6)

        customtkinter.CTkButton(
            dialog, text="Close", fg_color="transparent", border_width=1,
            command=dialog.destroy
        ).pack(pady=(0, 14))

    def _open_file(self, path):
        """Open the saved figure with the OS's default associated app."""
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa: (Windows-only attribute)
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
        except Exception as e:
            messagebox.showerror("Couldn't Open File",
                                 f"Could not open the file:\n{e}")

    def _open_containing_folder(self, path):
        """Open (and, where supported, select the file within) its folder."""
        folder = os.path.dirname(os.path.abspath(path))
        try:
            if sys.platform == "win32":
                try:
                    subprocess.run(
                        ["explorer", "/select,", os.path.abspath(path)], check=False)
                except Exception:
                    os.startfile(folder)  # noqa: (Windows-only attribute)
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", path], check=False)
            else:
                subprocess.run(["xdg-open", folder], check=False)
        except Exception as e:
            messagebox.showerror("Couldn't Open Folder",
                                 f"Could not open the folder:\n{e}")

    # ------------------------------------------------------------------
    # Project save / load / reset
    # ------------------------------------------------------------------
    def _settings_dict(self):
        return {
            "rows": self.rows, "cols": self.cols, "auto_rows": self.auto_rows,
            "panel_order": self.panel_order,
            "h_spacing": self.h_spacing, "v_spacing": self.v_spacing, "margin": self.margin,
            "cell_size_mode": self.cell_size_mode,
            "custom_width": self.custom_width_entry.get() if hasattr(self, "custom_width_entry") else "",
            "custom_height": self.custom_height_entry.get() if hasattr(self, "custom_height_entry") else "",
            "label_style": self.label_style, "label_format": self.label_format,
            "label_position": self.label_position,
            "custom_labels": self.custom_labels_entry.get() if hasattr(self, "custom_labels_entry") else "",
            "font_family": self.font_family, "font_bold": self.font_bold,
            "font_size": self.font_size, "font_color": list(self.font_color),
            "custom_font_path": self.custom_font_path,
            "bg_color": list(self.bg_color), "transparent_bg": self.transparent_bg,
            "panel_border_enabled": self.panel_border_enabled,
            "panel_border_width": self.panel_border_width,
            "panel_border_color": list(self.panel_border_color),
            "grayscale_enabled": self.grayscale_enabled,
            "auto_contrast_enabled": self.auto_contrast_enabled,
            "figure_caption_text": self.figure_caption_text,
            "figure_caption_position": self.figure_caption_position,
            "caption_font_size": self.caption_font_size,
            "caption_color": list(self.caption_color),
            "scale_bar_enabled": self.scale_bar_enabled,
            "scale_bar_length_px": self.scale_bar_length_px,
            "scale_bar_label": self.scale_bar_label,
            "scale_bar_position": self.scale_bar_position,
            "scale_bar_color": list(self.scale_bar_color),
            "scale_bar_thickness": self.scale_bar_thickness,
            "output_format": self.output_format,
            "dpi": self.dpi_entry.get() if hasattr(self, "dpi_entry") else self.dpi_text,
            "target_width": self.target_width_entry.get() if hasattr(self, "target_width_entry") else "",
        }

    def _apply_settings_dict(self, s):
        def g(key, default): return s.get(key, default)  # noqa: E731

        self.rows = int(g("rows", self.rows))
        self.cols = int(g("cols", self.cols))
        self.auto_rows = bool(g("auto_rows", self.auto_rows))
        self.panel_order = g("panel_order", self.panel_order)
        self.h_spacing = int(g("h_spacing", self.h_spacing))
        self.v_spacing = int(g("v_spacing", self.v_spacing))
        self.margin = int(g("margin", self.margin))
        self.cell_size_mode = g("cell_size_mode", self.cell_size_mode)
        self.label_style = g("label_style", self.label_style)
        self.label_format = g("label_format", self.label_format)
        self.label_position = g("label_position", self.label_position)
        self.font_family = g("font_family", self.font_family)
        self.font_bold = bool(g("font_bold", self.font_bold))
        self.font_size = int(g("font_size", self.font_size))
        self.font_color = tuple(g("font_color", list(self.font_color)))
        self.custom_font_path = g("custom_font_path", self.custom_font_path)
        self.bg_color = tuple(g("bg_color", list(self.bg_color)))
        self.transparent_bg = bool(g("transparent_bg", self.transparent_bg))
        self.panel_border_enabled = bool(
            g("panel_border_enabled", self.panel_border_enabled))
        self.panel_border_width = int(
            g("panel_border_width", self.panel_border_width))
        self.panel_border_color = tuple(
            g("panel_border_color", list(self.panel_border_color)))
        self.grayscale_enabled = bool(
            g("grayscale_enabled", self.grayscale_enabled))
        self.auto_contrast_enabled = bool(
            g("auto_contrast_enabled", self.auto_contrast_enabled))
        self.figure_caption_text = g(
            "figure_caption_text", self.figure_caption_text)
        self.figure_caption_position = g(
            "figure_caption_position", self.figure_caption_position)
        self.caption_font_size = int(
            g("caption_font_size", self.caption_font_size))
        self.caption_color = tuple(
            g("caption_color", list(self.caption_color)))
        self.scale_bar_enabled = bool(
            g("scale_bar_enabled", self.scale_bar_enabled))
        self.scale_bar_length_px = int(
            g("scale_bar_length_px", self.scale_bar_length_px))
        self.scale_bar_label = g("scale_bar_label", self.scale_bar_label)
        self.scale_bar_position = g(
            "scale_bar_position", self.scale_bar_position)
        self.scale_bar_color = tuple(
            g("scale_bar_color", list(self.scale_bar_color)))
        self.scale_bar_thickness = int(
            g("scale_bar_thickness", self.scale_bar_thickness))
        self.output_format = g("output_format", self.output_format)

        custom_width = g("custom_width", "")
        custom_height = g("custom_height", "")
        custom_labels = g("custom_labels", "")
        dpi_text = str(g("dpi", self.dpi_text))
        target_width_text = str(g("target_width", ""))

        # ---- sync every widget's displayed state to match ----
        self.rows_slider.set(self.rows)
        self.rows_value_label.configure(text=str(self.rows))
        self.cols_slider.set(self.cols)
        self.cols_value_label.configure(text=str(self.cols))
        if self.auto_rows:
            self.auto_rows_checkbox.select()
        else:
            self.auto_rows_checkbox.deselect()
        self.rows_slider.configure(
            state="disabled" if self.auto_rows else "normal")
        self.panel_order_menu.set(self.panel_order)

        self.hspacing_slider.set(self.h_spacing)
        self.hspacing_value_label.configure(text=str(self.h_spacing))
        self.vspacing_slider.set(self.v_spacing)
        self.vspacing_value_label.configure(text=str(self.v_spacing))
        self.margin_slider.set(self.margin)
        self.margin_value_label.configure(text=str(self.margin))

        self.cell_size_menu.set(self.cell_size_mode)
        if self.cell_size_mode == "Custom size":
            self.custom_size_frame.pack(
                fill="x", pady=(0, 6), after=self.cell_size_menu)
        else:
            self.custom_size_frame.pack_forget()
        self.custom_width_entry.delete(0, "end")
        self.custom_width_entry.insert(0, str(custom_width))
        self.custom_height_entry.delete(0, "end")
        self.custom_height_entry.insert(0, str(custom_height))

        self.bg_swatch.configure(fg_color=self._rgb_to_hex(self.bg_color),
                                 hover_color=self._rgb_to_hex(self.bg_color),
                                 text_color=self._contrast_text_color(self.bg_color))
        if self.transparent_bg:
            self.transparent_checkbox.select()
        else:
            self.transparent_checkbox.deselect()

        if self.panel_border_enabled:
            self.border_checkbox.select()
        else:
            self.border_checkbox.deselect()
        self.border_width_slider.configure(
            state="normal" if self.panel_border_enabled else "disabled")
        self.border_width_slider.set(self.panel_border_width)
        self.border_width_value_label.configure(
            text=str(self.panel_border_width))
        self.border_color_swatch.configure(
            fg_color=self._rgb_to_hex(self.panel_border_color),
            hover_color=self._rgb_to_hex(self.panel_border_color),
            text_color=self._contrast_text_color(self.panel_border_color))

        if self.grayscale_enabled:
            self.grayscale_checkbox.select()
        else:
            self.grayscale_checkbox.deselect()
        if self.auto_contrast_enabled:
            self.auto_contrast_checkbox.select()
        else:
            self.auto_contrast_checkbox.deselect()

        self.label_style_menu.set(self.label_style)
        if self.label_style == "Custom list":
            self.custom_labels_entry.pack(
                fill="x", pady=(0, 6), after=self.label_style_menu)
        else:
            self.custom_labels_entry.pack_forget()
        self.custom_labels_entry.delete(0, "end")
        self.custom_labels_entry.insert(0, str(custom_labels))

        self.label_format_menu.set(self.label_format)
        self.label_position_menu.set(self.label_position)
        self.font_family_menu.set(self.font_family)
        if self.font_bold:
            self.bold_checkbox.select()
        else:
            self.bold_checkbox.deselect()
        self.font_size_slider.set(self.font_size)
        self.font_size_value_label.configure(text=str(self.font_size))
        self.font_color_swatch.configure(
            fg_color=self._rgb_to_hex(self.font_color),
            hover_color=self._rgb_to_hex(self.font_color),
            text_color=self._contrast_text_color(self.font_color))
        if self.custom_font_path:
            self.font_file_label.configure(
                text=os.path.basename(self.custom_font_path))
        else:
            self.font_file_label.configure(
                text="(none \u2014 using dropdown font)")

        self.caption_entry.delete(0, "end")
        self.caption_entry.insert(0, self.figure_caption_text)
        self.caption_position_menu.set(self.figure_caption_position)
        self.caption_font_size_slider.set(self.caption_font_size)
        self.caption_font_size_value_label.configure(
            text=str(self.caption_font_size))
        self.caption_color_swatch.configure(
            fg_color=self._rgb_to_hex(self.caption_color),
            hover_color=self._rgb_to_hex(self.caption_color),
            text_color=self._contrast_text_color(self.caption_color))

        if self.scale_bar_enabled:
            self.scale_bar_checkbox.select()
        else:
            self.scale_bar_checkbox.deselect()
        sb_state = "normal" if self.scale_bar_enabled else "disabled"
        for widget in (self.scale_bar_length_entry, self.scale_bar_label_entry,
                       self.scale_bar_thickness_slider, self.scale_bar_position_menu,
                       self.scale_bar_color_swatch):
            widget.configure(state=sb_state)
        self.scale_bar_length_entry.delete(0, "end")
        self.scale_bar_length_entry.insert(0, str(self.scale_bar_length_px))
        self.scale_bar_label_entry.delete(0, "end")
        self.scale_bar_label_entry.insert(0, self.scale_bar_label)
        self.scale_bar_position_menu.set(self.scale_bar_position)
        self.scale_bar_color_swatch.configure(
            fg_color=self._rgb_to_hex(self.scale_bar_color),
            hover_color=self._rgb_to_hex(self.scale_bar_color),
            text_color=self._contrast_text_color(self.scale_bar_color))
        self.scale_bar_thickness_slider.set(self.scale_bar_thickness)
        self.scale_bar_thickness_value_label.configure(
            text=str(self.scale_bar_thickness))

        self.format_menu.set(self.output_format)
        self.dpi_entry.delete(0, "end")
        self.dpi_entry.insert(0, dpi_text)
        self.target_width_entry.delete(0, "end")
        self.target_width_entry.insert(0, target_width_text)

        self.request_preview_update()

    def reset_to_defaults(self):
        if not messagebox.askyesno(
            "Reset Settings", "Reset all layout, label, and output settings to defaults? "
                "Your loaded photos will not be removed."):
            return
        self._set_defaults()
        self._apply_settings_dict(self._settings_dict_from_current_state())

    def _settings_dict_from_current_state(self):
        return {
            "rows": self.rows, "cols": self.cols, "auto_rows": self.auto_rows,
            "panel_order": self.panel_order,
            "h_spacing": self.h_spacing, "v_spacing": self.v_spacing, "margin": self.margin,
            "cell_size_mode": self.cell_size_mode,
            "custom_width": self.custom_cell_width, "custom_height": self.custom_cell_height,
            "label_style": self.label_style, "label_format": self.label_format,
            "label_position": self.label_position, "custom_labels": self.custom_labels_text,
            "font_family": self.font_family, "font_bold": self.font_bold,
            "font_size": self.font_size, "font_color": list(self.font_color),
            "custom_font_path": self.custom_font_path,
            "bg_color": list(self.bg_color), "transparent_bg": self.transparent_bg,
            "panel_border_enabled": self.panel_border_enabled,
            "panel_border_width": self.panel_border_width,
            "panel_border_color": list(self.panel_border_color),
            "grayscale_enabled": self.grayscale_enabled,
            "auto_contrast_enabled": self.auto_contrast_enabled,
            "figure_caption_text": self.figure_caption_text,
            "figure_caption_position": self.figure_caption_position,
            "caption_font_size": self.caption_font_size,
            "caption_color": list(self.caption_color),
            "scale_bar_enabled": self.scale_bar_enabled,
            "scale_bar_length_px": self.scale_bar_length_px,
            "scale_bar_label": self.scale_bar_label,
            "scale_bar_position": self.scale_bar_position,
            "scale_bar_color": list(self.scale_bar_color),
            "scale_bar_thickness": self.scale_bar_thickness,
            "output_format": self.output_format,
            "dpi": self.dpi_text, "target_width": self.target_width_text,
        }

    def save_project(self):
        file_path = filedialog.asksaveasfilename(
            title="Save Project", defaultextension=".json",
            filetypes=[("Figora Project", "*.json"), ("All Files", "*.*")])
        if not file_path:
            return
        data = {"version": 1, "image_paths": list(self.image_paths),
                "settings": self._settings_dict()}
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            messagebox.showinfo(
                "Project Saved", f"Project saved to:\n{file_path}")
        except Exception as e:
            messagebox.showerror(
                "Save Failed", f"Could not save project:\n{e}")

    def load_project(self):
        file_path = filedialog.askopenfilename(
            title="Load Project",
            filetypes=[("Figora Project", "*.json"), ("All Files", "*.*")])
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror(
                "Load Failed", f"Could not read project file:\n{e}")
            return

        missing = []
        loaded_images, loaded_paths = [], []
        for p in data.get("image_paths", []):
            try:
                loaded_images.append(self._load_image_file(p))
                loaded_paths.append(p)
            except Exception:
                missing.append(p)

        self.images, self.image_paths = loaded_images, loaded_paths
        self._apply_settings_dict(data.get("settings", {}))
        self.refresh_image_list_ui()
        self.request_preview_update()

        msg = f"Loaded project with {len(loaded_images)} photo(s)."
        if missing:
            msg += "\n\nThese files could not be found and were skipped:\n" + \
                "\n".join(missing)
        messagebox.showinfo("Project Loaded", msg)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------
    def _make_link_label(self, parent, text, url):
        lbl = customtkinter.CTkLabel(parent, text=text, text_color=("#1a73c7", "#5aa9ff"),
                                     cursor="hand2")
        lbl.bind("<Button-1>", lambda e: webbrowser.open(url))
        return lbl

    def show_about(self):
        about_window = customtkinter.CTkToplevel(self.root)
        about_window.title("About Figora")
        about_window.geometry("460x470")
        about_window.resizable(False, False)

        customtkinter.CTkLabel(
            about_window,
            text=(
                f"Figora  \u00b7  v{self.VERSION}\n\n"
                "Combine multiple photos into a single labeled figure\n"
                "for manuscripts, posters, and presentations.\n\n"
                "Live zoomable preview, panel reordering, label styles/\n"
                "positions, spacing/margin/border control, grayscale and\n"
                "contrast adjustment, a word-wrapped figure caption with\n"
                "its own size and color, a calibrated scale bar, project\n"
                "save/load, and export to PNG, TIFF, JPEG, or PDF."
            ),
            justify="center",
        ).pack(padx=20, pady=(20, 10))

        customtkinter.CTkLabel(
            about_window, text="Developed by Ahmed Abdelmageed",
            font=customtkinter.CTkFont(weight="bold")
        ).pack(pady=(0, 6))

        links_frame = customtkinter.CTkFrame(
            about_window, fg_color="transparent")
        links_frame.pack(pady=(0, 10))
        self._make_link_label(links_frame, "GitHub: github.com/asmpro7",
                              "https://github.com/asmpro7").pack(pady=1)
        self._make_link_label(links_frame, "ORCID: 0009-0002-7902-690X",
                              "https://orcid.org/0009-0002-7902-690X").pack(pady=1)
        self._make_link_label(links_frame, "LinkedIn: linkedin.com/in/asmpro",
                              "https://www.linkedin.com/in/asmpro/").pack(pady=1)
        self._make_link_label(links_frame, "Email: AhmedElSaeedMassad@gmail.com",
                              "mailto:AhmedElSaeedMassad@gmail.com").pack(pady=1)
        self._make_link_label(links_frame, "DOI: 10.5281/zenodo.22166513",
                              "https://doi.org/10.5281/zenodo.22166513").pack(pady=1)

        customtkinter.CTkButton(about_window, text="Close", command=about_window.destroy).pack(
            pady=(0, 15))

    @staticmethod
    def _rgb_to_hex(rgb):
        return "#%02x%02x%02x" % tuple(rgb[:3])

    @staticmethod
    def _hex_to_rgb(hex_color):
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))

    @staticmethod
    def _contrast_text_color(rgb):
        r, g, b = rgb[:3]
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return "#000000" if luminance > 0.6 else "#ffffff"

    @staticmethod
    def _safe_int(value, default):
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return default


if __name__ == "__main__":
    customtkinter.set_appearance_mode("Dark")
    customtkinter.set_default_color_theme("blue")

    root = customtkinter.CTk()
    app = FigoraApp(root)
    root.mainloop()
