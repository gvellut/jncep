from pathlib import Path
import tempfile

from addict import Dict as Addict
import pytest

from jncep.model import Part, Series, Volume
from jncep.namegen import NameGenerator
from jncep.namegen_minilang import (
    InvalidNamegenRulesError,
    generate_names,
    parse_namegen_rules,
)
from jncep.namegen_utils import FC


def test_parse_title_namegen_rules_single_t():
    result = parse_namegen_rules('fc_full > p_title>p_title(1,"azaeae")')
    assert isinstance(result, dict), "Expected a dictionary"
    assert "t" in result, "Expected 't' in result"
    assert "n" in result, "Expected 'n' in result"
    assert "f" in result, "Expected 'f' in result"


def test_parse_title_namegen_rules_all_sections():
    result = parse_namegen_rules('t:fc_full|n:p_title>p_title(1,"azaeae")|f:p_title')
    assert isinstance(result, dict), "Expected a dictionary"
    assert "t" in result, "Expected 't' in result"
    assert "n" in result, "Expected 'n' in result"
    assert "f" in result, "Expected 'f' in result"


def test_parse_title_namegen_rules_invalid_repeated():
    with pytest.raises(InvalidNamegenRulesError):
        parse_namegen_rules("t:fc_full | t:p_title")


def test_parse_title_namegen_rules_bad_rule_name():
    with pytest.raises(InvalidNamegenRulesError):
        parse_namegen_rules("fc_fulleee")


def test_parse_title_namegen_rules_bad_section():
    with pytest.raises(InvalidNamegenRulesError):
        parse_namegen_rules("s:fc_full")


def test_generate_names():
    gen_rules = parse_namegen_rules("t:legacy_t | f:_t")
    series = Series(
        Addict({"title": "My Series", "raw_data": {"title": "My Series"}}), "s1"
    )
    volume = Volume(
        Addict({"title": "My Volume", "raw_data": {"title": "My Volume"}}),
        "v1",
        1,
        series=series,
    )
    part = Part(
        Addict({"title": "Hello", "raw_data": {"title": "Hello"}}),
        "p1",
        1,
        volume=volume,
    )
    volume.series = series
    part.volume = volume
    names = generate_names(series, [volume], [part], FC(False, False), gen_rules)
    assert isinstance(names, list), "Expected a list"
    assert all(isinstance(name, str) for name in names), (
        "Expected all names to be strings"
    )


def test_name_generator_with_py_file_fallback():
    with tempfile.TemporaryDirectory() as tmpdir:
        namegen_py_content = """
from jncep.namegen_utils import *
def to_title(series, volumes, parts, fc):
    return "Custom Title From Py"
"""
        namegen_py_path = Path(tmpdir) / "namegen.py"
        with open(namegen_py_path, "w") as f:
            f.write(namegen_py_content)

        name_generator = NameGenerator(str(namegen_py_path.absolute()))

        series = Series(
            Addict({"title": "My Series", "raw_data": {"title": "My Series"}}), "s1"
        )
        volume = Volume(
            Addict(
                {"title": "My Volume", "num": 1, "raw_data": {"title": "My Volume"}}
            ),
            "v1",
            1,
            series=series,
        )
        part = Part(
            Addict({"title": "My Part", "raw_data": {"title": "My Part"}}),
            "p1",
            1,
            volume=volume,
        )
        volume.series = series
        part.volume = volume

        title, filename, folder = name_generator.generate(
            series, [volume], [part], FC(False, False)
        )

        assert title == "Custom Title From Py"
        # Check fallback to default legacy_filename, which uses the generated title
        assert filename == "Custom_Title_From_Py"
        # Check fallback to default legacy_folder
        assert folder == "My Series"


def test_name_generator_with_mini_language():
    name_generator = NameGenerator("t:p_to_series>s_title>to_string")
    series = Series(
        Addict({"title": "My Series", "raw_data": {"title": "My Series"}}), "s1"
    )
    volume = Volume(
        Addict({"title": "My Volume", "num": 1, "raw_data": {"title": "My Volume"}}),
        "v1",
        1,
        series=series,
    )
    part = Part(
        Addict({"title": "My Part", "raw_data": {"title": "My Part"}}),
        "p1",
        1,
        volume=volume,
    )
    volume.series = series
    part.volume = volume

    title, filename, folder = name_generator.generate(
        series, [volume], [part], FC(False, False)
    )

    assert title == "My Series"
    # Check fallback to default legacy_filename and legacy_folder
    assert filename == "My_Series"
    assert folder == "My Series"
