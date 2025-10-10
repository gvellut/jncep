from __future__ import annotations

from collections import namedtuple
import copy
from enum import Enum, auto
import importlib.resources as imres
import logging
import numbers
import re
import string
import sys
from typing import TYPE_CHECKING
import importlib.util
from pathlib import Path

from attr import define
from lark import Lark, Transformer, v_args
from lark.exceptions import LarkError

from .utils import getConsole, to_safe_filename, to_safe_foldername
from . import config

if TYPE_CHECKING:
    from .model import Part, Series, Volume


logger = logging.getLogger(__name__)
console = getConsole()

GEN_RULE_FUNCS = {}

RULE_SPECIAL_PREVIOUS = "_t"

TITLE_SECTION = "t"
FILENAME_SECTION = "n"
# folder instead of directory since the option to output into folder is --subfolder
FOLDER_SECTION = "f"

DEFAULT_NAMEGEN_RULES = "t:legacy_t|n:_t>str_filesafe|f:legacy_f"

# dict : per language
CACHED_STOPWORDS = {}

EN_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}


class ComType(Enum):
    FC = auto()
    PN = auto()
    VN = auto()
    P = auto()
    V = auto()
    S = auto()
    S_STR = auto()
    STR = auto()


class VnType(Enum):
    VN_INTERNAL = auto()
    VN_MERGED = auto()
    VN_SPECIAL = auto()


@define
class Component:
    tag: ComType
    value: object
    base_value: object = None


FC = namedtuple("FC", "final complete")

GRAMMAR = """
    ?start: prefix_expr
    prefix_expr: section ("|" section)* -> sections
    ?section: "t" ":" t_expr
        | "n" ":" n_expr
        | "f" ":" f_expr
        | t_expr
    t_expr: func_call (">" func_call)*  -> t_chain
    n_expr: func_call (">" func_call)*  -> n_chain
    f_expr: func_call (">" func_call)*  -> f_chain
    func_call: CNAME "(" arg_list ")"  -> func_call_with_args
             | CNAME                  -> func_call_no_args
    arg_list: arg ("," arg)*
    arg: SIGNED_INT   -> int_arg
       | FLOAT        -> float_arg
       | ESCAPED_STRING -> string_arg
    %import common.CNAME
    %import common.SIGNED_INT
    %import common.FLOAT
    %import common.ESCAPED_STRING
    %import common.WS
    %ignore WS
"""


class MyTransformer(Transformer):
    def __init__(self):
        self._sections = set()

    @v_args(inline=True)
    def int_arg(self, arg):
        return int(arg.value)

    @v_args(inline=True)
    def float_arg(self, arg):
        return float(arg.value)

    @v_args(inline=True)
    def string_arg(self, arg):
        return str(arg.value[1:-1])

    def func_call_no_args(self, x):
        return (x[0].value, [])

    def func_call_with_args(self, x):
        return (x[0].value, x[1])

    def arg_list(self, args):
        return args

    def sections(self, args):
        return dict(args)

    def t_chain(self, args):
        if TITLE_SECTION in self._sections:
            raise InvalidNamegenRulesError(f"Section {TITLE_SECTION} must be present only once")
        self._sections.add(TITLE_SECTION)
        return (TITLE_SECTION, args)

    def n_chain(self, args):
        if FILENAME_SECTION in self._sections:
            raise InvalidNamegenRulesError(f"Section {FILENAME_SECTION} must be present only once")
        self._sections.add(FILENAME_SECTION)
        return (FILENAME_SECTION, args)

    def f_chain(self, args):
        if FOLDER_SECTION in self._sections:
            raise InvalidNamegenRulesError(f"Section {FOLDER_SECTION} must be present only once")
        self._sections.add(FOLDER_SECTION)
        return (FOLDER_SECTION, args)


LARK_PARSER = Lark(GRAMMAR, parser="lalr")


class InvalidNamegenRulesError(Exception):
    pass


class UnsupportedStopwordLanguage(Exception):
    pass


class NamegenRuleCallError(Exception):
    pass


class EmptyStringError(Exception):
    pass


