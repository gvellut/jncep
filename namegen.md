# namegen

This functionality allows the renaming of output EPUB file names, as well as the EPUB title (since it appears in the EPUB reader interface) and folder name.
A list of rules (to choose from a predefined list) are applied to transform the titles.

It is not very well documented or tested so if you need something and you don't see how to do it, you can open an issue and I will try to help (or tell you it is not possible...)
The version inside the master Github repo is missing some support for JNC Nina (will be added before release).

## Note about JNC Nina

Some functionalities (parsing and title generation) are not yet implemented outside English (ie for the main J-Novel Club website) so it is recommended not to use this functionnality with JNC Nina (or not use the rules that have issues with multilingual support).

Full support will be added for the next version.

## Python-based Naming

In addition to the mini-language, you can provide a Python file (`.py`) to control the naming of your EPUBs. This offers greater flexibility for complex naming schemes.

### How it Works

You can specify a Python file for name generation in two ways:
1.  **Explicitly via the `--namegen` option:** Pass the absolute path to your `.py` file.
    ```bash
    jncep ... --namegen /path/to/your/namegen.py
    ```
2.  **Automatically from the config directory:** Place a file named `namegen.py` in your `jncep` config directory. `jncep` will automatically detect and use it. You can find your config directory by running `jncep config show`.

The Python file can contain up to three functions:
- `to_title(series, volumes, parts, fc)`: Returns the EPUB title (a string).
- `to_filename(series, volumes, parts, fc)`: Returns the EPUB filename without the extension (a string).
- `to_folder(series, volumes, parts, fc)`: Returns the name of the subfolder for the EPUB (a string).

If any of these functions are not defined in your file, `jncep` will fall back to the default naming logic for that specific part.

### Generating a Template

To get started, you can generate a template `namegen.py` file with the following command:
```bash
jncep config generate-namegen-py
```
This will create a `namegen.py` file in your config directory with pre-defined functions and helpful comments. You can also specify an output path:
```bash
jncep config generate-namegen-py --output /path/to/generate/
```

### LLM Blurb for `namegen.py`

If you want to use an LLM to help you write a `namegen.py` file, you can use the following blurb as a preface to your request. It provides the necessary context for the LLM to generate a valid and functional script.

---

**LLM Blurb:**

I need you to write a Python script named `namegen.py` for `jncep`, a tool that creates EPUBs from J-Novel Club. This script will define how the EPUB title, filename, and subfolder are generated. The script can contain three functions: `to_title`, `to_filename`, and `to_folder`.

Here are the function signatures and the data structures you will work with:

- `to_title(series: "Series", volumes: list["Volume"], parts: list["Part"], fc: "FC") -> str`
- `to_filename(series: "Series", volumes: list["Volume"], parts: list["Part"], fc: "FC") -> str`
- `to_folder(series: "Series", volumes: list["Volume"], parts: list["Part"], fc: "FC") -> str`

The input parameters are:
- `series`: An object representing the novel series. It has a `raw_data` attribute with a `title` field (e.g., `series.raw_data.title`).
- `volumes`: A list of volume objects included in the EPUB. Each `volume` has `raw_data` with a `title` and a `num` (the volume number).
- `parts`: A list of part objects. Each `part` has `raw_data` with a `title` and a `num_in_volume`.
- `fc`: A named tuple with two boolean flags: `fc.final` (is the last part of a volume) and `fc.complete` (is the entire volume complete).

Your script should handle three primary scenarios for EPUB generation:
1.  **Single Part:** `parts` contains one item.
2.  **Multiple Parts in a Single Volume:** `volumes` contains one item, and `parts` contains multiple items.
3.  **Multiple Parts across Multiple Volumes:** `volumes` and `parts` both contain multiple items.

You can import and use helper functions from `jncep.namegen_utils`, such as `legacy_title`, `legacy_filename`, and `legacy_folder`, to replicate the default behavior.

---

## Mini-language Samples

