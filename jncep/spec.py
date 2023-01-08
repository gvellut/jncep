import logging
import re

import attr

logger = logging.getLogger(__name__)

RANGE_SEP = ":"

SERIES = "SERIES_ALL"
VOLUME = "VOLUME_ALL"
PART = "SINGLE_PART"
START_OF_VOLUME = "START_OF_VOLUME"
END_OF_VOLUME = "END_OF_VOLUME"
START_OF_SERIES = "START_OF_SERIES"
END_OF_SERIES = "END_OF_SERIES"


class SpecError(Exception):
    pass


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

    def has_part(self, part) -> bool:
        if self.type_ == SERIES:
            return True

        if not self.has_volume(part.volume):
            return False
        if self.type_ == VOLUME:
            return True

        _, pn = self.spec
        return part.num_in_volume == pn

    def normalize_and_verify(self, series):
        if self.type_ == SERIES:
            return
        elif self.type_ == VOLUME:
            original_spec = self.spec
            self.spec = _normalize_volume(self.spec, series)
            if 1 <= self.spec <= len(series.volumes):
                return
            raise SpecError(f"Bad spec for series: Volume '{original_spec}' not found")
        # part
        vn, pn = self.spec
        original_spec = self.spec

        vn = _normalize_volume(vn, series)
        self.spec = (vn, pn)
        if vn < 1 or vn > len(series.volumes):
            raise SpecError(
                f"Bad spec for series: Volume '{original_spec[0]}' not found"
            )

        volume = series.volumes[vn - 1]
        if 1 <= pn <= len(volume.parts):
            return
        raise SpecError(
            f"Bad spec for series: Part '{original_spec[0]}.{original_spec[1]}' "
            "not found"
        )


@attr.s
class Interval:
    start = attr.ib()
    end = attr.ib()

    def has_volume(self, volume) -> bool:
        if self.start == START_OF_SERIES:
            # spec is a tuple (START_OF / END_OF cannot happen together)
            # if analyse_spec is used
            vn2, _ = self.end.spec
            return volume.num <= vn2

        vn, _ = self.start.spec
        if self.end == END_OF_SERIES:
            return volume.num >= vn

        vn2, _ = self.end.spec
        return vn <= volume.num <= vn2

    def has_part(self, part) -> bool:
        if self.start == START_OF_SERIES:
            # spec is a tuple (see comment in has_volume)
            vn2, pn2 = self.end.spec
            if part.volume.num < vn2:
                return True

            if part.volume.num > vn2:
                return False

            # same volume
            if pn2 == END_OF_VOLUME:
                return True

            return part.num_in_volume <= pn2

        # spec is a tuple
        vn, pn = self.start.spec
        if self.end == END_OF_SERIES:
            if part.volume.num > vn:
                return True

            if part.volume.num < vn:
                return False

            # same volume
            if pn == START_OF_VOLUME:
                return True

            return part.num_in_volume >= pn

        vn2, pn2 = self.end.spec
        if vn < part.volume.num < vn2:
            return True

        if part.volume.num < vn or part.volume.num > vn2:
            return False

        if vn == vn2:
            if pn == START_OF_VOLUME:
                if pn2 == END_OF_VOLUME:
                    return True

                return part.num_in_volume <= pn2
            else:
                if pn2 == END_OF_VOLUME:
                    return part.num_in_volume >= pn

                return pn <= part.num_in_volume <= pn2
        else:
            if part.volume.num == vn:
                if pn == START_OF_VOLUME:
                    return True

                return part.num_in_volume >= pn
            else:
                assert part.volume.num == vn2
                if pn2 == END_OF_VOLUME:
                    return True

                return part.num_in_volume <= pn2

    def normalize_and_verify(self, series):
        if self.start != START_OF_SERIES:
            vn, pn = self.start.spec
            original_spec1 = self.start.spec
            vn = _normalize_volume(vn, series)
            self.start.spec = (vn, pn)

            if vn < 1 or vn > len(series.volumes):
                raise SpecError(
                    f"Bad left spec for series: Volume '{original_spec1[0]}' not found"
                )

            if pn != START_OF_VOLUME:
                volume = series.volumes[vn - 1]
                if pn < 1 or pn > len(volume.parts):
                    raise SpecError(
                        "Bad left spec for series: Part "
                        f"'{original_spec1[0]}.{original_spec1[1]}' "
                        "not found"
                    )

        if self.end != END_OF_SERIES:
            vn, pn = self.end.spec
            original_spec2 = self.end.spec
            vn = _normalize_volume(vn, series)
            self.end.spec = (vn, pn)

            if vn < 1 or vn > len(series.volumes):
                raise SpecError(
                    f"Bad right spec for series: Volume '{original_spec2[0]}' "
                    "not found"
                )

            if pn != END_OF_VOLUME:
                volume = series.volumes[vn - 1]
                if pn < 1 or pn > len(volume.parts):
                    raise SpecError(
                        "Bad right spec for series: Part "
                        f"'{original_spec2[0]}.{original_spec2[1]}' "
                        "not found"
                    )

        # already tested that both sides are valid in the series
        # test if left <= right
        if self.start != START_OF_SERIES and self.end != END_OF_SERIES:
            vn1, pn1 = self.start.spec
            vn2, pn2 = self.end.spec

            if vn2 > vn1:
                return

            if vn2 < vn1:
                raise SpecError(
                    f"Bad spec for series: Volume '{original_spec2[0]}' is before "
                    f"Volume '{original_spec1[0]}'"
                )

            # vn1 == vn2:
            if pn1 != START_OF_VOLUME and pn2 != END_OF_VOLUME:
                if pn2 < pn1:
                    raise SpecError(
                        "Bad spec for series: "
                        f"Part '{original_spec2[0]}.{original_spec2[1]}' "
                        "is before "
                        f"Part '{original_spec1[0]}.{original_spec1[1]}'"
                    )


def _normalize_volume(vn, series):
    # handle negative volume numbers
    if vn < 0:
        # numerotation of volumes in spec start at 1
        return len(series.volumes) + vn + 1
    return vn


@attr.s
class IdentifierSpec:
    # not really a spec (part:part) => represents a requests for series, vol or part by
    # id
    type_ = attr.ib()
    volume_id = attr.ib(None)
    part_id = attr.ib(None)

    def has_volume(self, volume) -> bool:
        # assumes : only check a single series with the spec
        if self.type_ == SERIES:
            return True

        return self.volume_id == volume.volume_id

    def has_part(self, part) -> bool:
        if self.type_ == SERIES:
            return True

        if self.type_ == VOLUME:
            return self.volume_id == part.volume.volume_id

        return self.part_id == part.part_id


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

    reg = r"^\s*(-?\d+)(?:\.(\d+))?\s*$"
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
