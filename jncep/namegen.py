from __future__ import annotations

from collections import namedtuple
import copy
from enum import auto, Enum
import logging
import numbers
import re
import string
import sys
from typing import List

from attr import define
import importlib_resources as imres

from .utils import getConsole, to_safe_filename, to_safe_filename_limited

logger = logging.getLogger(__name__)
console = getConsole()

GEN_RULES = None

DEF_SEP = "|"
RULE_SEP = ">"

RULE_SPECIAL_PREVIOUS = "_t"

TITLE_SECTION = "t"
FILENAME_SECTION = "n"
# folder instead of directory since the option to output into folder is --subfolder
FOLDER_SECTION = "f"

# legacy : should be equivalent of
# "t:fc_full>p_title>pn_rm_if_complete>pn_prepend_vn_if_multiple>pn_full>v_title>"
# + "vn_full>s_title>text"
# n:_t>filesafe_underscore
# f:to_series>fc_rm>pn_rm>vn_rm>s_title>text>filesafe_underscore
# but legacy more prudent
DEFAULT_NAMEGEN_RULES = "t:t_legacy|n:n_legacy|f:f_legacy"

CACHED_PARSED_NAMEGEGEN_RULES = None
# dict : per language
CACHED_STOPWORDS = {}

# TODO for JNC Nina : something different => + i18n of Part, Volume
# should be enough until 15
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
}


class ComType(Enum):
    FC_COM = auto()
    PN_COM = auto()
    VN_COM = auto()
    P_COM = auto()
    V_COM = auto()
    S_COM = auto()
    STR_COM = auto()


class VnType(Enum):
    VN_INTERNAL = auto()
    VN_MERGED = auto()
    VN_SPECIAL = auto()


@define
class Component:
    tag: ComType
    value: object
    base_value: object = None
    output: str = None


FC = namedtuple("FC", "final complete")


class InvalidNamegenRulesError(Exception):
    pass


class UnsupportedStopwordLanguage(Exception):
    pass


def _init_module():
    global GEN_RULES

    gen_rules = _get_functions_between_comments(
        __file__, "# GEN_RULES_BEGIN", "# GEN_RULES_END"
    )
    # special rule
    gen_rules.append("_t")
    GEN_RULES = gen_rules


def parse_namegen_rules(namegen_rules):
    global CACHED_PARSED_NAMEGEGEN_RULES

    if CACHED_PARSED_NAMEGEGEN_RULES:
        return CACHED_PARSED_NAMEGEGEN_RULES

    default_gen_rules = _do_parse_namegen_rules(DEFAULT_NAMEGEN_RULES)

    if namegen_rules:
        # always the same during the execution so read once and cache
        gen_rules = _do_parse_namegen_rules(namegen_rules)

        if TITLE_SECTION not in gen_rules:
            gen_rules[TITLE_SECTION] = default_gen_rules[TITLE_SECTION]
        if FILENAME_SECTION not in gen_rules:
            gen_rules[FILENAME_SECTION] = default_gen_rules[FILENAME_SECTION]
        if FOLDER_SECTION not in gen_rules:
            gen_rules[FOLDER_SECTION] = default_gen_rules[FOLDER_SECTION]

        CACHED_PARSED_NAMEGEGEN_RULES = gen_rules
    else:
        CACHED_PARSED_NAMEGEGEN_RULES = default_gen_rules

    return CACHED_PARSED_NAMEGEGEN_RULES


def _do_parse_namegen_rules(namegen_rules):
    try:
        tnf = namegen_rules.split(DEF_SEP)
        tnf_defs = _extract_components(tnf)
        if logger.level <= logging.DEBUG:
            logger.debug(f"tnf = {tnf_defs}")

        gen_rules = {}
        for key, gen_definition in tnf_defs.items():
            if gen_definition:
                rules = _validate(gen_definition.split(RULE_SEP))
                gen_rules[key] = rules

        return gen_rules

    except Exception as ex:
        # TODO more precise feedback
        raise InvalidNamegenRulesError(f"Invalid: {namegen_rules}") from ex


def _extract_components(tnf):
    tnf_defs = {}
    for component in tnf:
        for c_def in [TITLE_SECTION, FILENAME_SECTION, FOLDER_SECTION]:
            if component.startswith(c_def + ":"):
                # strip header
                tnf_defs[c_def] = component[2:]

    if not tnf_defs and len(tnf) == 1:
        # assume the entire string only contains the title (without prefix)
        # will throw an error later when parsing the rules if assumption is wrong
        tnf_defs[TITLE_SECTION] = tnf[0]

    return tnf_defs


