# jncep

Simple command-line tool to generate EPUB files for [J-Novel Club](https://j-novel.club/) pre-pub novels

# Install

The tool requires Python 3.6+.

To install, launch :

```console
pip install jncep
```

The command above will install the `jncep` Python library and its dependencies. The library includes a command-line script, also named `jncep`, whose functionality is described below.

# Limitations & disclaimer

This tool only works with J-Novel Club __novels__, not manga.

`jncep` is completely unaffiliated with J-Novel Club (it just uses their API) so do not expect support from them (but you may file an issue on the [bug tracker](https://github.com/gvellut/jncep/issues) of this project on Github).

# Usage

The `jncep` tool must be launched on the command-line. It has 3 commands:

- `epub`: To simply generate an EPUB file
- `track`: To tell the tool that a series is of interest
- `update`: To generate EPUB files for newly updated series of interest

## J-Novel Club account credentials

All the commands need some user credentials (email and password) in order to communicate with the J-Novel Club API. They are the same values as the ones used to log in to the J-Novel Club website with a browser (unless you used _Sign in with Google_ or _Sign in with Facebook_: In that case, see the section below).

Those credentials can be passed directly on the command line using the `--email` and `--password` arguments to the __command__ (or subcommand for `track`), not the `jncep` tool directly. For example, using the `epub` command:

```console
jncep epub --email user@example.com --password "foo%bar666!" https://j-novel.club/c/tearmoon-empire-volume-1-part-1
```

Optionally, the JNCEP_EMAIL and JNCEP_PASSWORD env vars can be set instead of passing the `--email` and `--password` arguments when launching the commands. For example, if they are set in the .bashrc in the following way:

```console
export JNCEP_EMAIL=user@example.com
export JNCEP_PASSWORD="foo%bar666!"
```

Then, the same command as above can be simply launched as follows:

```console
jncep epub https://j-novel.club/c/tearmoon-empire-volume-1-part-1
```

In order to make them more readable, all the examples in the rest of this documentation will assume that the env vars are set.

### Credentials if you signed up at J-Novel Club with Google or Facebook

It is not possible to directly use the Google credentials (if _Sign in with Google_ is used on the J-Novel Club website) or Facebook credentials (with _Sign in with Facebook_). Instead, it is the same process as the one you need to perform in order to log in to the official J-Novel Club mobile app, in case you originally signed up with Google or Facebook:
- Log in to the J-Novel Club website with Facebook or Google
- Go to the __Account__ page from the link at the top.
- Click on the __Password__ section on the left hand side.
- You can set a password there.

Then you can use the login email of your Facebook or Google account, together with that new password, as credentials for the `jncep` tool.

## epub

The `epub` command is used for simple EPUB generation, based on a URL link to a part or volume or series on the J-Novel Club website.

### Options

To get some help about the arguments to the `epub` command, just launch with the `--help` option:

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
  -n, --no-replace        Flag to indicate that some unicode characters
                          unlikely to be in an EPUB reader font should NOT be
                          replaced and instead kept as is
  --help                  Show this message and exit.
```

### Examples

#### Basic usage

The following command will create a single EPUB file of part 1 of Volume 1 of the 'Tearmoon Empire' novel in the specified `.../jncbooks` directory:

```console
jncep epub -o /Users/guilhem/Documents/jncbooks https://j-novel.club/c/tearmoon-empire-volume-1-part-1
```

Account credentials must be passed (in this case, by using the env vars, as explained above), as well as a URL link to a part or volume or series on the J-Novel Club website. Whatever the URL links to is downloaded (single part or whole volume or whole series).

The tool will then communicate with the J-Novel Club API using the specified credentials and download the necessary parts (texts and images), as well as a book cover. The EPUB file will be created inside the specified (optional) output directory, `/Users/guilhem/Documents/jncbooks`, which must exist (not created by the tool).

If the `--output` or `-o` switch is not present, the EPUB is output in the current directory. The `JNCEP_OUTPUT` env var can also be used instead of the switch to indicate a download directory.

#### Range of parts

The following command will create a single EPUB file with Parts 5 to 10 of Volume 1 of the 'Tearmoon Empire' novel (as long as the pre-pubs have not expired) in the current directory:

```console
jncep epub --parts 1.5:1.10 https://j-novel.club/c/tearmoon-empire-volume-1-part-1
```

Compared to the previous example, a range of parts / volumes has been specified, in which case the URL is simply used to indicate the series (even if it is a link to just a part or volume of a series).

The specified range is in the shape of `<volume>[.<part>]:<volume>[.<part>]` where `<volume>` and `<part>` are numbers (e.g. `1.5:3`). The specific part numbers are optional (as indicated by `[` and `]`, which should not be present in the actual argument value) and are relative to the volume. If the part number is not specified, it is equivalent to `<volume>.1` if on the left and, if on the right, until the last part of the volume. Both sides of the range are inclusive.

Any of the 2 sides of the `:` range separator is optional, like `<volume>[.<part>]:`, which means 'every part starting with the specified part until the last in the series', or even `:`, which means 'every part in the series'.

If the flag `--absolute` is passed, the range must be of the form `<part>:<part>` where each part number refers to the part number from the beginning of the series i.e. if the first volume in the series has 11 parts, then `12` is the same as `2.1` without the `--absolute` flag.

Moreover, the `:` itself is also optional: It is possible to specify just `<volume>[.<part>]` (or `<part>` with the `--absolute` flag), in which case it is not interpreted as a range. If only the volume is specified (e.g. `2`), then all the parts of the volume will be downloaded and if there is also a part (e.g. `2.1`), only that part will be downloaded.

Here are examples of valid values for the argument:
- `1.5:2.8` => Part 5 of volume 1 to part 8 of volume 2
- `1:2.8` => Part 1 of volume 1 to part 8 of volume 2
- `1:3` => If not absolute, part 1 of volume 1 to the last part of volume 3; If absolute, parts 1 to 3 (from the beginning of the series) 
- `2.7:` => Part 7 of volume 2 until the last part in the series 
- `:3.5` => From the first part in the series until part 5 of volume 3
- `:` => The whole series
- `2` => If not absolute, all the parts of volume 2; If absolute, part 2 (from the beginning of the series) 

### Rare Unicode characters

Originally, the tool copied into the EPUB the text obtained from J-Novel Club as is, simply adding a bit of styling through an external CSS. Depending on the font used by the ePub reader, some rare Unicode characters did not display. I noticed it in a series where the string used as the scene separator is [♱](https://emojipedia.org/emoji/%E2%99%B1/) (East Syriac Cross): My Kobo eBook reader would not show it with any of the fonts present on the device. Using [Crimson Text](https://www.typewolf.com/site-of-the-day/fonts/crimson-text), the font used by J-Novel Club for its web reader, gave the same result. It turns out it was only rendered in the web reader by a fallback font, which on my Mac is Menlo (a monospace font by Apple). This issue also happened with the Calibre EPUB reader. However, the iBooks reader app on macOS displayed the character.

To solve this issue (without having to mess with fonts), by default, this specific character is now replaced with "\*\*". This behaviour can be overridden with the `-n` switch. Both the characters to replace and the replacement string are hardcoded. If another character is unable to display properly, [an issue can be filed](https://github.com/gvellut/jncep/issues) and it will be processed by the tool in a later version.

## track

This command is used to maange series to track. It has 3 subcommands:
- `add`: Add a new series for tracking. After a series has been added, it can be updated using the `update` command.
- `rm`: Remove a series from tracking
- `list`: List tracked serie

In the cases of `add` and `rm`, a URL link to a part or volume or series on the J-Novel Club website must be passed and is used to specify the series. Credentials are also needed (but not for `list` though, which doesnt^communicate with th J-Novel Club API).

### Tracking configuration

The tracking is performed by updating the local config file `<home>/.jncep/tracked.json` (where `<home>` is either `/Users/<user>` on macOS, `C:\Users\<user>` on Windows or `/home/<user>` on Linux). That file will be created by the tool if it doesn't exist.

The `tracked.json` file can be updated manually with a text editor if needed. It is a JSON dictionary with keys the canonical URLs of the series and values another dictionary with keys "name" and "part". The value for "part" is a string in relative format (`<volume>.<part>`).

### Options

To get some help about the arguments to the `track` command, just launch with the `--help` option:

```console
~$ jncep track --help
Usage: jncep.py track [OPTIONS] COMMAND [ARGS]...

  Track updates to a series

Options:
  --help  Show this message and exit.

Commands:
  add   Add a new series for tracking
  list  List tracked series
  rm    Remove a series from tracking
```

In turn, the `add`, `rm` and `list` commands can be called with `--help`.

### Examples

#### Tracking

The following command will set up tracking for the "Tearmoon Empire" series, using the `add` subcommand:

```console
jncep track add https://j-novel.club/c/tearmoon-empire-volume-1-part-1
```

Currently the last part is Volume 1 Part 14, so an entry "tearmoon-empire" with part `1.14` will be added to the `tracked.json` file (note: If the series has been updated since writing this, it will be a different part number).

#### Untracking

The following command will disable tracking for the "Tearmoon Empire" series, using the `rm` subcommand:

```console
jncep track rm https://j-novel.club/c/tearmoon-empire-volume-1-part-14
```

Note that the URL is different from the first example: It doesn't matter since it resolves to the same series.

#### List tracked series

Using the `list`subcommand, `track` will list the tracked series:

```console
jncep track list
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

To get some help about the arguments to the `update` command, just launch with the `--help` option:

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
  -n, --no-replace        Flag to indicate that some unicode characters
                          unlikely to be in an EPUB reader font should NOT be
                          replaced and instead kept as is
  --help                  Show this message and exit.
```

Most of the arguments to the `epub` command are also found here.

### Example

The following command will update all the series:

```console
jncep update
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
jncep update | tail -n 1 | sed -En '/^[[:digit:]]+ series/p' | (grep -q ^ && osascript -e 'display notification "New J-Novel Club EPUBs available!" with title "JNCEP" sound name "Glass"')
```

If there are updates, the last line output by `jncep update` is something like `2 series sucessfully updated!`, in which case some AppleScript sends a notification message with a sound. It pops up and is kept in the macOS Notification Center.

# Issues

Report issues at https://github.com/gvellut/jncep/issues

# TODO (maybe)

- self-contained executable for macOS and Windows with PyInstaller
- config file for account
- async IO for faster downloads
- replace prints with logging