def _init_module():
    global GEN_RULE_FUNCS
    function_names = _get_functions_between_comments(__file__, "# GEN_RULES_BEGIN", "# GEN_RULES_END")
    for name in function_names:
        func = getattr(sys.modules[__name__], name, None)
        if func is not None:
            GEN_RULE_FUNCS[name] = func

    def _t():
        raise InvalidNamegenRulesError("_t should be the first rule in section")

    GEN_RULE_FUNCS[RULE_SPECIAL_PREVIOUS] = _t


def parse_namegen_rules(namegen_rules):
    default_gen_rules = None
    if namegen_rules:
        gen_rules = _do_parse_namegen_rules(namegen_rules)
        for prefix in [TITLE_SECTION, FILENAME_SECTION, FOLDER_SECTION]:
            if not gen_rules.get(prefix):
                if default_gen_rules is None:
                    default_gen_rules = _do_parse_namegen_rules(DEFAULT_NAMEGEN_RULES)
                gen_rules[prefix] = default_gen_rules[prefix]
        return gen_rules
    else:
        return _do_parse_namegen_rules(DEFAULT_NAMEGEN_RULES)


def _do_parse_namegen_rules(namegen_rules):
    try:
        tree = LARK_PARSER.parse(namegen_rules)
        gen_rules = MyTransformer().transform(tree)
    except LarkError as e:
        error_details = str(e)
        raise InvalidNamegenRulesError("Invalid namegen rules provided. Details: " + error_details) from e
    if logger.level <= logging.DEBUG:
        logger.debug(f"parse = {gen_rules}")
    _validate(gen_rules)
    return gen_rules


def _validate(gen_rules):
    for section in gen_rules:
        for func_name, _ in gen_rules[section]:
            if func_name not in GEN_RULE_FUNCS:
                raise InvalidNamegenRulesError(f"Invalid rule: {func_name}")
    return gen_rules


def generate_names(series, volumes, parts, fc, parsed_namegen_rules):
    values = []
    for section in [TITLE_SECTION, FILENAME_SECTION, FOLDER_SECTION]:
        rules = parsed_namegen_rules[section]
        components, rules = _initialize_components(series, volumes, parts, fc, rules, values)
        _apply_rules(components, rules)
        if len(components) != 1 or components[0].tag != ComType.STR or not components[0].value:
            raise InvalidNamegenRulesError("Invalid namegen definition: should generate a string (STR_COM)")
        values.append(components[0])
    return [o.value for o in values]


def _initialize_components(series, volumes, parts, fc, rules, outputs):
    if rules and rules[0][0] == RULE_SPECIAL_PREVIOUS:
        previous = outputs[-1]
        components = [copy.copy(previous)]
        rules = rules[1:]
    else:
        components = _default_initialize_components(series, volumes, parts, fc)
    return components, rules


def _default_initialize_components(series, volumes, parts, fc):
    if len(parts) == 1:
        components = [Component(ComType.P, parts[0])]
    else:
        if len(volumes) > 1:
            components = [
                Component(ComType.S, series),
                Component(ComType.VN, _default_vn(volumes), volumes),
                Component(ComType.PN, _default_pn(parts), parts),
            ]
        else:
            components = [
                Component(ComType.V, volumes[0]),
                Component(ComType.PN, _default_pn(parts), parts),
            ]
    components.append(Component(ComType.FC, fc))
    return components


def _apply_rules(components: list[Component], rules):
    for rule_name, args in rules:
        logger.debug(f"Apply rule: {rule_name} with args {args}")
        f_rule = GEN_RULE_FUNCS[rule_name]
        try:
            f_rule(components, *args)
        except Exception as ex:
            msg = f"Error calling rule {rule_name} with args {args}"
            logger.debug(f"{msg} : {ex}", exc_info=sys.exc_info())
            raise NamegenRuleCallError(msg) from ex


def legacy_title(series: "Series", volumes: list["Volume"], parts: list["Part"], fc: "FC") -> str:
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
            part_segment = f"Parts {parts[0].volume.num}.{parts[0].num_in_volume} to {parts[-1].volume.num}.{parts[-1].num_in_volume}"
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
                part_segment = f"Parts {parts[0].num_in_volume} to {parts[-1].num_in_volume}"
                if fc.final:
                    part_segment += " - Final"
            title = f"{title_base} [{part_segment}]"
    return title


