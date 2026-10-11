"""D65/sRGB colour measurements and OKLCH conversion, without GUI dependencies.

Oklab matrices: Björn Ottosson, https://bottosson.github.io/posts/oklab/.
Relative luminance: WCAG 2.2 / IEC sRGB transfer function.
"""

import math


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4


def _rgb(hex_color: str) -> tuple[float, ...]:
    return tuple(int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5))


def luminance(hex_color: str) -> float:
    r, g, b = (_linear(channel) for channel in _rgb(hex_color))
    return .2126 * r + .7152 * g + .0722 * b


def contrast_ratio(foreground: str, background: str) -> float:
    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + .05) / (dark + .05)


def oklab(hex_color: str) -> tuple[float, float, float]:
    r, g, b = (_linear(channel) for channel in _rgb(hex_color))
    long_cone = (.4122214708 * r + .5363325363 * g + .0514459929 * b) ** (1 / 3)
    m = (.2119034982 * r + .6806995451 * g + .1073969566 * b) ** (1 / 3)
    s = (.0883024619 * r + .2817188376 * g + .6299787005 * b) ** (1 / 3)
    return (.2104542553 * long_cone + .7936177850 * m - .0040720468 * s,
            1.9779984951 * long_cone - 2.4285922050 * m + .4505937099 * s,
            .0259040371 * long_cone + .7827717662 * m - .8086757660 * s)


def _oklch_linear(lightness: float, chroma: float, hue: float) -> tuple[float, float, float]:
    a, b = chroma * math.cos(math.radians(hue)), chroma * math.sin(math.radians(hue))
    long_cone = (lightness + .3963377774 * a + .2158037573 * b) ** 3
    m = (lightness - .1055613458 * a - .0638541728 * b) ** 3
    s = (lightness - .0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * long_cone - 3.3077115913 * m + .2309699292 * s,
            -1.2684380046 * long_cone + 2.6097574011 * m - .3413193965 * s,
            -.0041960863 * long_cone - .7034186147 * m + 1.7076147010 * s)


def oklch_hex(lightness: float, chroma: float, hue: float) -> str:
    """Reduce chroma to fit sRGB, preserving hue/lightness; return Qt-ready hex."""
    rgb = _oklch_linear(lightness, chroma, hue)
    if not all(0 <= channel <= 1 for channel in rgb):
        low, high = 0., chroma
        for _ in range(24):
            middle = (low + high) / 2
            if all(0 <= channel <= 1 for channel in _oklch_linear(lightness, middle, hue)):
                low = middle
            else:
                high = middle
        rgb = _oklch_linear(lightness, low, hue)
    encoded = (12.92 * channel if channel <= .0031308 else 1.055 * channel ** (1 / 2.4) - .055 for channel in rgb)
    return "#" + "".join(f"{round(max(0., min(1., channel)) * 255):02x}" for channel in encoded)


def mix_oklab(first: str, second: str, factor: float) -> str:
    start, end = oklab(first), oklab(second)
    lightness, a, b = (x + max(0., min(1., factor)) * (y - x) for x, y in zip(start, end))
    return oklch_hex(lightness, math.hypot(a, b), math.degrees(math.atan2(b, a)))


def readable_mix(background: str, accent: str, text: str, factor: float, minimum: float = 4.5) -> str:
    """A heatmap may gain colour, but must not lose its label contrast."""
    factor = max(0., min(1., factor))
    if contrast_ratio(text, accent) >= minimum:
        return mix_oklab(background, accent, factor)
    low, high = 0., 1.
    for _ in range(20):
        middle = (low + high) / 2
        if contrast_ratio(text, mix_oklab(background, accent, middle)) >= minimum:
            low = middle
        else:
            high = middle
    return mix_oklab(background, accent, low * factor)
