"""Dragging a rectangle over a picture of the world, in the 3D viewport the panel stands beside.

While the operator runs the picture is drawn over the viewport's main region, dimming the scene behind it. The pointer
is read in that region's pixels and handed to :class:`Kernel.app.picture.Picker`, which is the whole interaction; what
is Blender's here is the drawing, the events, and where on the screen there is room for a picture.
"""

from __future__ import annotations

import math

import blf
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from ...Kernel.app import picture as app_picture
from . import plugin_data
from .picture_view import interface_scale

BACKDROP = (0.02, 0.025, 0.03, 0.92)
VEIL = (0.0, 0.0, 0.0, 0.4)
FRAME = (1.0, 1.0, 1.0, 0.3)
GRID = (1.0, 1.0, 1.0, 0.16)
MINIMUM_GRID_PIXELS = 12.0
FILL = (0.25, 0.85, 1.0, 0.07)
OUTLINE = (0.25, 0.85, 1.0, 1.0)
TEXT = (1.0, 1.0, 1.0, 1.0)
SHADOW = (0.0, 0.0, 0.0, 0.85)
OUTLINE_WIDTH = 2.0
RULER_WIDTH = 3.0
PADDING = 16.0
FONT_SIZE = 15.0
RULER_PIXELS = 180.0
RULER_LENGTHS = (10, 20, 50, 100, 200, 500, 1000, 2000, 5000)
MINIMUM_LEVEL_SIDE = 128
HELP = ("LMB drag: pick region    Wheel: zoom    MMB drag: pan    A: whole map    Home: fit view    "
        "Enter: keep as is    Esc: cancel")
ZOOM_IN = {"WHEELUPMOUSE", "WHEELINMOUSE"}
ZOOM_OUT = {"WHEELDOWNMOUSE", "WHEELOUTMOUSE"}
ACCEPT = {"RET", "NUMPAD_ENTER", "SPACE"}
CANCEL = {"ESC", "RIGHTMOUSE"}

#: What the next ``INVOKE_DEFAULT`` of the operator is for: (picture, rectangle, done, snap).
_pending = []


def request(picture, rectangle, done, snap=0.0):
    """Start the interaction. The operator takes what is asked of it from here because an operator
    is started with an event and properties, and a picture is neither."""
    _pending[:] = [(picture, rectangle, done, snap)]
    try:
        bpy.ops.ruri.region_picker("INVOKE_DEFAULT")
    finally:
        _pending.clear()


class Levels:
    """The picture as GPU textures at successive halvings, each made the first time a view needs it, so
    that a view is drawn from the one that is least too large for it: a texture sampled at a quarter of its
    size shimmers as the view moves, and the price of avoiding that is a third more memory."""

    def __init__(self, picture):
        self._pictures = [picture]
        self._built = {}

    def _level_for(self, zoom):
        base = self._pictures[0]
        level = 0 if zoom >= base.resolution else int(math.floor(math.log2(base.resolution / zoom)))
        while level > 0 and min(base.width, base.height) >> level < MINIMUM_LEVEL_SIDE:
            level -= 1
        return level

    def ensure(self, zoom):
        """Make what drawing at ``zoom`` pixels per world unit samples from. It makes datablocks, so it is
        never called from a draw."""
        level = self._level_for(zoom)
        while len(self._pictures) <= level:
            self._pictures.append(self._pictures[-1].halved())
        if level not in self._built:
            self._built[level] = _texture(self._pictures[level])

    def texture(self, zoom):
        """The built level nearest to the one ``zoom`` wants: a view the pointer has not moved since a
        resize still has something to draw from."""
        wanted = self._level_for(zoom)
        level = min(self._built, key=lambda built: (abs(built - wanted), built))
        return self._built[level][1]

    def release(self):
        for image, _texture_in_use in self._built.values():
            try:
                image.gl_free()
                bpy.data.images.remove(image)
            except ReferenceError:
                pass
        self._built.clear()