def legacy_filename(series: "Series", volumes: list["Volume"], parts: list["Part"], fc: "FC") -> str:
    title = legacy_title(series, volumes, parts, fc)
    return to_safe_filename(title)


def legacy_folder(series: "Series", volumes: list["Volume"], parts: list["Part"], fc: "FC") -> str:
    return to_safe_foldername(series.raw_data.title)


# GEN_RULES_BEGIN

def fc_rm(components: list[Component]):
    component = _find_component_type(ComType.FC, components)
    if component:
        _del_component(components, component)

def fc_rm_if_complete(components: list[Component]):
    component = _find_component_type(ComType.FC, components)
    if component and component.value.complete:
        _del_component(components, component)

def fc_short(components: list[Component]):
    component = _find_component_type(ComType.FC, components)
    if component:
        output = "[C]" if component.value.complete else "[F]" if component.value.final else ""
        _replace_component(components, component, Component(ComType.STR, output))

def fc_full(components: list[Component]):
    component = _find_component_type(ComType.FC, components)
    if component:
        output = "[Complete]" if component.value.complete else "[Final]" if component.value.final else ""
        _replace_component(components, component, Component(ComType.STR, output))

def p_to_volume(components: list[Component]):
    component = _find_component_type(ComType.P, components)
    if component:
        part = component.value
        v_com = Component(ComType.V, part.volume)
        pn_com = Component(ComType.PN, _default_pn([part]), [part])
        _replace_component(components, component, v_com, pn_com)

def p_to_series(components: list[Component]):
    p_component = _find_component_type(ComType.P, components)
    if p_component:
        part = p_component.value
        pn_component = Component(ComType.PN, _default_pn([part]), [part])
        vn_component = Component(ComType.VN, _default_vn([part.volume]), [part.volume])
        series_component = Component(ComType.S, part.volume.series)
        _replace_component(components, p_component, series_component, vn_component, pn_component)

def p_split_part(components: list[Component]):
    p_component = _find_component_type(ComType.P, components)
    if p_component:
        part = p_component.value
        v_com = Component(ComType.V, part.volume)
        pn_com = Component(ComType.PN, [part.num_in_volume], [part])
        _replace_component(components, p_component, v_com, pn_com)

def p_title(components: list[Component]):
    component = _find_component_type(ComType.P, components)
    if component:
        _replace_component(components, component, Component(ComType.STR, component.value.raw_data.title))

def pn_rm(components: list[Component]):
    pn_component = _find_component_type(ComType.PN, components)
    if pn_component:
        _del_component(components, pn_component)

def pn_rm_if_complete(components: list[Component]):
    pn_component = _find_component_type(ComType.PN, components)
    fc_component = _find_component_type(ComType.FC, components)
    if pn_component and fc_component and fc_component.value.complete:
        _del_component(components, pn_component)

def pn_prepend_vn_if_multiple(components: list[Component]):
    pn_component = _find_component_type(ComType.PN, components)
    vn_component = _find_component_type(ComType.VN, components)
    if pn_component and vn_component and len(vn_component.value) > 1:
        parts = pn_component.base_value
        volumes = vn_component.base_value
        for i, part in enumerate(parts):
            volume_i = volumes.index(part.volume)
            pn_component.value[i] = f"{_vn_to_single(vn_component.value[volume_i])}.{pn_component.value[i]}"

def pn_prepend_vn(components: list[Component]):
    pn_component = _find_component_type(ComType.PN, components)
    vn_component = _find_component_type(ComType.VN, components)
    if pn_component and vn_component:
        parts = pn_component.base_value
        volumes = vn_component.base_value
        for i, part in enumerate(parts):
            volume_i = volumes.index(part.volume)
            pn_component.value[i] = f"{_vn_to_single(vn_component.value[volume_i])}.{pn_component.value[i]}"

def pn_0pad(components: list[Component]):
    component = _find_component_type(ComType.PN, components)
    if component:
        component.value = [str(pn).zfill(2) for pn in component.value]

def pn_short(components: list[Component]):
    component = _find_component_type(ComType.PN, components)
    if component:
        nums = component.value
        output = f"{nums[0]}-{nums[-1]}" if len(nums) > 1 else str(nums[0])
        _replace_component(components, component, Component(ComType.STR, output))

