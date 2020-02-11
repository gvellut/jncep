# jncep

Simple command-line tool to generate EPUB files for [J-Novel Club](https://j-novel.club/) pre-pub novels

# Install

The tool requires Python 3.6+.

To install, launch :

```console
pip install jncep
```

The command above will install the `jncep` Python library and its dependencies. The library includes a command-line script, also named `jncep`, whose functionality is described below.

# Limitations

This tool only works with J-Novel __novels__, not manga.

# Usage

The `jncep` tool must be launched on the command-line. It has 3 commands:

- `epub`: To simply generate an EPUB file
- `track`: To tell the tool that a series is of interest
- `update`: To generate EPUB files for newly updated series of interest

## epub

The `epub` command is used for simple EPUB generation, based on a URL link to a part or volume or series on the J-Novel Club website.

### Options

To get some help about the arguments to the `epub` command, just launch with the --help option:

```console
~$ jncep epub --help
Usage: jncep epub [OPTIONS] JNOVEL_CLUB_URL

  Generate EPUB files for J-Novel Club pre-pub novels

Options:
  -l, --email TEXT        Login email for J-Novel Club account  [required]
  -p, --password TEXT     Login password for J-Novel Club account  [required]
  -o, --output DIRECTORY  Existing folder to write the output [default: The
                          current directory]
  -s, --parts TEXT        Specification of a range of parts to download in the
                          form of <vol>[.part]:<vol>[.part] [default: All the
                          content linked by the JNOVEL_CLUB_URL argument,
                          either a single part, a whole volume or the whole
                          series]
  -a, --absolute          Flag to indicate that the --parts option specifies
                          part numbers globally, instead of relative to a
                          volume i.e. <part>:<part>
  -v, --byvolume          Flag to indicate that the parts of different volumes
                          shoud be output in separate EPUBs
  -i, --images            Flag to indicate that the images of the novel should
                          be extracted into the output folder
  --help                  Show this message and exit.
```

### Examples

#### Basic usage

The following command will create a single EPUB file of part 1 of Volume 1 of the 'Tearmoon Empire' novel in the specified `.../jncbooks` directory:

```console
jncep epub --email user@example.com --password "foo%bar666!" -o /Users/guilhem/Documents/jncbooks https://j-novel.club/c/tearmoon-empire-volume-1-part-1
```

Account credentials must be passed, as well as a URL link to a part or volume or series on the J-Novel Club website. Whatever the URL links to is downloaded (single part or whole volume or whole series).

The tool will then communicate with the J-Novel Club API using the specified account and download the necessary parts (texts and images), as well as a book cover. The EPUB file will be created inside the specified (optional) output directory, `/Users/guilhem/Documents/jncbooks`, which must exist (not created by the tool). If the output option is not present, the EPUB is output in the current directory.

Optionnally, the JNCEP_EMAIL and JNCEP_PASSWORD env vars can be set instead of passing the --email and --password arguments when launching the tool.

#### Range of parts

The following command will create a single EPUB file with Parts 5 to 10 of Volume 1 of the 'Tearmoon Empire' novel (as long as the pre-pubs have not expired) in the current directory:

```console
jncep epub --email user@example.com --password "foo%bar666!" --parts 1.5:1.10 https://j-novel.club/c/tearmoon-empire-volume-1-part-1
```

Compared to the previous example, a range of parts / volumes has been specified, in which case the URL is simply used to indicate the series (even if it is a link to just a part or volume of a series).

The specified range is in the shape of `<volume>[.part]:<volume>[.part]`. The specific part numbers are optional and are relative to the volume. If the part number is not specified, it is equivalent to `<volume>.1` if on the left and, if on the right, until the last part of the volume.

Any of the 2 sides of the `:` range separator is optional, like `<volume>[.part]:`, which means 'every part starting with the specified part until the last in the series', or even `:`, which means 'every part in the series'. 

If the flag `--absolute` is passed, the range must be of the form `<part>:<part>` where each part number refers to the part number from the beginning of the series i.e. if the first volume in the series has 11 parts, then `12` is the same as `2.1` without the `--absolute` flag.

### Font

The tool copies into the EPUB the text obtained from J-Novel Club as is, simply adding a bit of styling. Depending on the font used by the ePub reader, some characters may not display. I have noticed it in a series where the string used as the scene separator is [♱](https://emojipedia.org/emoji/%E2%99%B1/) (East Syriac Cross): My Kobo eBook reader would not show it with any of the fonts present on the device. Using [Crimson Text](https://www.typewolf.com/site-of-the-day/fonts/crimson-text), the font used by J-Novel Club for its web reader, gave the same result. It turns out it was only rendered in the web reader by a fallback font, which on my Mac is Menlo (a monospace font by Apple). A next version of the tool will try to provide a solution for this (without having to copy fonts to the eBook reader or embed fonts in the EPUB).

## track

This command is used to tell the tool that it should track updates for a series. A flag `--rm` can be used to untrack a series. In both cases, a URL link to a part or volume or series on the J-Novel Club website must be passed and is used to specify the series.

### Tracking configuration

The tracking is performed by updating the local config file `<home>/.jncep/tracked.json` (where `<home>` is either `/Users/<user>` on macOS, `C:\Users\<user>` on Windows or `/home/<user>` on Linux). That file will be created by the tool if it doesn't exist.

The `tracked.json` file can be updated manually with a text editor if needed. It is a JSON dictionary with keys the canonical URLs of the series and values another dictionary with keys "name" and "part". The value for "part" is a string in relative format ("<volume>.<part>").

### Options

To get some help about the arguments to the `track` command, just launch with the --help option:

```console
~$ jncep track --help
Usage: jncep track [OPTIONS] (JNOVEL_CLUB_URL?)

  Track updates to a series

Options:
  -l, --email TEXT     Login email for J-Novel Club account  [required]
  -p, --password TEXT  Login password for J-Novel Club account  [required]
  --rm                 Flag to indicate that the series identified by the
                       JNOVEL_CLUB_URL argument should be untracked
  --help               Show this message and exit.
```

### Examples

#### Tracking

The following command will set up tracking for the "Tearmoon Empire" series:

```console
jncep track --email user@example.com --password "foo%bar666!" https://j-novel.club/c/tearmoon-empire-volume-1-part-1
```

Currently the last part is Volume 1 Part 14, so an entry "tearmoon-empire" with volume 14 will be added to the `tracked.json` file.

#### Untracking

The following command will disable tracking for the "Tearmoon Empire" series, using the `--rm` flag:

```console
jncep track --email user@example.com --password "foo%bar666!" --rm https://j-novel.club/c/tearmoon-empire-volume-1-part-14
```

Note that the URL is different from the first example: It doesn't matter since it resolves to the same series.

#### List tracked series

Without any argument the command will list the tracked series:

```console
jncep track --email user@example.com --password "foo%bar666!"
```

This will display something like:

```console
2 series are tracked:
'Kobold King' (https://j-novel.club/s/kobold-king): 2.2
'The Tales of Marielle Clarac' (https://j-novel.club/s/the-tales-of-marielle-clarac): 1.4
```

## update

This command is used to generate EPUB files for newly updated series that were previously added using the `track` command. Optionally, a URL link to a part or volume or series on the J-Novel Club website can be passed, in order to only update that series.

### Options

To get some help about the arguments to the `update` command, just launch with the --help option:

```console
~$ jncep update --help
Usage: jncep update [OPTIONS] (JNOVEL_CLUB_URL?)

  Generate EPUB files for new parts of all tracked series (or specific
  series if a URL argument is passed)

Options:
  -l, --email TEXT        Login email for J-Novel Club account  [required]
  -p, --password TEXT     Login password for J-Novel Club account  [required]
  -o, --output DIRECTORY  Existing folder to write the output [default: The
                          current directory]
  -v, --byvolume          Flag to indicate that the parts of different volumes
                          shoud be output in separate EPUBs
  -i, --images            Flag to indicate that the images of the novel should
                          be extracted into the output folder
  --help                  Show this message and exit.
```

Most of the arguments to the `epub` command are also found here.

### Example

The following command will update all the series:

```console
jncep update --email user@example.com --password "foo%bar666!"
```

Depending on which series were configured, something like the following should be displayed on the last line:

```console
2 series sucessfully updated!
```

Or if no tracked series has seen any updates:

```console
All series are already up to date!
```

### Automation

The `update` command can be called in the background from launchd (on macOS) or a scheduled task (on Windows) or cron (on Linux) in order to regularly download new content if available and create EPUBs (for example, once a day). 

There is no notification built in the `jncep update` command but the text output can be combined with other tools to make something suitable. For example, on __macOS__:

```console
jncep update --email user@example.com --password "foo%bar666!" | tail -n 1 | sed -En '/^[[:digit:]]+ series/p' | (grep -q ^ && osascript -e 'display notification "New J-Novel Club EPUBs available!" with title "JNCEP" sound name "Glass"')
```

If there are updates, the last line output by `jncep update` is something like `2 series sucessfully updated!`, in which case some AppleScript sends a notification message with a sound. It pops up and is kept in the macOS Notification Center.

# Issues

Report issues at https://github.com/gvellut/jncep/issues

# TODO (maybe)

- self-contained executable for macOS and Windows with PyInstaller
- config file for account
- async IO for faster downloads
- solution for rare characters used as scene separator