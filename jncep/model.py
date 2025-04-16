from __future__ import annotations

from enum import Enum, auto

import attr


@attr.s
class Series:
    raw_data = attr.ib()
    series_id = attr.ib()

    volumes: list[Volume] = attr.ib(None)


@attr.s
class Volume:
    raw_data = attr.ib()
    volume_id = attr.ib()

    num: int = attr.ib()
    parts: list[Part] = attr.ib(None)
    cover: Image = attr.ib(None)
    series: Series = attr.ib(None)


@attr.s
class Part:
    raw_data = attr.ib()
    part_id = attr.ib()

    num_in_volume: int = attr.ib()
    volume: Volume = attr.ib(None)
    series: Series = attr.ib(None)
    content: str = attr.ib(None)
    images: list[Image] = attr.ib(None)

    epub_content = attr.ib(None)


@attr.s
class Image:
    url: str = attr.ib()
    content: bytes = attr.ib(None)
    local_filename: str = attr.ib(None)

    order_in_part: int = attr.ib(None)


class Language(Enum):
    DE = auto()
    EN = auto()
    FR = auto()