def _validate(arr):
    rules = []
    for c in arr:
        c = c.strip()
        if c not in GEN_RULES:
            raise InvalidNamegenRulesError(f"Invalid rule: {c}")
        rules.append(c)
    return rules


def generate_names(series, volumes, parts, fc, parsed_namegen_rules):
    # TODO handle language (for JNC Nina)
    values = []
    for section in [TITLE_SECTION, FILENAME_SECTION, FOLDER_SECTION]:
        rules = parsed_namegen_rules[section]

        components, rules = _initialize_components(
            series, volumes, parts, fc, rules, values
        )

        _apply_rules(components, rules)

        if (
            len(components) != 1
            or components[0].tag != ComType.STR_COM
            or not components[0].value
        ):
            raise InvalidNamegenRulesError(
                "Invalid namegen definition: should generate a string (STR_COM)"
            )

        values.append(components[0])

    return [o.value for o in values]


def _initialize_components(series, volumes, parts, fc, rules, outputs):
    # special processing
    if rules[0] == RULE_SPECIAL_PREVIOUS:
        previous = outputs[-1]
        # clone component since it will be modified
        components = [copy.copy(previous)]
        rules = rules[1:]
    else:
        # initilize new for each section since modified
        components = _default_initialize_components(series, volumes, parts, fc)

    return components, rules


def _default_initialize_components(series, volumes, parts, fc):
    # TODO initilize series, volume, part structs specific to this processing
    # to handle split, pad, merge
    # DONE ? check
    if len(parts) == 1:
        components = [Component(ComType.P_COM, parts[0])]
    else:
        if len(volumes) > 1:
            components = [
                Component(ComType.S_COM, series),
                Component(ComType.VN_COM, _default_vn(volumes), volumes),
                Component(ComType.PN_COM, _default_pn(parts), parts),
            ]
        else:
            components = [
                Component(ComType.V_COM, volumes[0]),
                Component(ComType.PN_COM, _default_pn(parts), parts),
            ]

    components.append(Component(ComType.FC_COM, fc))

    return components


def _apply_rules(components: List[Component], rules):
    for rule in rules:
        f_rule = getattr(sys.modules[__name__], rule, None)
        logger.debug(f"Apply rule: {rule}")
        # array modified in place
        f_rule(components)


# GEN_RULES_BEGIN


def fc_rm(components: List[Component]):
    component = _find_component_type(ComType.FC_COM, components)
    if not component:
        return
    _del_component(components, component)


def fc_rm_if_complete(components: List[Component]):
    component = _find_component_type(ComType.FC_COM, components)
    if not component:
        return
    if component.value.complete:
        _del_component(components, component)


def fc_short(components: List[Component]):
    component = _find_component_type(ComType.FC_COM, components)
    if not component:
        return
    if component.value.complete:
        component.output = "[C]"
    elif component.value.final:
        component.output = "[F]"


def fc_full(components: List[Component]):
    component = _find_component_type(ComType.FC_COM, components)
    if not component:
        return
    # priority on complete
    if component.value.complete:
        component.output = "[Complete]"
    elif component.value.final:
        component.output = "[Final]"


def p_to_volume(components: List[Component]):
    component = _find_component_type(ComType.P_COM, components)
    if not component:
        return
    part = component.value
    volume = part.volume
    v_com = Component(ComType.V_COM, volume)
    pn_com = Component(ComType.PN_COM, _default_pn([part]), [part])
    _replace_component(components, component, v_com, pn_com)


def p_to_series(components: List[Component]):
    p_component = _find_component_type(ComType.P_COM, components)
    if not p_component:
        return
    part = p_component.value
    volume = part.volume
    pn_component = Component(ComType.PN_COM, _default_pn([part]), [part])
    vn_component = Component(ComType.VN_COM, _default_vn([volume]), [volume])
    series_component = Component(ComType.S_COM, volume.series)
    _replace_component(
        components, p_component, series_component, vn_component, pn_component
    )


def p_split_part(components: List[Component]):
    p_component = _find_component_type(ComType.P_COM, components)
    if not p_component:
        return

    part = p_component.value
    volume = part.volume

    # no need to parse for parts
    v_com = Component(ComType.V_COM, volume)
    pn_com = Component(ComType.PN_COM, [part.num_in_volume], [part])
    _replace_component(components, p_component, v_com, pn_com)


