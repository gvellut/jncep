from __future__ import annotations

import string
from typing import TYPE_CHECKING

from .utils import to_safe_filename, to_safe_foldername

if TYPE_CHECKING:
    from .model import Series, Volume, Part
    from .namegen import FC

__all__ = ["legacy_title", "legacy_filename", "legacy_folder"]


def legacy_title(series: Series, volumes: list[Volume], parts: list[Part], fc: FC) -> str:
    """Generates the EPUB title using the legacy logic."""
    if len(parts) == 1:
        # single part
        part = parts[0]
        title_base = part.raw_data.title

        suffix = ""
        is_final = fc.final
        if is_final:
            # TODO i18n
            suffix = " [Final]"

        title = f"{title_base}{suffix}"
    else:
        if len(volumes) > 1:
            # multiple volumes
            title_base = series.raw_data.title

            # ordered already
            volume_nums = [str(v.num) for v in volumes]
            volume_nums = ", ".join(volume_nums[:-1]) + " & " + volume_nums[-1]
            # TODO i18n
            volume_segment = f"Volumes {volume_nums}"

            volume_num0 = parts[0].volume.num
            part_num0 = parts[0].num_in_volume
            volume_num1 = parts[-1].volume.num
            part_num1 = parts[-1].num_in_volume

            # check only last part in the epub
            suffix = ""
            is_final = fc.final
            if is_final:
                # TODO i18n
                suffix = " - Final"

            # TODO i18n
            part_segment = (
                f"Parts {volume_num0}.{part_num0} to {volume_num1}.{part_num1}{suffix}"
            )

            if title_base[-1] in string.punctuation:
                # like JNC : no double punctuation mark
                colon = ""
            else:
                colon = ":"
            title = f"{title_base}{colon} {volume_segment} [{part_segment}]"

        else:
            # single volume
            volume = volumes[0]
            title_base = volume.raw_data.title

            part_num0 = parts[0].num_in_volume
            part_num1 = parts[-1].num_in_volume

            is_complete = fc.complete
            is_final = fc.final
            if is_complete:
                # TODO i18n
                part_segment = "Complete"
            else:
                # check the last part in the epub
                suffix = ""
                if is_final:
                    # TODO i18n
                    suffix = " - Final"
                part_segment = f"Parts {part_num0} to {part_num1}{suffix}"

            title = f"{title_base} [{part_segment}]"
    return title


def legacy_filename(series: Series, volumes: list[Volume], parts: list[Part], fc: FC) -> str:
    """Generates the EPUB filename using the legacy logic."""
    title = legacy_title(series, volumes, parts, fc)
    return to_safe_filename(title)


def legacy_folder(series: Series, volumes: list[Volume], parts: list[Part], fc: FC) -> str:
    """Generates the EPUB folder name using the legacy logic."""
    return to_safe_foldername(series.raw_data.title)