def _texture(picture):
    image = bpy.data.images.new("Ruri Region Picker", picture.width, picture.height, alpha=True, float_buffer=False)
    plugin_data.born(image)
    image.colorspace_settings.name = "Non-Color"
    image.alpha_mode = "STRAIGHT"
    image.pixels.foreach_set(picture.pixels.astype(np.float32).ravel() * np.float32(1.0 / 255.0))
    texture = gpu.texture.from_image(image)
    texture.filter_mode(True)
    texture.extend_mode("EXTEND")
    return image, texture


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------
def _fill(x0, y0, x1, y1, color):
    if x1 <= x0 or y1 <= y0:
        return
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "TRI_FAN", {"pos": ((x0, y0), (x1, y0), (x1, y1), (x0, y1))})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _line(points, color, width, closed=False):
    shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    coordinates = list(points) + ([points[0]] if closed else [])
    batch = batch_for_shader(shader, "LINE_STRIP", {"pos": coordinates})
    shader.bind()
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", color)
    batch.draw(shader)


def _segments(points, color, width):
    shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    batch = batch_for_shader(shader, "LINES", {"pos": points})
    shader.bind()
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", color)
    batch.draw(shader)


def _grid(view, snap, low, high):
    """The cell boundaries across the picture, where the world is made of cells."""
    if snap * view.zoom < MINIMUM_GRID_PIXELS:
        return
    rect = view.rect
    points = []
    column = math.ceil(rect[0] / snap)
    while column * snap < rect[2]:
        x = view.to_screen(column * snap, rect[1])[0]
        points += [(x, low[1]), (x, high[1])]
        column += 1
    row = math.ceil(rect[1] / snap)
    while row * snap < rect[3]:
        y = view.to_screen(rect[0], row * snap)[1]
        points += [(low[0], y), (high[0], y)]
        row += 1
    if points:
        _segments(points, GRID, 1.0)


def _frame(low, high, color, width):
    _line(((low[0], low[1]), (high[0], low[1]), (high[0], high[1]), (low[0], high[1])), color, width, closed=True)


def _text(x, y, text, size, color=TEXT):
    blf.size(0, size)
    blf.enable(0, blf.SHADOW)
    blf.shadow(0, 5, *SHADOW)
    blf.shadow_offset(0, 1, -1)
    blf.position(0, x, y, 0)
    blf.color(0, *color)
    blf.draw(0, text)
    blf.disable(0, blf.SHADOW)


def _text_width(text, size):
    blf.size(0, size)
    return blf.dimensions(0, text)[0]


def _ruler_length(zoom):
    fitting = [length for length in RULER_LENGTHS if length * zoom <= RULER_PIXELS]
    return fitting[-1] if fitting else RULER_LENGTHS[0]


