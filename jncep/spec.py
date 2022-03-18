import logging
import re

import attr

logger = logging.getLogger(__name__)

RANGE_SEP = ":"

SERIES = "ALL_SERIES"
VOLUME = "ALL_VOLUME"
PART = "SINGLE_PART"
START_OF_VOLUME = "START_OF_VOLUME"
END_OF_VOLUME = "END_OF_VOLUME"
START_OF_SERIES = "START_OF_SERIES"
END_OF_SERIES = "END_OF_SERIES"


@attr.s
class Single:
    type_ = attr.ib()
    spec = attr.ib()

    def has_volume(self, volume) -> bool:
        if self.type_ == SERIES:
            return True
        elif self.type_ == VOLUME:
            return self.spec == volume.num
        # part
        vn, _ = self.spec
        return volume.num == vn

    def has_part(self, ref_part) -> bool:
        # assume has_volume is True if has_part is checked
        if self.type_ in (SERIES, VOLUME):
            return True
        # part
        _, pn = self.spec
        return ref_part.num_in_volume == pn


@attr.s
class Interval:
    start = attr.ib()
    end = attr.ib()

    def has_volume(self, volume) -> bool:
        if self.start == START_OF_SERIES:
            # spec is a part (START_OF / END_OF cannot happen together)
            vn, _ = self.end.spec
            return volume.num <= vn

        vn, _ = self.start.spec
        if self.end == END_OF_SERIES:
            return volume.num >= vn

        vn2, _ = self.end.spec
        return vn <= volume.num <= vn2

    def has_part(self, ref_part) -> bool:
        if self.start == START_OF_SERIES:
            # spec is a part
            vn, pn = self.end.spec
            if ref_part.volume.num < vn:
                return True
            # same volume
            return ref_part.num_in_volume <= pn

        vn, pn = self.start.spec
        if self.end == END_OF_SERIES:
            if ref_part.volume.num > vn:
                return True
            # same volume
            return ref_part.num_in_volume >= pn

        vn2, pn2 = self.end.spec
        if vn < ref_part.volume.num < vn2:
            return True

        if vn == vn2:
            return ref_part.volume.num == vn and pn <= ref_part.num_in_volume <= pn2

        return (ref_part.volume.num == vn and ref_part.num_in_volume >= pn) or (
            ref_part.volume.num == vn2 and ref_part.num_in_volume <= pn2
        )


def to_relative_spec_from_part(part):
    volume_number = part.volume.num
    part_number = part.num_in_volume
    return f"{volume_number}.{part_number}"


def analyze_part_specs(part_specs):
    """v(.p):v2(.p) or v(.p): or :v(.p) or v(.p) or :"""

    part_specs = part_specs.strip()

    if part_specs == RANGE_SEP:
        return Single(SERIES, None)

    return _analyze_volume_part_specs(part_specs)


def _analyze_volume_part_specs(part_specs):
    sides = part_specs.split(RANGE_SEP)
    if len(sides) > 2:
        raise ValueError("Multiple ':' in part specs")

    reg = r"^\s*(\d+)(?:\.(\d+))?\s*$"
    if len(sides) == 1:
        # not a range: single part
        m = re.match(reg, sides[0])
        if not m:
            raise ValueError(
                "Specification must be a of the form 'vol[.part]' (part is optional)"
            )
        fv = int(m.group(1))
        if m.group(2):
            # only the part specified
            fp = int(m.group(2))
            return Single(PART, (fv, fp))
        else:
            # full volume
            return Single(VOLUME, fv)

    # range
    m1 = re.match(reg, sides[0])
    m2 = re.match(reg, sides[1])
    if (
        (not m1 and not m2)
        # left side not valid
        or (not m1 and len(sides[0]) > 0)
        # right side not valid
        or (not m2 and len(sides[1]) > 0)
    ):
        msg = (
            "Part specification must be vol[.part]:vol[.part] or vol[.part]: or "
            ":vol[.part]"
        )
        raise ValueError(msg)

    if m1:
        fv = int(m1.group(1))
        if m1.group(2):
            fp = int(m1.group(2))
        else:
            fp = START_OF_VOLUME
        start = Single(PART, (fv, fp))
    else:
        start = START_OF_SERIES

    if m2:
        lv = int(m2.group(1))
        if m2.group(2):
            lp = int(m2.group(2))
        else:
            lp = END_OF_VOLUME
        end = Single(PART, (lv, lp))
    else:
        end = END_OF_SERIES

    # both sides
    return Interval(start, end)
