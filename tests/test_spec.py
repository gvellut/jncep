from jncep.model import Part, Volume
from jncep.spec import analyze_part_specs


def _to_vp(vn, pn):
    volume = Volume(None, None, vn)
    part = Part(None, None, pn, volume)

    return volume, part


def test_open_end_no_part():
    spec = analyze_part_specs("2:")

    volume, part = _to_vp(1, 1)
    assert not spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(2, 1)
    assert spec.has_volume(volume)
    assert spec.has_part(part)


def test_open_end_with_part():
    spec = analyze_part_specs("2.4:")

    volume, part = _to_vp(1, 1)
    assert not spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(2, 1)
    assert spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(2, 4)
    assert spec.has_volume(volume)
    assert spec.has_part(part)

    volume, part = _to_vp(3, 1)
    assert spec.has_volume(volume)
    assert spec.has_part(part)


def test_open_start_no_part():
    spec = analyze_part_specs(":6")

    volume, part = _to_vp(2, 1)
    assert spec.has_volume(volume)
    assert spec.has_part(part)

    volume, part = _to_vp(6, 1)
    assert spec.has_volume(volume)
    assert spec.has_part(part)

    volume, part = _to_vp(7, 1)
    assert not spec.has_volume(volume)
    assert not spec.has_part(part)


def test_open_start_with_part():
    spec = analyze_part_specs(":6.4")

    volume, part = _to_vp(2, 1)
    assert spec.has_volume(volume)
    assert spec.has_part(part)

    volume, part = _to_vp(6, 1)
    assert spec.has_volume(volume)
    assert spec.has_part(part)

    volume, part = _to_vp(6, 7)
    assert spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(7, 3)
    assert not spec.has_volume(volume)
    assert not spec.has_part(part)


def test_whole_series():
    spec = analyze_part_specs(":")

    volume, part = _to_vp(6, 3)
    assert spec.has_volume(volume)
    assert spec.has_part(part)

    volume, part = _to_vp(1, 1)
    assert spec.has_volume(volume)
    assert spec.has_part(part)


def test_same_vol_diff_parts():
    spec = analyze_part_specs("9.6:9.8")

    volume, part = _to_vp(6, 1)
    assert not spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(9, 9)
    assert spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(9, 4)
    assert spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(9, 6)
    assert spec.has_volume(volume)
    assert spec.has_part(part)


def test_same_parts():
    spec = analyze_part_specs("9.6:9.6")

    volume, part = _to_vp(9, 4)
    assert spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(9, 6)
    assert spec.has_volume(volume)
    assert spec.has_part(part)


def test_diff_vol():
    spec = analyze_part_specs("5.6:7.8")

    volume, part = _to_vp(4, 1)
    assert not spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(5, 4)
    assert spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(5, 6)
    assert spec.has_volume(volume)
    assert spec.has_part(part)

    volume, part = _to_vp(5, 9)
    assert spec.has_volume(volume)
    assert spec.has_part(part)

    volume, part = _to_vp(6, 4)
    assert spec.has_volume(volume)
    assert spec.has_part(part)

    volume, part = _to_vp(7, 9)
    assert spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(7, 8)
    assert spec.has_volume(volume)
    assert spec.has_part(part)

    volume, part = _to_vp(7, 4)
    assert spec.has_volume(volume)
    assert spec.has_part(part)


def test_single_volume():
    spec = analyze_part_specs("9")

    volume, part = _to_vp(6, 1)
    assert not spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(9, 9)
    assert spec.has_volume(volume)
    assert spec.has_part(part)


def test_single_part():
    spec = analyze_part_specs("6.7")

    volume, part = _to_vp(6, 1)
    assert spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(6, 7)
    assert spec.has_volume(volume)
    assert spec.has_part(part)
