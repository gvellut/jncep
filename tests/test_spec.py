from addict import Dict as Addict
import pytest

from jncep.model import Part, Volume
from jncep.spec import analyze_part_specs, SpecError


def _to_vp(vn, pn):
    volume = Volume(None, None, vn)
    part = Part(None, None, pn, volume)

    return volume, part


def _to_series(num_parts):
    series = Addict(
        {
            "volumes": [
                {"num": i, "parts": [None] * pn} for i, pn in enumerate(num_parts)
            ]
        }
    )
    return series


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


def test_diff_parts_negative_volumes():
    series = _to_series([8, 11, 10, 7, 12])
    spec = analyze_part_specs("-1.3:-1.6")
    spec.normalize_and_verify(series)

    volume, part = _to_vp(4, 1)
    assert not spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(5, 4)
    assert spec.has_volume(volume)
    assert spec.has_part(part)

    spec = analyze_part_specs("-5.3:-2.6")
    spec.normalize_and_verify(series)

    volume, part = _to_vp(5, 1)
    assert not spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(2, 4)
    assert spec.has_volume(volume)
    assert spec.has_part(part)

    spec = analyze_part_specs("-4.3:3.6")
    spec.normalize_and_verify(series)

    volume, part = _to_vp(2, 4)
    assert spec.has_volume(volume)
    assert spec.has_part(part)

    volume, part = _to_vp(3, 4)
    assert spec.has_volume(volume)
    assert spec.has_part(part)

    volume, part = _to_vp(2, 1)
    assert spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(4, 1)
    assert not spec.has_volume(volume)
    assert not spec.has_part(part)


def test_single_volume():
    spec = analyze_part_specs("9")

    volume, part = _to_vp(6, 1)
    assert not spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(9, 9)
    assert spec.has_volume(volume)
    assert spec.has_part(part)


def test_single_negative_volume():
    series = _to_series([8, 11, 10])

    spec = analyze_part_specs("-2")
    # necessary for negative volumes
    spec.normalize_and_verify(series)

    volume, part = _to_vp(1, 1)
    assert not spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(2, 9)
    assert spec.has_volume(volume)
    assert spec.has_part(part)

    volume, part = _to_vp(3, 2)
    assert not spec.has_volume(volume)
    assert not spec.has_part(part)


def test_single_part():
    spec = analyze_part_specs("6.7")

    volume, part = _to_vp(6, 1)
    assert spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(6, 7)
    assert spec.has_volume(volume)
    assert spec.has_part(part)


def test_single_part_negative_volume():
    series = _to_series([8, 11, 10, 9])

    spec = analyze_part_specs("-2.1")
    spec.normalize_and_verify(series)

    volume, part = _to_vp(2, 1)
    assert not spec.has_volume(volume)
    assert not spec.has_part(part)

    volume, part = _to_vp(3, 1)
    assert spec.has_volume(volume)
    assert spec.has_part(part)

    volume, part = _to_vp(4, 2)
    assert not spec.has_volume(volume)
    assert not spec.has_part(part)


def test_verifiy_whole_series():
    series = _to_series([8, 11, 10, 9])

    spec = analyze_part_specs(":")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")


def test_verify_open_end_no_part():
    series = _to_series([8, 11, 10, 9])

    spec = analyze_part_specs("2:")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")

    spec = analyze_part_specs("5:")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs("-5:")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs("-4:")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")


def test_verify_open_end_with_part():
    series = _to_series([8, 11, 10, 9])

    spec = analyze_part_specs("2.4:")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")

    spec = analyze_part_specs("5.3:")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs("2.12:")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs("-5.3:")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs("-3.12:")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs("-4.8:")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")


def test_verify_open_start_no_part():
    series = _to_series([8, 11, 10, 9])

    spec = analyze_part_specs(":1")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")

    spec = analyze_part_specs(":6")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs(":-5")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs(":-4")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")


def test_verify_open_start_with_part():
    series = _to_series([8, 11, 10, 9])

    spec = analyze_part_specs(":4.4")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")

    spec = analyze_part_specs(":4.10")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs(":5.2")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs(":-5.2")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs(":-1.4")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")

    spec = analyze_part_specs(":-1.10")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)


def test_verify_same_vol_diff_parts():
    series = _to_series([8, 11, 10, 9])

    spec = analyze_part_specs("-5.8:2.6")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs("4.6:4.8")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")

    spec = analyze_part_specs("4.8:4.6")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs("-1.6:4.8")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")

    spec = analyze_part_specs("-1.8:4.6")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)


def test_verify_same_parts():
    series = _to_series([8, 11, 10, 9])

    spec = analyze_part_specs("3.6:3.6")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")

    spec = analyze_part_specs("-1.8:4.8")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")

    spec = analyze_part_specs("-5.6:-5.6")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)


def test_verify_diff_vol():
    series = _to_series([8, 11, 10, 9])

    spec = analyze_part_specs("5.6:7.8")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs("3.2:4.9")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")

    spec = analyze_part_specs("2.2:4")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")

    spec = analyze_part_specs("2:4.5")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")

    spec = analyze_part_specs("4.5:2")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs("2.12:4.7")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs("2.2:1.7")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs("2.1:4.10")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs("-5.1:4.10")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs("1.3:-1.10")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs("2.3:-1")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")


def test_verify_single_volume():
    series = _to_series([8, 11, 10])

    spec = analyze_part_specs("3")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")

    spec = analyze_part_specs("4")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs("-2")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")

    spec = analyze_part_specs("-5")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)


def test_verify_single_part():
    series = _to_series([8, 11, 10, 9])

    spec = analyze_part_specs("3.1")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")

    spec = analyze_part_specs("3.11")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs("5.6")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs("-2.1")
    try:
        spec.normalize_and_verify(series)
    except SpecError:
        pytest.fail("Unexpected")

    spec = analyze_part_specs("-2.12")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)

    spec = analyze_part_specs("-5")
    with pytest.raises(SpecError):
        spec.normalize_and_verify(series)
