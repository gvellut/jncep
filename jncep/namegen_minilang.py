from __future__ import annotations

import copy
from enum import Enum, auto
import importlib.resources as imres
import logging
import numbers
import re
import string
import sys

from attr import define
from lark import Lark, Transformer, v_args
from lark.exceptions import LarkError

from .namegen_utils import default_title
from .utils import getConsole, to_safe_filename, to_safe_foldername

logger = logging.getLogger(__name__)
console = getConsole()


GEN_RULE_FUNCS = {}

RULE_SPECIAL_PREVIOUS = "_t"

TITLE_SECTION = "t"
FILENAME_SECTION = "n"
# folder instead of directory since the option to output into folder is --subfolder
FOLDER_SECTION = "f"

# legacy : should be equivalent of
# "t:fc_full>p_title>pn_rm_if_complete>pn_prepend_vn_if_multiple>pn_full>v_title>"
# + "vn_full>s_title>text"
# f:to_series>fc_rm>pn_rm>vn_rm>s_title>text>filesafe_underscore
# but legacy more prudent
# for n use the rules in case t has been defined by user
DEFAULT_NAMEGEN_RULES = "t:legacy_t|n:_t>str_filesafe|f:legacy_f"

# dict : per language
CACHED_STOPWORDS = {}

# should be enough until 15
# TODO for JNC Nina : something different => + i18n of Part, Volume
EN_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}


class ComType(Enum):
    FC = auto()
    PN = auto()
    VN = auto()
    P = auto()
    V = auto()
    S = auto()
    # no V_STR or P_STR => no specific transformation for them like with Series
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


