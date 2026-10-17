"""A raster that stands for a rectangle of the world, and the one geometry of looking at it.

Nothing here knows what the pixels depict or which application shows them. A
:class:`Picture` is what a panel draws and a user points into; a
:class:`PictureView` is where it sits in a drawing area, and the ONLY place a
world point and a screen point are turned into one another -- so what an overlay
draws and what a click is read back as cannot disagree.

Rows run from the rectangle's minimum Z edge up and columns from its minimum X
edge across, which is the order every host's image buffer already has.
"""

from __future__ import annotations

import math

import numpy as np

#: The smallest side, in world units, a picked rectangle may have. A click that
#: barely moved is a rectangle of nothing, which no window can be read for.
MINIMUM_SIDE = 1.0


class Picture:
    """``pixels`` is (height, width, 4) unsigned bytes covering ``rect`` =
    (min_x, min_z, max_x, max_z); ``label`` is what a person calls what it shows."""

    __slots__ = ("rect", "pixels", "label")

    def __init__(self, rect, pixels, label=""):
        if pixels.ndim != 3 or pixels.shape[2] != 4 or pixels.dtype != np.uint8:
            raise ValueError("a picture is height x width x RGBA of bytes, got {0} {1}".format(
                pixels.shape, pixels.dtype))
        self.rect = tuple(float(value) for value in rect)
        self.pixels = pixels
        self.label = label

    @property
    def width(self):
        return self.pixels.shape[1]

    @property
    def height(self):
        return self.pixels.shape[0]

    @property
    def resolution(self):
        """Pixels per world unit along X."""
        return self.width / (self.rect[2] - self.rect[0])

    def halved(self):
        """The same rectangle at half the pixels along each side, each pixel the average of the four it
        covers; a side with an odd count repeats its last pixels."""
        source = self.pixels
        height, width = source.shape[:2]
        if height % 2 or width % 2:
            source = np.pad(source, ((0, height % 2), (0, width % 2), (0, 0)), mode="edge")
        total = source[0::2, 0::2].astype(np.uint16)
        total += source[0::2, 1::2]
        total += source[1::2, 0::2]
        total += source[1::2, 1::2]
        total += 2
        return Picture(self.rect, (total >> 2).astype(np.uint8), self.label)

    def __repr__(self):
        return "<Picture {0} {1}x{2}>".format(self.label, self.width, self.height)


def normalised(first, second):
    """The rectangle two world points span, as (min_x, min_z, max_x, max_z)."""
    return (min(first[0], second[0]), min(first[1], second[1]),
            max(first[0], second[0]), max(first[1], second[1]))


def snapped(rect, cell):
    """``rect`` grown outward to the grid of ``cell``-sided squares laid from the origin: the squares it meets, as one
    rectangle. A ``cell`` of 0 is no grid."""
    if cell <= 0:
        return tuple(rect)
    cell = float(cell)
    return (math.floor(rect[0] / cell) * cell, math.floor(rect[1] / cell) * cell,
            math.ceil(rect[2] / cell) * cell, math.ceil(rect[3] / cell) * cell)


def clamped(rect, bounds):
    """``rect`` pulled inside ``bounds``, never thinner than :data:`MINIMUM_SIDE`.
    A rectangle that sits wholly outside comes back as the nearest sliver of the
    bounds, so a pick always means something."""
    min_x, min_z, max_x, max_z = rect
    bounds_min_x, bounds_min_z, bounds_max_x, bounds_max_z = bounds
    min_x = min(max(min_x, bounds_min_x), bounds_max_x - MINIMUM_SIDE)
    min_z = min(max(min_z, bounds_min_z), bounds_max_z - MINIMUM_SIDE)
    max_x = max(min(max_x, bounds_max_x), min_x + MINIMUM_SIDE)
    max_z = max(min(max_z, bounds_max_z), min_z + MINIMUM_SIDE)
    return (min_x, min_z, max_x, max_z)