def p_title(components: List[Component]):
    component = _find_component_type(ComType.P_COM, components)
    if not component:
        return
    component.output = component.value.raw_data.title


def pn_rm(components: List[Component]):
    pn_component = _find_component_type(ComType.PN_COM, components)
    if not pn_component:
        return
    _del_component(components, pn_component)


def pn_rm_if_complete(components: List[Component]):
    pn_component = _find_component_type(ComType.PN_COM, components)
    if not pn_component:
        return
    fc_component = _find_component_type(ComType.FC_COM, components)
    if not fc_component:
        return

    if fc_component.value.complete:
        _del_component(components, pn_component)


def pn_prepend_vn_if_multiple(components: List[Component]):
    pn_component = _find_component_type(ComType.PN_COM, components)
    if not pn_component:
        return
    vn_component = _find_component_type(ComType.VN_COM, components)
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


def pn_prepend_vn(components: List[Component]):
    pn_component = _find_component_type(ComType.PN_COM, components)
    if not pn_component:
        return
    vn_component = _find_component_type(ComType.VN_COM, components)
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


def pn_0pad(components: List[Component]):
    component = _find_component_type(ComType.PN_COM, components)
    if not component:
        return
    part_numbers = component.value
    component.value = [str(pn).zfill(2) for pn in part_numbers]


def pn_short(components: List[Component]):
    component = _find_component_type(ComType.PN_COM, components)
    if not component:
        return

    part_numbers = component.value
    if len(part_numbers) > 1:
        part0 = part_numbers[0]
        part1 = part_numbers[-1]
        component.output = f"{part0}-{part1}"
    else:
        component.output = f"{part_numbers[0]}"


def pn_full(components: List[Component]):
    component = _find_component_type(ComType.PN_COM, components)
    if not component:
        return

    part_numbers = component.value
    if len(part_numbers) > 1:
        part0 = part_numbers[0]
        part1 = part_numbers[-1]
        component.output = f"Parts {part0} to {part1}"
    else:
        component.output = f"Part {part_numbers[0]}"


def v_to_series(components: List[Component]):
    component = _find_component_type(ComType.V_COM, components)
    if not component:
        return
    volume = component.value
    series = volume.series
    s_com = Component(ComType.S_COM, series)
    vn_com = Component(ComType.VN_COM, _default_vn([volume]), [volume])
    _replace_component(components, component, s_com, vn_com)


def v_split_volume(components: List[Component]):
    component = _find_component_type(ComType.V_COM, components)
    if not component:
        return

    volume = component.value
    series = volume.series

    diff = _str_diff(volume.raw_data.title, series.raw_data.title)
    if diff:
        vn = _clean(diff)
        vn_parts = _parse_volume_number(vn)

        s_com = Component(ComType.S_COM, series)
        vn_com = Component(ComType.VN_COM, [vn_parts], [volume])
        _replace_component(components, component, s_com, vn_com)


def _parse_volume_number(vn):
    # TODO adapt for JNC Nina : diff lang
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


def v_title(components: List[Component]):
    component = _find_component_type(ComType.V_COM, components)
    if not component:
        return
    component.output = component.value.raw_data.title


def vn_rm(components: List[Component]):
    vn_component = _find_component_type(ComType.VN_COM, components)
    if not vn_component:
        return
    _del_component(components, vn_component)


def vn_rm_if_pn(components: List[Component]):
    vn_component = _find_component_type(ComType.VN_COM, components)
    if not vn_component:
        return
    pn_component = _find_component_type(ComType.PN_COM, components)
    if not pn_component:
        return
    _del_component(components, vn_component)


def vn_number(components: List[Component]):
    vn_component = _find_component_type(ComType.VN_COM, components)
    if not vn_component:
        return

    volume_numbers = vn_component.value
    # for voumes with 2 parts : like AoaB : Part 5 Volume 2
    # or Volume 3 Part Four
    for v in volume_numbers:
        # TODO specific type : CompoundVN
        # => add when implementing v_split_volume
        for j, p in enumerate(v):
            if isinstance(p[0], str):
                # TODO for JNC Nina : something diff
                p0l = p[0].lower()
                if p0l in EN_NUMBERS:
                    n = EN_NUMBERS[p0l]
                    v[j] = (n, p[1])


def vn_merge(components: List[Component]):
    vn_component = _find_component_type(ComType.VN_COM, components)
    if not vn_component:
        return

    volume_numbers = vn_component.value
    for i, v in enumerate(volume_numbers):
        if len(v) > 1:
            vn = _vn_to_single(v)
            volume_numbers[i] = [(vn, VnType.VN_MERGED)]


