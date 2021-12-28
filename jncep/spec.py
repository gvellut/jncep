import logging
import re

from . import jncapi, jncweb

logger = logging.getLogger(__package__)

RANGE_SEP = ":"


def to_relative_spec_from_part(part):
    volume_number = part.volume.num
    part_number = part.num_in_volume
    return f"{volume_number}.{part_number}"


def to_part_from_relative_spec(series, relpart_str) -> jncapi.Part:
    # there will be an error if the relpart does not not existe
    parts = _analyze_volume_part_specs(series, relpart_str)
    return parts[0]


def analyze_requested(jnc_resource, series):
    if jnc_resource.resource_type == jncweb.RESOURCE_TYPE_PART:
        # because partNumber sometimes has a gap => loop through all parts
        # to find the actual object (instead of using [partNumber] directly)
        for part in series.parts:
            if part.raw_part.partNumber == jnc_resource.raw_metadata.partNumber:
                return [part]

    if jnc_resource.resource_type == jncweb.RESOURCE_TYPE_VOLUME:
        iv = jnc_resource.raw_metadata.volumeNumber - 1
        return list(series.volumes[iv].parts)

    # series: all parts
    return list(series.parts)


def analyze_part_specs(series, part_specs, is_absolute):
    """ v(.p):v2(.p) or v(.p): or :v(.p) or v(.p) or : """

    part_specs = part_specs.strip()

    if part_specs == RANGE_SEP:
        return series.parts

    if is_absolute:
        return _analyze_absolute_part_specs(series, part_specs)

    return _analyze_volume_part_specs(series, part_specs)


def _analyze_absolute_part_specs(series, part_specs):  # noqa: C901
    parts = []
    sides = part_specs.split(RANGE_SEP)
    if len(sides) > 2:
        raise ValueError("Multiple ':' in part specs")

    reg = r"^\s*(\d+)\s*$"
    if len(sides) == 1:
        # not a range: single part
        m = re.match(reg, sides[0])
        if not m:
            raise ValueError("Specified part must be a number")
        fp = int(m.group(1))
        ifp = _validate_absolute_part_number(series, fp)
        return [series.parts[ifp]]

    # range
    m1 = re.match(reg, sides[0])
    m2 = re.match(reg, sides[1])
    if not m1 and not m2:
        msg = "Part specification must be <number>:<number> or <number>: or :<number>"
        raise ValueError(msg)

    if m1:
        fp = int(m1.group(1))
        ifp = _validate_absolute_part_number(series, fp)

    if m2:
        lp = int(m2.group(1))
        ilp = _validate_absolute_part_number(series, lp)

    if m1 and not m2:
        # to the end
        for ip in range(ifp, len(series.parts)):
            parts.append(series.parts[ip])
        return parts

    if m2 and not m1:
        # since the beginning
        # + 1 => include the second side of the range
        for ip in range(0, ilp + 1):
            parts.append(series.parts[ip])
        return parts

    # both sides are present
    if ifp > ilp:
        msg = "Second side of the part range must be greater than first"
        raise ValueError(msg)

    # + 1 => include the second side of the range
    for ip in range(ifp, ilp + 1):
        parts.append(series.parts[ip])
    return parts


def _validate_absolute_part_number(series, p):
    if p == 0:
        raise ValueError("Specified part number must be at least 1")
    # part specs start at 1 => transform to Python index
    ip = p - 1
    if ip >= len(series.parts):
        raise ValueError(
            "Specified part number must be less than the number of parts in series"
        )
    return ip


def _analyze_volume_part_specs(series, part_specs):  # noqa: C901
    parts = []
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
            iv, ip = _validate_volume_part_number(series, fv, fp)
            return [series.volumes[iv].parts[ip]]
        else:
            # full volume
            iv = _validate_volume_part_number(series, fv)
            for part in series.volumes[iv].parts:
                parts.append(part)
            return parts

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
            ifv, ifp = _validate_volume_part_number(series, fv, fp)
        else:
            ifv = _validate_volume_part_number(series, fv)
            # beginning of the volume
            ifp = 0
        ifp = _to_absolute_part_index(series, ifv, ifp)

    if m2:
        lv = int(m2.group(1))
        if m2.group(2):
            lp = int(m2.group(2))
            ilv, ilp = _validate_volume_part_number(series, lv, lp)
        else:
            ilv = _validate_volume_part_number(series, lv)
            # end of the volume
            ilp = -1
        # this works too if ilp == -1
        ilp = _to_absolute_part_index(series, ilv, ilp)

    # same as for absolute part spec

    if m1 and not m2:
        # to the end
        for ip in range(ifp, len(series.parts)):
            parts.append(series.parts[ip])
        return parts

    if m2 and not m1:
        # since the beginning
        # + 1 => include the second side of the range
        for ip in range(0, ilp + 1):
            parts.append(series.parts[ip])
        return parts

    # both sides are present
    if ifp > ilp:
        msg = "Second side of the vol[.part] range must be greater than first"
        raise ValueError(msg)

    # + 1 => always include the second side of the range
    for ip in range(ifp, ilp + 1):
        parts.append(series.parts[ip])
    return parts


def _validate_volume_part_number(series, v, p=None):
    iv = v - 1

    if iv >= len(series.volumes):
        raise ValueError(
            "Specified volume number must be less than the number of volumes in series"
        )
    volume = series.volumes[iv]

    if p is None:
        return iv

    ip = p - 1
    if ip >= len(volume.parts):
        raise ValueError(
            "Specified part number must be less than the number of parts in volume"
        )
    return iv, ip


def _to_absolute_part_index(series, iv, ip):
    volume = series.volumes[iv]
    return volume.parts[ip].absolute_num - 1