# TODO add booleans
GRAMMAR = """
    ?start: prefix_expr
    prefix_expr: section ("|" section)* -> sections
    ?section: "t" ":" t_expr
        | "n" ":" n_expr
        | "f" ":" f_expr
        | t_expr  // If no prefix is provided, consider it as t_expr
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
        return str(arg.value[1:-1])  # Remove quotes

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
            raise InvalidNamegenRulesError(
                f"Section {TITLE_SECTION} must be present only once"
            )
        self._sections.add(TITLE_SECTION)
        return (TITLE_SECTION, args)

    def n_chain(self, args):
        if FILENAME_SECTION in self._sections:
            raise InvalidNamegenRulesError(
                f"Section {FILENAME_SECTION} must be present only once"
            )
        self._sections.add(FILENAME_SECTION)
        return (FILENAME_SECTION, args)

    def f_chain(self, args):
        if FOLDER_SECTION in self._sections:
            raise InvalidNamegenRulesError(
                f"Section {FOLDER_SECTION} must be present only once"
            )
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

    function_names = _get_functions_between_comments(
        __file__, "# GEN_RULES_BEGIN", "# GEN_RULES_END"
    )

    for name in function_names:
        func = getattr(sys.modules[__name__], name, None)
        if func is not None:
            GEN_RULE_FUNCS[name] = func

    # TODO embed this rule in grammar ? must be in first position
    def _t():
        raise InvalidNamegenRulesError("_t should be the first rule in section")

    # special rule : will be processed before calling, only in first position
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
        raise InvalidNamegenRulesError(
            "Invalid namegen rules provided. Details: " + error_details
        ) from e

    if logger.level <= logging.DEBUG:
        logger.debug(f"parse = {gen_rules}")

    _validate(gen_rules)

    return gen_rules


def _validate(gen_rules):
    for section in gen_rules:
        for func_name, _ in gen_rules[section]:
            if func_name not in GEN_RULE_FUNCS:
                raise InvalidNamegenRulesError(f"Invalid rule: {func_name}")
            # do not check the number of args: can be variable so too complex for now
            # TODO check the number of args ; handle variable args ie *args or default
            # args
    return gen_rules


def generate_names(series, volumes, parts, fc, parsed_namegen_rules):
    # TODO handle language (for JNC Nina)
    values = []
    for section in [TITLE_SECTION, FILENAME_SECTION, FOLDER_SECTION]:
        rules = parsed_namegen_rules[section]

        # TODO add context like language ; struct components insteaf of list
        components, rules = _initialize_components(
            series, volumes, parts, fc, rules, values
        )

        _apply_rules(components, rules)

        if (
            len(components) != 1
            or components[0].tag != ComType.STR
            or not components[0].value
        ):
            raise InvalidNamegenRulesError(
                "Invalid namegen definition: should generate a string (STR_COM)"
            )

        values.append(components[0])

    return [o.value for o in values]


def _initialize_components(series, volumes, parts, fc, rules, outputs):
    # special processing
    # each item is a tuple (func_name, args) so [0][0] to get the func name
    if rules[0][0] == RULE_SPECIAL_PREVIOUS:
        previous = outputs[-1]
        # clone component since it will be modified
        components = [copy.copy(previous)]
        rules = rules[1:]
    else:
        # initilize new for each section since modified
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

        # normally already checked
        f_rule = GEN_RULE_FUNCS[rule_name]

        try:
            # components array modified in place
            f_rule(components, *args)
        except Exception as ex:
            msg = f"Error calling rule {rule_name} with args {args}"
            logger.debug(f"{msg} : {ex}", exc_info=sys.exc_info())
            # abort
            raise NamegenRuleCallError(msg) from ex


# GEN_RULES_BEGIN


def fc_rm(components: list[Component]):
    component = _find_component_type(ComType.FC, components)
    if not component:
        return
    _del_component(components, component)


def fc_rm_if_complete(components: list[Component]):
    component = _find_component_type(ComType.FC, components)
    if not component:
        return
    if component.value.complete:
        _del_component(components, component)


def fc_short(components: list[Component]):
    component = _find_component_type(ComType.FC, components)
    if not component:
        return
    # TODO i18n
    if component.value.complete:
        output = "[C]"
    elif component.value.final:
        output = "[F]"
    else:
        output = ""

    str_component = Component(ComType.STR, output)
    _replace_component(components, component, str_component)


def fc_full(components: list[Component]):
    component = _find_component_type(ComType.FC, components)
    if not component:
        return
    # priority on complete
    # TODO i18n
    if component.value.complete:
        output = "[Complete]"
    elif component.value.final:
        output = "[Final]"
    else:
        output = ""

    str_component = Component(ComType.STR, output)
    _replace_component(components, component, str_component)


def p_to_volume(components: list[Component]):
    component = _find_component_type(ComType.P, components)
    if not component:
        return
    part = component.value
    volume = part.volume
    v_com = Component(ComType.V, volume)
    pn_com = Component(ComType.PN, _default_pn([part]), [part])
    _replace_component(components, component, v_com, pn_com)


def p_to_series(components: list[Component]):
    p_component = _find_component_type(ComType.P, components)
    if not p_component:
        return
    part = p_component.value
    volume = part.volume
    pn_component = Component(ComType.PN, _default_pn([part]), [part])
    vn_component = Component(ComType.VN, _default_vn([volume]), [volume])
    series_component = Component(ComType.S, volume.series)
    _replace_component(
        components, p_component, series_component, vn_component, pn_component
    )


def p_split_part(components: list[Component]):
    p_component = _find_component_type(ComType.P, components)
    if not p_component:
        return

    part = p_component.value
    volume = part.volume

    # no need to parse for parts
    v_com = Component(ComType.V, volume)
    pn_com = Component(ComType.PN, [part.num_in_volume], [part])
    _replace_component(components, p_component, v_com, pn_com)


def p_title(components: list[Component]):
    component = _find_component_type(ComType.P, components)
    if not component:
        return
    output = component.value.raw_data.title

    str_component = Component(ComType.STR, output)
    _replace_component(components, component, str_component)


def pn_rm(components: list[Component]):
    pn_component = _find_component_type(ComType.PN, components)
    if not pn_component:
        return
    _del_component(components, pn_component)


def pn_rm_if_complete(components: list[Component]):
    pn_component = _find_component_type(ComType.PN, components)
    if not pn_component:
        return
    fc_component = _find_component_type(ComType.FC, components)
    if not fc_component:
        return

    if fc_component.value.complete:
        _del_component(components, pn_component)


def pn_prepend_vn_if_multiple(components: list[Component]):
    pn_component = _find_component_type(ComType.PN, components)
    if not pn_component:
        return
    vn_component = _find_component_type(ComType.VN, components)
    if not vn_component:
        return

    if len(vn_component.value) == 1:
        return

    parts = pn_component.base_value
    volumes = vn_component.base_value
    for i, part in enumerate(parts):
        tr_pn = pn_component.value[i]
        volume = part.volume
        volume_i = volumes.index(volume)
        tr_vn = _vn_to_single(vn_component.value[volume_i])
        new_tr_pn = f"{tr_vn}.{tr_pn}"
        pn_component.value[i] = new_tr_pn


def pn_prepend_vn(components: list[Component]):
    pn_component = _find_component_type(ComType.PN, components)
    if not pn_component:
        return
    vn_component = _find_component_type(ComType.VN, components)
    if not vn_component:
        return

    parts = pn_component.base_value
    volumes = vn_component.base_value
    for i, part in enumerate(parts):
        tr_pn = pn_component.value[i]
        volume = part.volume
        volume_i = volumes.index(volume)
        tr_vn = _vn_to_single(vn_component.value[volume_i])
        new_tr_pn = f"{tr_vn}.{tr_pn}"
        pn_component.value[i] = new_tr_pn


def pn_0pad(components: list[Component]):
    component = _find_component_type(ComType.PN, components)
    if not component:
        return
    part_numbers = component.value
    component.value = [str(pn).zfill(2) for pn in part_numbers]


def pn_short(components: list[Component]):
    component = _find_component_type(ComType.PN, components)
    if not component:
        return

    part_numbers = component.value
    if len(part_numbers) > 1:
        part0 = part_numbers[0]
        part1 = part_numbers[-1]
        output = f"{part0}-{part1}"
    else:
        output = f"{part_numbers[0]}"

    str_component = Component(ComType.STR, output)
    _replace_component(components, component, str_component)


def pn_full(components: list[Component]):
    component = _find_component_type(ComType.PN, components)
    if not component:
        return

    # TODO i18n
    part_numbers = component.value
    if len(part_numbers) > 1:
        part0 = part_numbers[0]
        part1 = part_numbers[-1]
        output = f"Parts {part0} to {part1}"
    else:
        output = f"Part {part_numbers[0]}"

    str_component = Component(ComType.STR, output)
    _replace_component(components, component, str_component)


def v_to_series(components: list[Component]):
    component = _find_component_type(ComType.V, components)
    if not component:
        return
    volume = component.value
    series = volume.series
    s_com = Component(ComType.S, series)
    vn_com = Component(ComType.VN, _default_vn([volume]), [volume])
    _replace_component(components, component, s_com, vn_com)


def v_split_volume(components: list[Component]):
    component = _find_component_type(ComType.V, components)
    if not component:
        return

    volume = component.value
    series = volume.series

    diff = _str_diff(volume.raw_data.title, series.raw_data.title)
    if diff:
        vn = _clean(diff)
        vn_parts = _parse_volume_number(vn)

        s_com = Component(ComType.S, series)
        vn_com = Component(ComType.VN, [vn_parts], [volume])
        _replace_component(components, component, s_com, vn_com)


def _parse_volume_number(vn):
    # TODO i18n
    volume_match = re.search(r"Volume (\d+)", vn)
    part_match = re.search(r"Part (\w+)", vn)
    result = []
    if volume_match:
        result.append((int(volume_match.group(1)), "Volume"))
    if part_match:
        result.append((part_match.group(1), "Part"))
    result.sort(key=lambda x: vn.index(x[1]))
    if not result:
        # cannot parse into the Volume, Part : keep the incoming vn (non number)
        # can happen for example Arifureta: "Short Stories" for the side stories
        # volume number
        result = [(vn, VnType.VN_SPECIAL)]
    return result


def v_title(components: list[Component]):
    component = _find_component_type(ComType.V, components)
    if not component:
        return
    output = component.value.raw_data.title

    str_component = Component(ComType.STR, output)
    _replace_component(components, component, str_component)


def vn_rm(components: list[Component]):
    vn_component = _find_component_type(ComType.VN, components)
    if not vn_component:
        return
    _del_component(components, vn_component)


def vn_rm_if_pn(components: list[Component]):
    vn_component = _find_component_type(ComType.VN, components)
    if not vn_component:
        return
    pn_component = _find_component_type(ComType.PN, components)
    if not pn_component:
        return
    _del_component(components, vn_component)


def vn_number(components: list[Component]):
    vn_component = _find_component_type(ComType.VN, components)
    if not vn_component:
        return

    volume_numbers = vn_component.value
    # for voumes with 2 parts : like AoaB : Part 5 Volume 2
    # or Volume 3 Part Four
    for v in volume_numbers:
        # TODO specific struct : CompoundVN
        # => add when implementing v_split_volume
        for j, p in enumerate(v):
            if isinstance(p[0], str):
                # TODO i18n
                p0l = p[0].lower()
                if p0l in EN_NUMBERS:
                    n = EN_NUMBERS[p0l]
                    v[j] = (n, p[1])


def vn_merge(components: list[Component]):
    vn_component = _find_component_type(ComType.VN, components)
    if not vn_component:
        return

    volume_numbers = vn_component.value
    for i, v in enumerate(volume_numbers):
        if len(v) > 1:
            vn = _vn_to_single(v)
            volume_numbers[i] = [(vn, VnType.VN_MERGED)]


def vn_0pad(components: list[Component]):
    vn_component = _find_component_type(ComType.VN, components)
    if not vn_component:
        return

    volume_numbers = vn_component.value
    for i, v in enumerate(volume_numbers):
        # TODO do instead: int(...). + format ?
        padded = [(str(p[0]).zfill(2), p[1]) for p in v]
        volume_numbers[i] = padded


def vn_short(components: list[Component]):
    component = _find_component_type(ComType.VN, components)
    if not component:
        return

    # implicit
    vn_merge(components)

    volumes = component.value
    if len(volumes) > 1:
        # may look weird for VN_SPECIAL but OK
        volume0 = volumes[0]
        volume1 = volumes[-1]
        volume_nums = f"{volume0[0][0]}-{volume1[0][0]}"
        output = volume_nums
    else:
        # TODO use struct : array indexing is too complex
        volume = volumes[0]
        output = volume[0][0]

    str_component = Component(ComType.STR, output)
    _replace_component(components, component, str_component)


def vn_full(components: list[Component]):
    component = _find_component_type(ComType.VN, components)
    if not component:
        return

    volumes = component.base_value
    if len(volumes) > 1:
        # implicit
        vn_merge(components)

        base_vns = component.value
        volume_nums = [str(vn[0][0]) for vn in base_vns]
        volume_nums = ", ".join(volume_nums[:-1]) + " & " + volume_nums[-1]
        # TODO i18n
        output = f"Volumes {volume_nums}"
    else:
        # in this case : the 2 part Volume number may have been preserved
        base_vns = component.value
        vn = base_vns[0]
        if len(vn) > 1:
            # preserved
            # [(2, "Part"), (5, "Volume")]
            nparts = []
            for p in vn:
                if p[1] == VnType.VN_SPECIAL:
                    nparts.append(p[0])
                else:
                    nparts.append(f"{p[1]} {p[0]}")
            output = " ".join(nparts)
        else:
            # [(2, "VN_INTERNAL")] or [(2, "Volume")] : 2nd case if v_parse_vn used
            vn0 = vn[0]
            if vn0[1] == VnType.VN_SPECIAL:
                # TODO keep track of the special status: so no addition of : after
                # series title when merging the strings
                o = vn0[0]
            else:
                # should be always Volume if only one of vn
                # TODO i18n
                o = f"Volume {vn0[0]}"
            output = o

    str_component = Component(ComType.STR, output)
    _replace_component(components, component, str_component)


def to_series(components: list[Component]):
    v_to_series(components)
    p_to_series(components)


def s_title(components: list[Component]):
    component = _find_component_type(ComType.S, components)
    if not component:
        return
    output = component.value.raw_data.title

    str_component = Component(ComType.S_STR, output)
    _replace_component(components, component, str_component)


def s_slug(components: list[Component]):
    component = _find_component_type(ComType.S, components)
    if not component:
        return
    output = component.value.raw_data.slug

    str_component = Component(ComType.S_STR, output)
    _replace_component(components, component, str_component)


def ss_rm_stopwords(components: list[Component]):
    component = _find_component_type(ComType.S_STR, components)
    if not component:
        return

    # TODO i18n
    stopwords = _load_stopwords("en")

    title = component.value
    words = title.split()
    no_stopwords = [word for word in words if word not in stopwords]
    output = " ".join(no_stopwords)

    component.value = output


def ss_rm_subtitle(components: list[Component]):
    component = _find_component_type(ComType.S_STR, components)
    if not component:
        return
    title = component.value
    output = title.split(":", 1)[0].strip()

    component.value = output


def ss_acronym(components: list[Component]):
    component = _find_component_type(ComType.S_STR, components)
    if not component:
        return
    title = component.value
    title = "".join(ch for ch in title if ch not in string.punctuation)
    words = title.split()
    acronym = "".join(word[0] for word in words)
    output = acronym

    component.value = output


def ss_first(components: list[Component], first_n=3):
    component = _find_component_type(ComType.S_STR, components)
    if not component:
        return
    title = component.value
    title = "".join(ch for ch in title if ch not in string.punctuation)
    words = title.split()
    acronym = "".join(word[:first_n].capitalize() for word in words)
    output = acronym

    component.value = output


def ss_max_len(components: list[Component], max_len_n=30):
    component = _find_component_type(ComType.S_STR, components)
    if not component:
        return
    output = component.value[:max_len_n]

    component.value = output


def legacy_t(components: list[Component]):
    p_component = _find_component_type(ComType.P, components)
    v_component = _find_component_type(ComType.V, components)
    s_component = _find_component_type(ComType.S, components)
    fc_component = _find_component_type(ComType.FC, components)
    fc = fc_component.value
    if p_component:
        part = p_component.value
        title = default_title(part.volume.series, [part.volume], [part], fc)
    elif s_component:
        vn_component = _find_component_type(ComType.VN, components)
        pn_component = _find_component_type(ComType.PN, components)
        title = default_title(
            s_component.value, vn_component.base_value, pn_component.base_value, fc
        )
    else:
        pn_component = _find_component_type(ComType.PN, components)
        title = default_title(
            v_component.value.series, [v_component.value], pn_component.base_value, fc
        )
    _replace_all(components, Component(ComType.STR, title))


def legacy_f(components: list[Component]):
    # assume launched first, not after transformation
    # must be one of the three according to _initialize_components
    p_component = _find_component_type(ComType.P, components)
    v_component = _find_component_type(ComType.V, components)
    s_component = _find_component_type(ComType.S, components)

    if p_component:
        series = p_component.value.volume.series
    elif v_component:
        series = v_component.value.series
    elif s_component:
        series = s_component.value

    folder = to_safe_foldername(series.raw_data.title)

    str_com = Component(ComType.STR, folder)
    _replace_all(components, str_com)


# no boolean in the rule language so use integer for flag
def to_string(components: list[Component], add_colon=0):
    str_values = []
    for c in components:
        if c.tag == ComType.S_STR:
            if not c.value:
                continue

            str_value = c.value
            if add_colon:
                # only if doesn't end in punctuation mark
                if str_value[-1] in string.punctuation:
                    str_values.append(str_value)
                else:
                    str_values.append(str_value + ":")
            else:
                str_values.append(str_value)
        elif c.tag == ComType.STR:
            if not c.value:
                continue
            str_values.append(c.value)

    str_value = " ".join(str_values)
    str_component = Component(ComType.STR, str_value)
    _replace_all(components, str_component)


def str_rm_space(components: list[Component]):
    str_component = _find_str_component_implicit_string(components)
    str_component.value = str_component.value.replace(" ", "")


def str_replace_space(components: list[Component], char_replace="_"):
    str_component = _find_str_component_implicit_string(components)
    str_component.value = str_component.value.replace(" ", char_replace)


def str_filesafe(components: list[Component], char_replace="_", preserve_chars=""):
    str_component = _find_str_component_implicit_string(components)
    str_component.value = to_safe_filename(
        str_component.value, char_replace, preserve_chars
    )


# GEN_RULES_END


def _find_component_type(ctype: ComType, components: list[Component]):
    for component in components:
        if component.tag == ctype:
            return component

    return None


def _find_str_component_implicit_string(components):
    str_component = _find_component_type(ComType.STR, components)
    if not str_component:
        # implicit
        to_string(components)
        str_component = _find_component_type(ComType.STR, components)

        # TODO check instead when the STR is created
        if not str_component.value:
            raise EmptyStringError()

    return str_component


def _default_vn(volumes):
    # multiple "parts" for volumes possible : Usually 1 but sometimes
    # Volume 1 Part Two or Part 3 Volume 8 => so nested array
    volume_numbers = [[(v.num, VnType.VN_INTERNAL)] for v in volumes]
    return volume_numbers


def _default_pn(parts):
    part_numbers = [p.num_in_volume for p in parts]
    return part_numbers


def _vn_to_single(vn):
    if _is_list(vn):
        items = [str(p[0]) for p in vn]
        return ".".join(items)
    return vn[0]


def _is_number(v):
    return isinstance(v, numbers.Number)


def _is_list(v):
    return isinstance(v, list)


def _replace_component(components, item, *items):
    item_index = _index(components, item)
    components[item_index : item_index + 1] = items


def _del_component(components, item):
    item_index = _index(components, item)
    del components[item_index]


def _replace_all(components, *items):
    components[:] = items


def _index(components, item):
    item_index = next(
        (i for i, component in enumerate(components) if component is item), None
    )
    return item_index


def _str_diff(str1, str2):
    if str1.startswith(str2):
        return str1[len(str2) :]
    return None


def _clean(s: str):
    return s.strip(":").strip()


def _load_stopwords(language):
    if language in CACHED_STOPWORDS:
        return CACHED_STOPWORDS[language]

    path = imres.files(__package__) / "res" / f"{language}_stopwords.txt"
    if not path.is_file():
        raise UnsupportedStopwordLanguage(f"Unsupported: {language}")

    with path.open("r", encoding="utf-8") as f:
        # 3.8 is the minimal version anyway so := is supported
        stopwords = [sw for w in f.readlines() if (sw := w.strip())]
        CACHED_STOPWORDS[language] = set(stopwords)

    return CACHED_STOPWORDS[language]


def _get_functions_between_comments(filename, start_comment, end_comment):
    with open(filename) as file:
        lines = file.readlines()

    start_line = next(
        (i for i, line in enumerate(lines) if line.startswith(start_comment)), None
    )
    end_line = next(
        (i for i, line in enumerate(lines) if line.startswith(end_comment)), None
    )

    if start_line is None or end_line is None:
        return []

    function_lines = lines[start_line:end_line]
    functions = [
        line
        for line in function_lines
        if line.strip().startswith("def ") and not line.strip().startswith("def _")
    ]

    return [f.split("(")[0].replace("def ", "").strip() for f in functions]


_init_module()
