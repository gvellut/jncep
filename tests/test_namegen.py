from addict import Dict as Addict
import pytest

from jncep.model import Part
from jncep.namegen import (
    FC,
    generate_names,
    InvalidNamegenRulesError,
    parse_namegen_rules,
)


def test_parse_title_namegen_rules_single_t():
    result = parse_namegen_rules('fc_full > p_title>p_title(1,"azaeae")', False)
    assert isinstance(result, dict), "Expected a dictionary"
    assert "t" in result, "Expected 't' in result"
    assert "n" in result, "Expected 'n' in result"
    assert "f" in result, "Expected 'f' in result"


def test_parse_title_namegen_rules_all_sections():
    result = parse_namegen_rules(
        't:fc_full|n:p_title>p_title(1,"azaeae")|f:p_title', False
    )
    assert isinstance(result, dict), "Expected a dictionary"
    assert "t" in result, "Expected 't' in result"
    assert "n" in result, "Expected 'n' in result"
    assert "f" in result, "Expected 'f' in result"


def test_parse_title_namegen_rules_invalid_repeated():
    with pytest.raises(InvalidNamegenRulesError):
        parse_namegen_rules("t:fc_full | t:p_title", False)


def test_parse_title_namegen_rules_bad_rule_name():
    with pytest.raises(InvalidNamegenRulesError):
        parse_namegen_rules("fc_fulleee", False)


def test_parse_title_namegen_rules_bad_section():
    with pytest.raises(InvalidNamegenRulesError):
        parse_namegen_rules("s:fc_full", False)


def test_generate_names():
    gen_rules = parse_namegen_rules("t:legacy_t | f:_t", False)
    part = Part(Addict({"title": "Hello"}), "azaez", 1)
    names = generate_names(None, [], [part], FC(False, False), gen_rules)
    assert isinstance(names, list), "Expected a list"
    assert all(
        isinstance(name, str) for name in names
    ), "Expected all names to be strings"