def vn_0pad(components: List[Component]):
    vn_component = _find_component_type(ComType.VN_COM, components)
    if not vn_component:
        return

    volume_numbers = vn_component.value
    for i, v in enumerate(volume_numbers):
        # TODO do instead: int(...). + format ?
        padded = [(str(p[0]).zfill(2), p[1]) for p in v]
        volume_numbers[i] = padded


def vn_short(components: List[Component]):
    component = _find_component_type(ComType.VN_COM, components)
    if not component:
        return

    # implicit
    vn_merge(components)

    volumes = component.value
    if len(volumes) > 1:
        # may look weird for VN_SPECIAL but OK
        volume0 = volumes[0][0]
        volume1 = volumes[1][0]
        volume_nums = f"{volume0}-{volume1}"
        component.output = f"{volume_nums}"
    else:
        volume = volumes[0][0]
        component.output = f"{volume.num}"


def vn_full(components: List[Component]):
    component = _find_component_type(ComType.VN_COM, components)
    if not component:
        return

    volumes = component.base_value
    if len(volumes) > 1:
        # implicit
        vn_merge(components)

        base_vns = component.value
        volume_nums = [str(vn[0][0]) for vn in base_vns]
        volume_nums = ", ".join(volume_nums[:-1]) + " & " + volume_nums[-1]
        component.output = f"Volumes {volume_nums}"
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
            component.output = " ".join(nparts)
        else:
            # [(2, "VN_INTERNAL")] or [(2, "Volume")] : 2nd case if v_parse_vn used
            vn0 = vn[0]
            if vn0[1] == VnType.VN_SPECIAL:
                o = vn0[0]
            else:
                # should be always Volume if only one of vn
                o = f"Volume {vn0[0]}"
            component.output = o


def to_series(components: List[Component]):
    v_to_series(components)
    p_to_series(components)


def s_title(components: List[Component]):
    component = _find_component_type(ComType.S_COM, components)
    if not component:
        return
    component.output = component.value.raw_data.title


def s_slug(components: List[Component]):
    component = _find_component_type(ComType.S_COM, components)
    if not component:
        return
    component.output = component.value.raw_data.slug


def s_rm_stopwords(components: List[Component]):
    component = _find_component_type(ComType.S_COM, components, has_output=True)
    if not component:
        return

    # TODO take language as argument
    stopwords = _load_stopwords("en")

    title = component.output
    words = title.split()
    no_stopwords = [word for word in words if word not in stopwords]
    component.output = " ".join(no_stopwords)


def s_rm_subtitle(components: List[Component]):
    component = _find_component_type(ComType.S_COM, components, has_output=True)
    if not component:
        return
    title = component.output
    component.output = title.split(":", 1)[0]


def s_acronym(components: List[Component]):
    component = _find_component_type(ComType.S_COM, components, has_output=True)
    if not component:
        return
    title = component.output
    title = "".join(ch for ch in title if ch not in string.punctuation)
    words = title.split()
    acronym = "".join(word[0] for word in words)
    component.output = acronym


def s_first3(components: List[Component]):
    component = _find_component_type(ComType.S_COM, components, has_output=True)
    if not component:
        return
    title = component.output
    title = "".join(ch for ch in title if ch not in string.punctuation)
    words = title.split()
    acronym = "".join(word[:3].capitalize() for word in words)
    component.output = acronym


def s_max_len30(components: List[Component]):
    component = _find_component_type(ComType.S_COM, components, has_output=True)
    if not component or not component.output:
        return

    component.output = component.output[:30]