def draw(picker, levels, width, height, size=FONT_SIZE):
    """Everything the overlay is, in the pixels of a ``width`` x ``height`` region whose origin is its
    bottom-left corner. ``picker`` must have been arranged and ``levels`` must have made a texture."""
    view = picker.view
    free_x, free_y, free_width, free_height = picker.area
    origin_x, origin_y = gpu.state.viewport_get()[:2]
    gpu.state.blend_set("ALPHA")
    _fill(0.0, 0.0, width, height, BACKDROP)

    gpu.state.scissor_test_set(True)
    gpu.state.scissor_set(int(origin_x + free_x), int(origin_y + free_y), int(free_width), int(free_height))
    low, high = view.corners(picker.picture.rect)
    shader = gpu.shader.from_builtin("IMAGE")
    batch = batch_for_shader(shader, "TRI_FAN", {"pos": ((low[0], low[1]), (high[0], low[1]), (high[0], high[1]),
                                                         (low[0], high[1])),
                                                 "texCoord": ((0, 0), (1, 0), (1, 1), (0, 1))})
    shader.bind()
    shader.uniform_sampler("image", levels.texture(view.zoom))
    batch.draw(shader)
    if picker.snap > 0:
        _grid(view, picker.snap, low, high)

    selection = picker.selection
    inner_low, inner_high = view.corners(selection)
    _fill(low[0], low[1], inner_low[0], high[1], VEIL)
    _fill(inner_high[0], low[1], high[0], high[1], VEIL)
    _fill(inner_low[0], low[1], inner_high[0], inner_low[1], VEIL)
    _fill(inner_low[0], inner_high[1], inner_high[0], high[1], VEIL)
    _fill(inner_low[0], inner_low[1], inner_high[0], inner_high[1], FILL)
    _frame(low, high, FRAME, 1.0)
    _frame(inner_low, inner_high, OUTLINE, OUTLINE_WIDTH)
    gpu.state.scissor_test_set(False)

    extent = "{0:.0f} x {1:.0f} m".format(selection[2] - selection[0], selection[3] - selection[1])
    if picker.snap > 0:
        extent += "  ({0:.0f} x {1:.0f} cells)".format((selection[2] - selection[0]) / picker.snap,
                                                      (selection[3] - selection[1]) / picker.snap)
    title_size = size * 1.2
    title_y = free_y + free_height - PADDING - title_size
    title_right = free_x + PADDING + _text_width(picker.picture.label, title_size)
    label_x = min(max(inner_low[0], free_x + PADDING), free_x + free_width - PADDING - _text_width(extent, size))
    ceiling = free_y + free_height - size - PADDING
    label_y = inner_high[1] + 6.0 if inner_high[1] + 6.0 <= ceiling else inner_high[1] - size - 6.0
    label_y = min(max(label_y, free_y + PADDING), ceiling)
    if label_x < title_right + size and label_y + size > title_y:
        label_y = title_y - size * 1.6
    _text(label_x, label_y, extent, size)
    _text(free_x + PADDING, title_y, picker.picture.label, title_size)
    length = _ruler_length(view.zoom)
    ruler_x = free_x + PADDING
    ruler_y = free_y + PADDING + size * 2.2
    _line(((ruler_x, ruler_y + 5.0), (ruler_x, ruler_y), (ruler_x + length * view.zoom, ruler_y),
           (ruler_x + length * view.zoom, ruler_y + 5.0)), TEXT, RULER_WIDTH)
    _text(ruler_x, ruler_y + 10.0, "{0} m".format(length), size)
    _text(free_x + PADDING, free_y + PADDING, HELP, size * 0.9)
    gpu.state.blend_set("NONE")


# ---------------------------------------------------------------------------
# Where there is room
# ---------------------------------------------------------------------------
def free_area(area, region):
    """The part of ``region`` no other region of ``area`` lies over, as (x, y, width, height) in the
    region's own pixels. The main region of a 3D viewport runs under its toolbar, header and sidebar
    where they overlap it, and a picture drawn there would be half behind them."""
    low_x, low_y, high_x, high_y = 0.0, 0.0, float(region.width), float(region.height)
    for other in area.regions:
        if other.type == "WINDOW" or other.width <= 1 or other.height <= 1:
            continue
        left = other.x - region.x
        bottom = other.y - region.y
        right = left + other.width
        top = bottom + other.height
        if right <= 0 or top <= 0 or left >= region.width or bottom >= region.height:
            continue
        if other.alignment == "LEFT":
            low_x = max(low_x, right)
        elif other.alignment == "RIGHT":
            high_x = min(high_x, left)
        elif other.alignment == "TOP":
            high_y = min(high_y, bottom)
        elif other.alignment == "BOTTOM":
            low_y = max(low_y, top)
    return low_x, low_y, max(high_x - low_x, 1.0), max(high_y - low_y, 1.0)


# ---------------------------------------------------------------------------
# One interaction
# ---------------------------------------------------------------------------
class Session:
    """The picker, the textures it draws from, and which region of which area it is drawn in."""

    def __init__(self, area, region, picture, rectangle, done, snap):
        self.area = area
        self.region_pointer = region.as_pointer()
        self.picker = app_picture.Picker(picture, rectangle, snap)
        self.levels = Levels(picture)
        self.done = done
        self.pressed = False
        self.handle = None

    def region(self):
        try:
            return next((one for one in self.area.regions if one.as_pointer() == self.region_pointer), None)
        except ReferenceError:
            return None

    def arrange(self, region):
        x, y, width, height = free_area(self.area, region)
        self.picker.arrange(x + PADDING, y + PADDING, max(width - 2 * PADDING, 1.0), max(height - 2 * PADDING, 1.0))

    def over_picture(self, x, y):
        area_x, area_y, area_width, area_height = self.picker.area
        return area_x <= x <= area_x + area_width and area_y <= y <= area_y + area_height

    def start(self):
        self.handle = bpy.types.SpaceView3D.draw_handler_add(_draw_callback, (self,), "WINDOW", "POST_PIXEL")

    def stop(self):
        if self.handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self.handle, "WINDOW")
            self.handle = None
        self.levels.release()


