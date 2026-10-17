"""The picture a panel shows: a map as a preview icon, with the rectangle a pick would take outlined on it.

A preview icon is the one thing Blender lays out inside a panel that is made of pixels the add-on owns, so the
picture is cut down to a square of ``CANVAS`` pixels once per picture and only the outline is drawn again when
the rectangle moves. The icon is square, so the picture sits in the middle of it and the rest is left clear.
"""

from __future__ import annotations

import bpy
import bpy.utils.previews
import numpy as np

CANVAS = 512
ICON = 32
BACKGROUND = np.array((0.09, 0.10, 0.12), dtype=np.float32)
OUTSIDE_VEIL = 0.4
OUTLINE = np.array((0.25, 0.85, 1.0), dtype=np.float32)
OUTLINE_PIXELS = 2
#: Width of one UI unit before the user's scale, in pixels, and what the panel keeps for its own margins.
UNIT_PIXELS = 20.0
MARGIN_UNITS = 3.0
MINIMUM_UNITS = 6.0

_previews = []
_canvas = []
_drawn = []


def register():
    _previews[:] = [bpy.utils.previews.new()]


def unregister():
    for collection in _previews:
        bpy.utils.previews.remove(collection)
    _previews.clear()
    _canvas.clear()
    _drawn.clear()


def draw(layout, picture, window, context):
    """Put the picture into ``layout`` at the width of the region it is drawn in, ``window`` outlined on it."""
    layout.template_icon(icon_value=_icon(picture, picture.rect if window is None else window),
                         scale=_units(context))


def interface_scale():
    """Pixels per pixel of the interface's own size on this screen: the display's DPI and the user's resolution scale."""
    preferences = bpy.context.preferences
    return preferences.system.dpi / 72.0 * preferences.view.ui_scale


def _units(context):
    return max(MINIMUM_UNITS, context.region.width / (UNIT_PIXELS * interface_scale()) - MARGIN_UNITS)


def _icon(picture, window):
    preview = _previews[0].get("picture") or _previews[0].new("picture")
    edge = tuple(round(value, 2) for value in window)
    if not _drawn or _drawn[0][0] is not picture or _drawn[0][1] != edge:
        if tuple(preview.image_size) != (CANVAS, CANVAS):
            preview.image_size = (CANVAS, CANVAS)
            preview.icon_size = (ICON, ICON)
        canvas, geometry = _canvas_of(picture)
        image = _outlined(canvas, geometry, picture.rect, window)
        preview.image_pixels_float.foreach_set(image.ravel())
        preview.icon_pixels_float.foreach_set(_icon_pixels(image, preview.icon_size).ravel())
        _drawn[:] = [(picture, edge)]
    return preview.icon_id


def _canvas_of(picture):
    if _canvas and _canvas[0][0] is picture:
        return _canvas[0][1], _canvas[0][2]
    level = picture
    while max(level.width, level.height) >= 2 * CANVAS:
        level = level.halved()
    scale = CANVAS / max(level.width, level.height)
    width = max(1, round(level.width * scale))
    height = max(1, round(level.height * scale))
    rows = np.minimum((np.arange(height) / scale).astype(np.intp), level.height - 1)
    columns = np.minimum((np.arange(width) / scale).astype(np.intp), level.width - 1)
    sample = level.pixels[rows[:, None], columns[None, :]].astype(np.float32) * np.float32(1.0 / 255.0)
    alpha = sample[..., 3:4]
    canvas = np.zeros((CANVAS, CANVAS, 4), dtype=np.float32)
    offset_x = (CANVAS - width) // 2
    offset_y = (CANVAS - height) // 2
    canvas[offset_y:offset_y + height, offset_x:offset_x + width, :3] = sample[..., :3] * alpha + BACKGROUND * (1.0 - alpha)
    canvas[offset_y:offset_y + height, offset_x:offset_x + width, 3] = 1.0
    geometry = (offset_x, offset_y, width, height)
    _canvas[:] = [(picture, canvas, geometry)]
    return canvas, geometry


def _outlined(canvas, geometry, rect, window):
    """The canvas with everything outside ``window`` dimmed and its edge drawn."""
    offset_x, offset_y, width, height = geometry
    span_x = rect[2] - rect[0]
    span_z = rect[3] - rect[1]
    low_x = offset_x + int(round(min(max((window[0] - rect[0]) / span_x, 0.0), 1.0) * width))
    high_x = offset_x + int(round(min(max((window[2] - rect[0]) / span_x, 0.0), 1.0) * width))
    low_y = offset_y + int(round(min(max((window[1] - rect[1]) / span_z, 0.0), 1.0) * height))
    high_y = offset_y + int(round(min(max((window[3] - rect[1]) / span_z, 0.0), 1.0) * height))
    high_x = max(high_x, low_x + OUTLINE_PIXELS)
    high_y = max(high_y, low_y + OUTLINE_PIXELS)
    image = canvas.copy()
    image[offset_y:offset_y + height, offset_x:offset_x + width, :3] *= OUTSIDE_VEIL
    image[low_y:high_y, low_x:high_x, :3] = canvas[low_y:high_y, low_x:high_x, :3]
    edge = OUTLINE_PIXELS
    for rows, columns in ((slice(low_y, low_y + edge), slice(low_x, high_x)),
                          (slice(high_y - edge, high_y), slice(low_x, high_x)),
                          (slice(low_y, high_y), slice(low_x, low_x + edge)),
                          (slice(low_y, high_y), slice(high_x - edge, high_x))):
        image[rows, columns, :3] = OUTLINE
    return image


def _icon_pixels(image, size):
    rows = np.arange(size[1]) * CANVAS // size[1]
    columns = np.arange(size[0]) * CANVAS // size[0]
    return image[rows[:, None], columns[None, :]]
