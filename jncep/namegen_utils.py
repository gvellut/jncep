from __future__ import annotations

from collections import namedtuple
import string

from .model import Part, Series, Volume
from .utils import (
    to_safe_filename,
    to_safe_foldername,
)

__all__ = [
    "default_title",
    "default_filename",
    "default_folder",
    "Series",
    "Volume",
    "Part",
    "FC",
    "to_safe_foldername",
    "to_safe_filename",
]

FC = namedtuple("FC", "final complete")


def default_title(
    series: Series, volumes: list[Volume], parts: list[Part], fc: FC
) -> str:
    if len(parts) == 1:
        part = parts[0]
        title_base = part.raw_data.title
        suffix = " [Final]" if fc.final else ""
        title = f"{title_base}{suffix}"
    else:
        if len(volumes) > 1:
            title_base = series.raw_data.title
            volume_nums = [str(v.num) for v in volumes]
            volume_nums_str = ", ".join(volume_nums[:-1]) + " & " + volume_nums[-1]
            volume_segment = f"Volumes {volume_nums_str}"
            part_segment = (
                f"Parts {parts[0].volume.num}.{parts[0].num_in_volume} "
                f"to {parts[-1].volume.num}.{parts[-1].num_in_volume}"
            )
            if fc.final:
                part_segment += " - Final"
            colon = "" if title_base[-1] in string.punctuation else ":"
            title = f"{title_base}{colon} {volume_segment} [{part_segment}]"
        else:
            volume = volumes[0]
            title_base = volume.raw_data.title
            if fc.complete:
                part_segment = "Complete"
            else:
                part_segment = (
                    f"Parts {parts[0].num_in_volume} to {parts[-1].num_in_volume}"
                )
                if fc.final:
                    part_segment += " - Final"
            title = f"{title_base} [{part_segment}]"
    return title


def default_filename(
    series: Series, volumes: list[Volume], parts: list[Part], fc: FC
) -> str:
    title = default_title(series, volumes, parts, fc)
    return _default_filename_from_title(title)


def _default_filename_from_title(title):
    # basic
    return to_safe_filename(title)


def default_folder(
    series: Series, volumes: list[Volume], parts: list[Part], fc: FC
) -> str:
    return to_safe_foldername(series.raw_data.title)