def t_legacy(components: List[Component]):
    # assume launched first, not after transformation
    p_component = _find_component_type(ComType.P_COM, components)
    v_component = _find_component_type(ComType.V_COM, components)
    s_component = _find_component_type(ComType.S_COM, components)
    fc_component = _find_component_type(ComType.FC_COM, components)

    if p_component:
        # single part
        part = p_component.value
        title_base = part.raw_data.title

        suffix = ""
        is_final = fc_component.value.final
        if is_final:
            suffix = " [Final]"

        title = f"{title_base}{suffix}"
    else:
        if s_component:
            # multiple volumes
            series = s_component.value

            title_base = series.raw_data.title

            vn_component = _find_component_type(ComType.VN_COM, components)
            volumes = vn_component.base_value
            # ordered already
            volume_nums = [str(v.num) for v in volumes]
            volume_nums = ", ".join(volume_nums[:-1]) + " & " + volume_nums[-1]
            volume_segment = f"Volumes {volume_nums}"

            pn_component = _find_component_type(ComType.PN_COM, components)
            parts = pn_component.base_value
            volume_num0 = parts[0].volume.num
            part_num0 = parts[0].num_in_volume
            volume_num1 = parts[-1].volume.num
            part_num1 = parts[-1].num_in_volume

            # check only last part in the epub
            suffix = ""
            is_final = fc_component.value.final
            if is_final:
                suffix = " - Final"

            part_segment = (
                f"Parts {volume_num0}.{part_num0} to "
                f"{volume_num1}.{part_num1}{suffix}"
            )

            if title_base[-1] in string.punctuation:
                # like JNC : no double punctuation mark
                colon = ""
            else:
                colon = ":"
            title = f"{title_base}{colon} {volume_segment} [{part_segment}]"

        else:
            # single volume
            volume = v_component.value
            title_base = volume.raw_data.title

            pn_component = _find_component_type(ComType.PN_COM, components)
            parts = pn_component.base_value

            part_num0 = parts[0].num_in_volume
            part_num1 = parts[-1].num_in_volume

            is_complete = fc_component.value.complete
            is_final = fc_component.value.final
            if is_complete:
                part_segment = "Complete"
            else:
                # check the last part in the epub
                suffix = ""
                if is_final:
                    suffix = " - Final"
                part_segment = f"Parts {part_num0} to {part_num1}{suffix}"

            title = f"{title_base} [{part_segment}]"

    str_component = Component(ComType.STR_COM, title)
    _replace_all(components, str_component)


def n_legacy(components: List[Component]):
    t_legacy(components)

    str_com = _find_str_component_implicit_text(components)
    title = str_com.value
    filename = to_safe_filename(title)

    str_com = Component(ComType.STR_COM, filename)
    _replace_all(components, str_com)


def f_legacy(components: List[Component]):
    # assume launched first, not after transformation
    # must be one of the three according to _initialize_components
    p_component = _find_component_type(ComType.P_COM, components)
    v_component = _find_component_type(ComType.V_COM, components)
    s_component = _find_component_type(ComType.S_COM, components)

    if p_component:
        series = p_component.value.volume.series
    elif v_component:
        series = v_component.value.series
    elif s_component:
        series = s_component.value

    folder = to_safe_filename(series.raw_data.title)

    str_com = Component(ComType.STR_COM, folder)
    _replace_all(components, str_com)


def text(components: List[Component]):
    # TODO raise exc if component doesn't have output ?
    outputs = [c.output for c in components if c.output]
    # TODO add : after s_com ? like in the legacy version
    str_value = " ".join(outputs)
    # for STR_COM, its value is the string (not output)
    str_component = Component(ComType.STR_COM, str_value)
    _replace_all(components, str_component)


def rm_space(components: List[Component]):
    str_component = _find_str_component_implicit_text(components)
    str_component.value = str_component.value.replace(" ", "")


def replace_space_by_underscore(components: List[Component]):
    str_component = _find_str_component_implicit_text(components)
    str_component.value = str_component.value.replace(" ", "_")


def filesafe_underscore(components: List[Component]):
    str_component = _find_str_component_implicit_text(components)
    str_component.value = to_safe_filename(str_component.value, "_")


# TODO allow passing of arguments : for example with ? after rule name
def filesafe_underscore_limited(components: List[Component]):
    str_component = _find_str_component_implicit_text(components)
    str_component.value = to_safe_filename_limited(str_component.value, "_")


def filesafe_space(components: List[Component]):
    str_component = _find_str_component_implicit_text(components)
    str_component.value = to_safe_filename(str_component.value, " ")


def filesafe_space_limited(components: List[Component]):
    str_component = _find_str_component_implicit_text(components)
    str_component.value = to_safe_filename_limited(str_component.value, " ")


# GEN_RULES_END


def _find_component_type(ctype: ComType, components: List[Component], has_output=None):
    for component in components:
        if component.tag == ctype:
            # supposes a single instance of the type
            if has_output and component.output is None:
                return None
            return component

    return None


def _find_str_component_implicit_text(components):
    str_component = _find_component_type(ComType.STR_COM, components)
    if not str_component:
        # implicit
        text(components)
        str_component = _find_component_type(ComType.STR_COM, components)

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
    with open(filename, "r") as file:
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
