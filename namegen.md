# namegen

This functionality allows the renaming of output EPUB file names, as well as the EPUB title (since it appears in the EPUB reader interface) and folder name.
A list of rules (to choose from a predefined list) are applied to transform the titles.

It is not very well documented or tested so if you need something and you don't see how to do it, you can open an issue and I will try to help (or tell you it is not possible...)
The version inside the master Github repo is missing some support for JNC Nina (will be added before release).

## Note about JNC Nina

Some functionalities (parsing and title generation) are not yet implemented outside English (ie for the main J-Novel Club website) so it is recommended not to use this functionnality with JNC Nina (or not use the rules that have issues with multilingual support).

Full support will be added for the next version.

## Samples

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
- `p`: Part. It refers to the part as coming from the J-Novel Club API: Its title includes the series name, the volume number and the part number, always *Part <number>*.
- `pn`: Part number
- `v`: Volume. It refers to the volume as coming from the J-Novel Club API: Its title includes the series name and the volume number, possibly in multiple items like *Part 5 Volume 2*.
- `vn`: Volume number
- `s`: Series. It refers to the series as coming from the J-Novel Club API: Its title possibly includes a subtitle (after a `:`).
- `ss`: Series string. It is the series name that was possibly transformed (eg just the slug).
- `str`: To apply at the end to the title to a string with no separate logical parts.
