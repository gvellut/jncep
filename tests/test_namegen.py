import tempfile
from pathlib import Path

from addict import Dict as Addict
import pytest

from jncep.cli.options import process_namegen_option
from jncep.core import _process_single_epub_content, EpubGenerationOptions
from jncep.model import Part, Series, Volume
from jncep.namegen import (
    FC,
    InvalidNamegenRulesError,
    generate_names,
    parse_namegen_rules,
)


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
    series = Series(Addict({"title": "My Series"}), "s1")
    volume = Volume(Addict({"title": "My Volume"}), "v1", 1, series=series)
    part = Part(Addict({"title": "Hello"}), "p1", 1, volume=volume)
    names = generate_names(series, [volume], [part], FC(False, False), gen_rules)
    assert isinstance(names, list), "Expected a list"
    assert all(isinstance(name, str) for name in names), "Expected all names to be strings"


def test_generate_names_from_py_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        namegen_py_content = """
def to_title(series, volumes, parts, fc):
    return "Custom Title"

def to_filename(series, volumes, parts, fc):
    return "custom_filename"

def to_folder(series, volumes, parts, fc):
    return "custom_folder"
"""
        namegen_py_path = Path(tmpdir) / "namegen.py"
        with open(namegen_py_path, "w") as f:
            f.write(namegen_py_content)

        @process_namegen_option
        def dummy_command(**kwargs):
            return kwargs["namegen_rules"]

        loaded_funcs = dummy_command(namegen_rules=str(namegen_py_path.absolute()))

        assert "to_title" in loaded_funcs
        assert "to_filename" in loaded_funcs
        assert "to_folder" in loaded_funcs

        # Mock data for _process_single_epub_content
        series = Series(
            Addict({"title": "My Series", "slug": "my-series", "tags": []}),
            "series_id",
        )
        volume = Volume(
            Addict(
                {
                    "title": "My Volume",
                    "slug": "my-volume",
                    "creators": [],
                    "description": "",
                }
            ),
            "volume_id",
            1,
            series=series,
        )
        part = Part(Addict({"title": "My Part"}), "part_id", 1, volume=volume)
        volume.parts = [part]
        series.volumes = [volume]
        part.epub_content = ""
        part.images = []

        options = EpubGenerationOptions(
            output_dirpath="",
            is_subfolder=True,
            is_by_volume=False,
            is_extract_images=False,
            is_extract_content=False,
            is_not_replace_chars=False,
            style_css_path=None,
            namegen_rules=loaded_funcs,
        )

        book_details = _process_single_epub_content(series, [volume], [part], options)

        assert book_details.title == "Custom Title"
        assert book_details.filename == "custom_filename"
        assert book_details.subfolder == "custom_folder"