def pn_full(components: list[Component]):
    component = _find_component_type(ComType.PN, components)
    if component:
        nums = component.value
        output = f"Parts {nums[0]} to {nums[-1]}" if len(nums) > 1 else f"Part {nums[0]}"
        _replace_component(components, component, Component(ComType.STR, output))

def v_to_series(components: list[Component]):
    component = _find_component_type(ComType.V, components)
    if component:
        volume = component.value
        s_com = Component(ComType.S, volume.series)
        vn_com = Component(ComType.VN, _default_vn([volume]), [volume])
        _replace_component(components, component, s_com, vn_com)

def v_split_volume(components: list[Component]):
    component = _find_component_type(ComType.V, components)
    if component:
        volume = component.value
        diff = _str_diff(volume.raw_data.title, volume.series.raw_data.title)
        if diff:
            vn_parts = _parse_volume_number(_clean(diff))
            s_com = Component(ComType.S, volume.series)
            vn_com = Component(ComType.VN, [vn_parts], [volume])
            _replace_component(components, component, s_com, vn_com)

def _parse_volume_number(vn):
    volume_match = re.search(r"Volume (\d+)", vn)
    part_match = re.search(r"Part (\w+)", vn)
    result = []
    if volume_match:
        result.append((int(volume_match.group(1)), "Volume"))
    if part_match:
        result.append((part_match.group(1), "Part"))
    result.sort(key=lambda x: vn.index(x[1]))
    return result if result else [(vn, VnType.VN_SPECIAL)]

def v_title(components: list[Component]):
    component = _find_component_type(ComType.V, components)
    if component:
        _replace_component(components, component, Component(ComType.STR, component.value.raw_data.title))

def vn_rm(components: list[Component]):
    vn_component = _find_component_type(ComType.VN, components)
    if vn_component:
        _del_component(components, vn_component)

def vn_rm_if_pn(components: list[Component]):
    vn_component = _find_component_type(ComType.VN, components)
    pn_component = _find_component_type(ComType.PN, components)
    if vn_component and pn_component:
        _del_component(components, vn_component)

def vn_number(components: list[Component]):
    vn_component = _find_component_type(ComType.VN, components)
    if vn_component:
        for v in vn_component.value:
            for j, p in enumerate(v):
                if isinstance(p[0], str) and p[0].lower() in EN_NUMBERS:
                    v[j] = (EN_NUMBERS[p[0].lower()], p[1])

def vn_merge(components: list[Component]):
    vn_component = _find_component_type(ComType.VN, components)
    if vn_component:
        for i, v in enumerate(vn_component.value):
            if len(v) > 1:
                vn_component.value[i] = [(_vn_to_single(v), VnType.VN_MERGED)]

def vn_0pad(components: list[Component]):
    vn_component = _find_component_type(ComType.VN, components)
    if vn_component:
        for i, v in enumerate(vn_component.value):
            vn_component.value[i] = [(str(p[0]).zfill(2), p[1]) for p in v]

def vn_short(components: list[Component]):
    component = _find_component_type(ComType.VN, components)
    if component:
        vn_merge(components)
        volumes = component.value
        output = f"{volumes[0][0][0]}-{volumes[-1][0][0]}" if len(volumes) > 1 else str(volumes[0][0][0])
        _replace_component(components, component, Component(ComType.STR, output))

def vn_full(components: list[Component]):
    component = _find_component_type(ComType.VN, components)
    if component:
        if len(component.base_value) > 1:
            vn_merge(components)
            nums = [str(vn[0][0]) for vn in component.value]
            output = f"Volumes {', '.join(nums[:-1])} & {nums[-1]}"
        else:
            vn = component.value[0]
            if len(vn) > 1:
                output = " ".join([f"{p[1]} {p[0]}" if p[1] != VnType.VN_SPECIAL else p[0] for p in vn])
            else:
                output = str(vn[0][0]) if vn[0][1] == VnType.VN_SPECIAL else f"Volume {vn[0][0]}"
        _replace_component(components, component, Component(ComType.STR, output))

def to_series(components: list[Component]):
    v_to_series(components)
    p_to_series(components)