def _draw_callback(session):
    region = bpy.context.region
    if region is None or region.as_pointer() != session.region_pointer:
        return
    session.arrange(region)
    draw(session.picker, session.levels, region.width, region.height, FONT_SIZE * interface_scale())


class RURI_OT_region_picker(bpy.types.Operator):
    bl_idname = "ruri.region_picker"
    bl_label = "Pick Region"
    bl_description = "Drag a rectangle over the picture"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def invoke(self, context, event):
        if not _pending:
            return {"CANCELLED"}
        picture, rectangle, done, snap = _pending[0]
        area = context.area
        region = next((one for one in area.regions if one.type == "WINDOW"), None)
        if region is None:
            return {"CANCELLED"}
        self.session = Session(area, region, picture, rectangle, done, snap)
        self.session.arrange(region)
        self.session.levels.ensure(self.session.picker.view.zoom)
        self.session.start()
        context.window.cursor_modal_set("CROSSHAIR")
        context.workspace.status_text_set(HELP)
        context.window_manager.modal_handler_add(self)
        area.tag_redraw()
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        session = self.session
        region = session.region()
        if region is None or (event.value == "PRESS" and event.type in CANCEL):
            return self._finish(context, None)
        x = event.mouse_x - region.x
        y = event.mouse_y - region.y
        session.arrange(region)
        picker = session.picker
        if not (session.over_picture(x, y) or session.pressed or picker.panning):
            return {"PASS_THROUGH"}
        if event.type == "MOUSEMOVE":
            picker.move(x, y)
        elif event.type == "LEFTMOUSE":
            if event.value == "PRESS" and session.over_picture(x, y):
                session.pressed = True
                picker.press(x, y)
            elif event.value == "RELEASE" and session.pressed:
                session.pressed = False
                picked = picker.release(x, y)
                if picked is not None:
                    return self._finish(context, picked)
        elif event.type == "MIDDLEMOUSE":
            if event.value == "PRESS":
                picker.begin_pan(x, y)
            elif event.value == "RELEASE":
                picker.end_pan()
        elif event.type in ZOOM_IN or event.type in ZOOM_OUT:
            picker.zoom(x, y, 1 if event.type in ZOOM_IN else -1)
            session.levels.ensure(picker.view.zoom)
        elif event.value == "PRESS" and event.type == "A":
            picker.whole()
        elif event.value == "PRESS" and event.type == "HOME":
            picker.fit()
            session.levels.ensure(picker.view.zoom)
        elif event.value == "PRESS" and event.type in ACCEPT:
            return self._finish(context, picker.window)
        session.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def cancel(self, context):
        self._teardown(context)

    def _teardown(self, context):
        self.session.stop()
        if context.window is not None:
            context.window.cursor_modal_restore()
        if context.workspace is not None:
            context.workspace.status_text_set(None)
        try:
            self.session.area.tag_redraw()
        except ReferenceError:
            pass

    def _finish(self, context, rectangle):
        self._teardown(context)
        if rectangle is None:
            return {"CANCELLED"}
        try:
            self.session.done(context, rectangle)
        except Exception as failure:
            self.report({"ERROR"}, "{0}: {1}".format(type(failure).__name__, failure))
            return {"CANCELLED"}
        return {"FINISHED"}


def register():
    bpy.utils.register_class(RURI_OT_region_picker)


def unregister():
    bpy.utils.unregister_class(RURI_OT_region_picker)