class PictureView:
    """Where a rectangle of the world sits in a drawing area of ``width`` x
    ``height`` pixels whose origin is its bottom-left corner: ``zoom`` pixels per
    world unit and the pixel the rectangle's minimum corner lands on."""

    __slots__ = ("rect", "zoom", "origin_x", "origin_y", "minimum_zoom", "maximum_zoom")

    def __init__(self, rect, maximum_zoom=64.0):
        self.rect = tuple(float(value) for value in rect)
        self.zoom = 1.0
        self.origin_x = 0.0
        self.origin_y = 0.0
        self.minimum_zoom = 0.0
        self.maximum_zoom = float(maximum_zoom)

    @property
    def span(self):
        return (self.rect[2] - self.rect[0], self.rect[3] - self.rect[1])

    def fit(self, width, height, margin=0.0):
        """Show all of the rectangle, as large as fits, centred. What zooming out
        can never go past."""
        span_x, span_z = self.span
        self.zoom = max(min((width - 2.0 * margin) / span_x, (height - 2.0 * margin) / span_z), 1e-6)
        self.minimum_zoom = self.zoom * 0.5
        self.origin_x = (width - span_x * self.zoom) * 0.5
        self.origin_y = (height - span_z * self.zoom) * 0.5

    def to_screen(self, x, z):
        return (self.origin_x + (x - self.rect[0]) * self.zoom,
                self.origin_y + (z - self.rect[1]) * self.zoom)

    def to_world(self, screen_x, screen_y):
        return (self.rect[0] + (screen_x - self.origin_x) / self.zoom,
                self.rect[1] + (screen_y - self.origin_y) / self.zoom)

    def zoom_about(self, screen_x, screen_y, factor):
        """Scale by ``factor`` keeping the world point under the pixel where it is."""
        x, z = self.to_world(screen_x, screen_y)
        self.zoom = min(max(self.zoom * factor, self.minimum_zoom), self.maximum_zoom)
        self.origin_x = screen_x - (x - self.rect[0]) * self.zoom
        self.origin_y = screen_y - (z - self.rect[1]) * self.zoom

    def pan(self, delta_x, delta_y):
        self.origin_x += delta_x
        self.origin_y += delta_y

    def corners(self, rect):
        """A world rectangle as its two opposite screen corners."""
        low = self.to_screen(rect[0], rect[1])
        high = self.to_screen(rect[2], rect[3])
        return low, high


#: How far, in pixels, the pointer has to travel before a press is a drag. A press that
#: stayed under it is a click, which picks nothing.
DRAG_THRESHOLD = 6.0
#: What one step of a wheel scales the view by.
ZOOM_STEP = 1.25


class Picker:
    """Dragging a rectangle over a picture: the interaction, with no application in it.

    A host feeds it the pointer in the pixels of its drawing area and draws what it
    says -- ``view`` places the picture, ``selection`` is the rectangle to outline.
    Pressing starts a drag, releasing it picks the rectangle between the two points
    unless the pointer barely moved; the wheel zooms about the pointer and a pan
    moves the picture under it. A ``snap`` is the side of the cells the world is made
    of where something can only be taken a cell at a time: what is picked is then the
    cells the pointer's rectangle meets."""

    __slots__ = ("picture", "view", "window", "snap", "_area", "_anchor", "_current", "_panning")

    def __init__(self, picture, rectangle=None, snap=0.0):
        self.picture = picture
        self.view = PictureView(picture.rect)
        self.snap = float(snap)
        self.window = self._shaped(rectangle or picture.rect)
        self._area = None
        self._anchor = None
        self._current = None
        self._panning = None

    def arrange(self, x, y, width, height, margin=24.0):
        """Put the picture in the part of the drawing area that is free: ``width`` x ``height`` pixels
        whose bottom-left corner is at (``x``, ``y``). Returns whether that changed anything."""
        area = (x, y, width, height)
        if area == self._area:
            return False
        self._area = area
        self.view.fit(width, height, margin)
        self.view.pan(x, y)
        return True

    @property
    def area(self):
        """The part of the drawing area the picture is arranged in, as (x, y, width, height)."""
        return self._area

    @property
    def panning(self):
        return self._panning is not None

    @property
    def selection(self):
        """The rectangle to outline: the one being dragged, else the window a pick would leave."""
        if self._anchor is None:
            return self.window
        return self._shaped(normalised(self._anchor, self._current))

    def _shaped(self, rect):
        """A rectangle as this picker offers it: inside the picture, then out to the cells it meets."""
        return snapped(clamped(rect, self.picture.rect), self.snap)

    def _world(self, x, y):
        world_x, world_z = self.view.to_world(x, y)
        rect = self.picture.rect
        return (min(max(world_x, rect[0]), rect[2]), min(max(world_z, rect[1]), rect[3]))

    def press(self, x, y):
        self._anchor = self._current = self._world(x, y)

    def move(self, x, y):
        if self._panning is not None:
            self.view.pan(x - self._panning[0], y - self._panning[1])
            self._panning = (x, y)
        elif self._anchor is not None:
            self._current = self._world(x, y)

    def release(self, x, y):
        """The rectangle this drag picked, or None when it was only a click (or no drag was on)."""
        if self._anchor is None:
            return None
        self.move(x, y)
        anchor, current = self._anchor, self._current
        self._anchor = self._current = None
        first, second = self.view.to_screen(*anchor), self.view.to_screen(*current)
        if abs(first[0] - second[0]) < DRAG_THRESHOLD and abs(first[1] - second[1]) < DRAG_THRESHOLD:
            return None
        self.window = self._shaped(normalised(anchor, current))
        return self.window

    def begin_pan(self, x, y):
        self._panning = (x, y)

    def end_pan(self):
        self._panning = None

    def zoom(self, x, y, steps):
        self.view.zoom_about(x, y, ZOOM_STEP ** steps)

    def whole(self):
        """The window is the whole picture again."""
        self.window = self._shaped(self.picture.rect)
        return self.window

    def fit(self):
        if self._area is not None:
            x, y, width, height = self._area
            self._area = None
            self.arrange(x, y, width, height)