def s_title(components: list[Component]):
    component = _find_component_type(ComType.S, components)
    if component:
        _replace_component(components, component, Component(ComType.S_STR, component.value.raw_data.title))

def s_slug(components: list[Component]):
    component = _find_component_type(ComType.S, components)
    if component:
        _replace_component(components, component, Component(ComType.S_STR, component.value.raw_data.slug))

def ss_rm_stopwords(components: list[Component]):
    component = _find_component_type(ComType.S_STR, components)
    if component:
        stopwords = _load_stopwords("en")
        words = component.value.split()
        component.value = " ".join([word for word in words if word not in stopwords])

def ss_rm_subtitle(components: list[Component]):
    component = _find_component_type(ComType.S_STR, components)
    if component:
        component.value = component.value.split(":", 1)[0].strip()

def ss_acronym(components: list[Component]):
    component = _find_component_type(ComType.S_STR, components)
    if component:
        title = "".join(ch for ch in component.value if ch not in string.punctuation)
        component.value = "".join(word[0] for word in title.split())

def ss_first(components: list[Component], first_n=3):
    component = _find_component_type(ComType.S_STR, components)
    if component:
        title = "".join(ch for ch in component.value if ch not in string.punctuation)
        component.value = "".join(word[:first_n].capitalize() for word in title.split())

def ss_max_len(components: list[Component], max_len_n=30):
    component = _find_component_type(ComType.S_STR, components)
    if component:
        component.value = component.value[:max_len_n]

def legacy_t(components: list[Component]):
    p_component = _find_component_type(ComType.P, components)
    v_component = _find_component_type(ComType.V, components)
    s_component = _find_component_type(ComType.S, components)
    fc_component = _find_component_type(ComType.FC, components)
    fc = fc_component.value
    if p_component:
        part = p_component.value
        title = legacy_title(part.volume.series, [part.volume], [part], fc)
    elif s_component:
        vn_component = _find_component_type(ComType.VN, components)
        pn_component = _find_component_type(ComType.PN, components)
        title = legacy_title(s_component.value, vn_component.base_value, pn_component.base_value, fc)
    else:
        pn_component = _find_component_type(ComType.PN, components)
        title = legacy_title(v_component.value.series, [v_component.value], pn_component.base_value, fc)
    _replace_all(components, Component(ComType.STR, title))

def legacy_f(components: list[Component]):
    p_component = _find_component_type(ComType.P, components)
    v_component = _find_component_type(ComType.V, components)
    s_component = _find_component_type(ComType.S, components)
    if p_component:
        series = p_component.value.volume.series
    elif v_component:
        series = v_component.value.series
    else:
        series = s_component.value
    folder = legacy_folder(series, None, None, None)
    _replace_all(components, Component(ComType.STR, folder))

def to_string(components: list[Component], add_colon=0):
    str_values = []
    for c in components:
        if c.tag == ComType.S_STR and c.value:
            str_value = c.value
            if add_colon and str_value[-1] not in string.punctuation:
                str_values.append(str_value + ":")
            else:
                str_values.append(str_value)
        elif c.tag == ComType.STR and c.value:
            str_values.append(c.value)
    _replace_all(components, Component(ComType.STR, " ".join(str_values)))

def str_rm_space(components: list[Component]):
    str_component = _find_str_component_implicit_string(components)
    str_component.value = str_component.value.replace(" ", "")

def str_replace_space(components: list[Component], char_replace="_"):
    str_component = _find_str_component_implicit_string(components)
    str_component.value = str_component.value.replace(" ", char_replace)

def str_filesafe(components: list[Component], char_replace="_", preserve_chars=""):
    str_component = _find_str_component_implicit_string(components)
    str_component.value = to_safe_filename(str_component.value, char_replace, preserve_chars)

# GEN_RULES_END

def _find_component_type(ctype: ComType, components: list[Component]):
    return next((c for c in components if c.tag == ctype), None)

def _find_str_component_implicit_string(components):
    str_component = _find_component_type(ComType.STR, components)
    if not str_component:
        to_string(components)
        str_component = _find_component_type(ComType.STR, components)
        if not str_component.value:
            raise EmptyStringError()
    return str_component

def _default_vn(volumes):
    return [[(v.num, VnType.VN_INTERNAL)] for v in volumes]