- `t:legacy_t|n:_t>str_filesafe|f:legacy_f`: this is the defaut rule if no namegen argument is defined. It defines rules for the 3 sections: `t:` (EPUB title), `n:` (file name) and `f:` (folder name). The special rule `_t` is used: it takes the output of the `t:` rule. The rules for `t:` and `f:` use the legacy rules. Note that the folder will be generated only if the `--subfolder` argument is passed to the jncep command: Otherwise it has no effect.
- `t:fc_full>p_title>pn_rm_if_complete>pn_prepend_vn_if_multiple>pn_full>v_title>vn_full>s_title>to_string|f:to_series>fc_rm>pn_rm>vn_rm>s_title>text>filesafe_underscore`: It is the equivalent of the default rule but without using the legacy rules. The `n:` rule is missing so it is taken to be the default `n:` rule (ie `_t>str_filesafe`; see above).
- `fc_full>p_title`: This doesn't have the `tnf` prefixes. In this case, it assumed to be a `t:` prefix (the other ones being the default).
- suppress part naming in volumes [Issue 44](https://github.com/gvellut/jncep/issues/44): `n:fc_rm>p_to_volume>pn_rm>v_title>vn_full>s_title>to_string>str_filesafe`. With this the EPUB title will be generated as default, only the file name will be customized. Even if single part : "Demon_Lord_Retry_Volume_9.epub"
- only the Volume is shown and numbered, additionally flags could be set for converting spelled out numbers into decimals and removing underscores + padding [Issue 29](https://github.com/gvellut/jncep/issues/29): `n:fc_rm>p_split_part>v_split_volume>pn_0pad>vn_number>vn_0pad>vn_merge>pn_rm_if_complete>pn_prepend_vn>pn_short>s_title>ss_rm_subtitle>to_string`. Part 2 of Volume 6 Part One of [Rebuild World](https://j-novel.club/series/rebuild-world) will be: "Rebuild World 06.01.02.epub"

## Syntax

### Sections

The 3 sections are separated by a `|` and prefixed with a `t:` (EPUB title), `n:` (file name) or `f:` (folder name). In each section, the rules are separated with `>`. The rules are applied in order.

### Initial value

The title is initialized as :
- Part (`p`) if only one part
- Volume (`v`) + Part numbers (`pn`) if multiple parts in a single volume
- Series (`s`) + Volume numbers (`vn`) + Part numbers (`pn`) if multiple volumes present

Rules should handle the 3 cases. If "By Volume" is always used, only the first 2 cases can be handled.

### Rules

The rules are as follows (TODO document briefly):

- fc_rm
- fc_rm_if_complete
- fc_short
- fc_full
- p_to_volume
- p_to_series
- p_split_part
- p_title
- pn_rm
- pn_rm_if_complete
- pn_prepend_vn_if_multiple
- pn_prepend_vn
- pn_0pad
- pn_short
- pn_full
- v_to_series
- v_split_volume
- v_title
- vn_rm
- vn_rm_if_pn
- vn_number
- vn_merge
- vn_0pad
- vn_short
- vn_full
- to_series
- s_title
- s_slug
- ss_rm_stopwords
- ss_rm_subtitle
- ss_acronym
- ss_first
- ss_max_len
- legacy_t
- legacy_f
- to_string
- str_rm_space
- str_replace_space
- str_filesafe
- _t

The rules apply to the following parts of the title, according to their prefixes:

- `fc`: Final Complete (the indication at the end of the file name)
- `p`: Part. It refers to the part as coming from the J-Novel Club API: Its title includes the series name, the volume number and the part number, always *Part &lt;number&gt*.
- `pn`: Part number
- `v`: Volume. It refers to the volume as coming from the J-Novel Club API: Its title includes the series name and the volume number, possibly in multiple items like *Part 5 Volume 2*.
- `vn`: Volume number
- `s`: Series. It refers to the series as coming from the J-Novel Club API: Its title possibly includes a subtitle (after a `:`).
- `ss`: Series string. It is the series name that was possibly transformed (eg just the slug).
- `str`: To apply at the end to the title to a string with no separate logical parts.