def _default_pn(parts):
    return [p.num_in_volume for p in parts]

def _vn_to_single(vn):
    return ".".join([str(p[0]) for p in vn]) if isinstance(vn, list) else vn[0]

def _is_number(v):
    return isinstance(v, numbers.Number)

def _is_list(v):
    return isinstance(v, list)

def _replace_component(components, item, *items):
    components[_index(components, item):_index(components, item) + 1] = items

def _del_component(components, item):
    del components[_index(components, item)]

def _replace_all(components, *items):
    components[:] = items

def _index(components, item):
    return next((i for i, c in enumerate(components) if c is item), None)

def _str_diff(str1, str2):
    return str1[len(str2):] if str1.startswith(str2) else None

def _clean(s: str):
    return s.strip(":").strip()

def _load_stopwords(language):
    if language in CACHED_STOPWORDS:
        return CACHED_STOPWORDS[language]
    path = imres.files(__package__) / "res" / f"{language}_stopwords.txt"
    if not path.is_file():
        raise UnsupportedStopwordLanguage(f"Unsupported: {language}")
    with path.open("r", encoding="utf-8") as f:
        stopwords = [sw for w in f.readlines() if (sw := w.strip())]
        CACHED_STOPWORDS[language] = set(stopwords)
    return CACHED_STOPWORDS[language]

def _get_functions_between_comments(filename, start_comment, end_comment):
    with open(filename) as file:
        lines = file.readlines()
    start_line = next((i for i, line in enumerate(lines) if line.startswith(start_comment)), None)
    end_line = next((i for i, line in enumerate(lines) if line.startswith(end_comment)), None)
    if start_line is None or end_line is None:
        return []
    function_lines = lines[start_line:end_line]
    functions = [line for line in function_lines if line.strip().startswith("def ") and not line.strip().startswith("def _")]
    return [f.split("(")[0].replace("def ", "").strip() for f in functions]


class NameGenerator:
    def __init__(self, namegen_option: str | None):
        self._mode = "mini_language"
        self._py_funcs = {}
        self._parsed_rules = None
        self._process_option(namegen_option)

    def _process_option(self, namegen_option: str | None):
        from .cli.options import click
        namegen_py_path = None
        if namegen_option:
            if namegen_option.endswith(".py"):
                path = Path(namegen_option)
                if not path.is_absolute():
                    raise click.UsageError("--namegen path must be absolute.")
                if not path.exists():
                    raise click.UsageError(f"File not found: {namegen_option}")
                namegen_py_path = path
                logger.debug(f"Using namegen file from option: {namegen_py_path}")
            else:
                logger.debug("Using namegen rule string from option.")
                self._parsed_rules = parse_namegen_rules(namegen_option)
        else:
            config_namegen_py = config.config_dir() / "namegen.py"
            if config_namegen_py.exists():
                namegen_py_path = config_namegen_py
                logger.debug(f"Using namegen file from config directory: {namegen_py_path}")

        if namegen_py_path:
            self._mode = "py_file"
            spec = importlib.util.spec_from_file_location("namegen_custom", namegen_py_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for func_name in ["to_title", "to_filename", "to_folder"]:
                if hasattr(module, func_name):
                    self._py_funcs[func_name] = getattr(module, func_name)
                    logger.debug(f"Found '{func_name}' function in namegen file.")
                else:
                    logger.debug(f"'{func_name}' function not found, will use default.")
        elif self._parsed_rules is None:
            logger.debug("Using default namegen rules.")
            self._parsed_rules = parse_namegen_rules(DEFAULT_NAMEGEN_RULES)

    def generate(self, series, volumes, parts, fc):
        if self._mode == "py_file":
            args = (series, volumes, parts, fc)

            title_func = self._py_funcs.get("to_title", legacy_title)
            title = title_func(*args)

            if "to_filename" in self._py_funcs:
                filename = self._py_funcs["to_filename"](*args)
            else:
                filename = to_safe_filename(title)

            folder_func = self._py_funcs.get("to_folder", legacy_folder)
            folder = folder_func(*args)

            return title, filename, folder
        else:
            return generate_names(series, volumes, parts, fc, self._parsed_rules)

_init_module()