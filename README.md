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

`jncep` is completely unaffiliated with J-Novel Club (it simply uses their API) so, if you have an issue with the tool, it would be unrealistic to expect support from them (but an issue may be filed on the [bug tracker](https://github.com/gvellut/jncep/issues) of this project on Github).

# Usage

The `jncep` tool must be launched on the command-line. It has 3 commands:

- `epub`: To simply generate an EPUB file
- `track`: To tell the tool that a series is of interest
- `update`: To generate EPUB files for newly updated series of interest

## J-Novel Club account credentials

All the commands need some user credentials (email and password) in order to communicate with the J-Novel Club API. They are the same values as the ones used to log in to the J-Novel Club website with a browser (unless _Sign in with Google_ or _Sign in with Facebook_ is used: In that case, see the section just below).

Those credentials can be passed directly on the command line using the `--email` and `--password` arguments to the __command__ (or subcommand for `track`), not the `jncep` tool directly. For example, using the `epub` command:

```console
jncep epub --email user@example.com --password "foo%bar666!" https://j-novel.club/series/tearmoon-empire
```

Optionally, the __JNCEP_EMAIL__ and __JNCEP_PASSWORD__ env vars can be set instead of passing the `--email` and `--password` arguments when launching the commands. For example, if they are set in the .bashrc in the following way:

```console
export JNCEP_EMAIL=user@example.com
export JNCEP_PASSWORD="foo%bar666!"
```

Then, the same command as above can be simply launched as follows:

```console
jncep epub https://j-novel.club/series/tearmoon-empire
```

In order to make them more readable, all the examples in the rest of this documentation will assume that the env vars are set.

### Credentials when signing in at J-Novel Club with Google or Facebook

It is not possible to directly use Google credentials (if _Sign in with Google_ is used on the J-Novel Club website) or Facebook credentials (with _Sign in with Facebook_). Instead, a password specific to J-Novel Club must first be created: It is the same process as the one needed to be performed in order to log in to the official J-Novel Club mobile app, in case Google or Facebook was originally used to sign up.

Here is what needs to be done:
- Log in to the J-Novel Club website with Facebook or Google
- Go to the __Account__ page from the link at the top.
- Click on the __Password__ section on the left hand side.
- Set a password on that screen.

Then the login email of the Facebook or Google account, together with that new password, can be used as credentials for the `jncep` tool.

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
  -v, --byvolume          Flag to indicate that the parts of different volumes
                          shoud be output in separate EPUBs
  -i, --images            Flag to indicate that the images of the novel should
                          be extracted into the output folder
  -c, --content           Flag to indicate that the raw content of the parts
                          should be extracted into the output folder
  -n, --no-replace        Flag to indicate that some unicode characters
                          unlikely to be in an EPUB reader font should NOT be
                          replaced and instead kept as is
  -t, --css FILE          Path to custom CSS file for the EPUBs [default: The
                          CSS provided by JNCEP]
  --help                  Show this message and exit.
```

### Examples

#### Basic usage

The following command will create a single EPUB file of part 1 of Volume 1 of the 'Tearmoon Empire' novel in the specified `.../jncbooks` directory:

```console
jncep epub -o /Users/guilhem/Documents/jncbooks https://j-novel.club/read/tearmoon-empire-volume-1-part-1
```

Account credentials must be passed (in this case, by using the env vars, as explained above), as well as a URL link to a part or volume or series on the J-Novel Club website. Whatever the URL links to is downloaded (single part or whole volume or whole series).

The tool will then communicate with the J-Novel Club API using the specified credentials and download the necessary parts (texts and images), as well as a book cover. The EPUB file will be created inside the specified (optional) output directory, `/Users/guilhem/Documents/jncbooks`, which must exist (not created by the tool).

If the `--output` or `-o` switch is not present, the EPUB is output in the current directory. The `JNCEP_OUTPUT` env var can also be used instead of the switch to indicate a download directory.

#### Range of parts

The following command will create a single EPUB file with Parts 5 to 10 of Volume 1 of the 'Tearmoon Empire' novel (as long as the pre-pubs have not expired) in the current directory:

```console
jncep epub --parts 1.5:1.10 https://j-novel.club/read/tearmoon-empire-volume-1-part-1
```

Compared to the previous example, a range of parts / volumes has been specified, in which case the URL is simply used to indicate the series (even if it is a link to just a part or volume of a series).

The specified range is in the shape of `<volume>[.<part>]:<volume>[.<part>]` where `<volume>` and `<part>` are numbers (e.g. `1.5:3`). The specific part numbers are optional (as indicated by `[` and `]`, which should not be present in the actual argument value) and are relative to the volume. If the part number is not specified, it is equivalent to `<volume>.1` if on the left and, if on the right, until the last part of the volume. Both sides of the range are inclusive.

Any of the 2 sides of the `:` range separator is optional, like `<volume>[.<part>]:`, which means 'every part starting with the specified part until the last in the series', or even `:`, which means 'every part in the series'.

Moreover, the `:` itself is also optional: It is possible to specify just `<volume>[.<part>]`, in which case it is not interpreted as a range. If only the volume is specified (e.g. `2`), then all the parts of the volume will be downloaded and if there is also a part (e.g. `2.1`), only that part will be downloaded.

Here are examples of valid values for the argument:
- `1.5:2.8` => Part 5 of volume 1 to part 8 of volume 2
- `1:2.8` => Part 1 of volume 1 to part 8 of volume 2
- `1:3` => Part 1 of volume 1 to the last part of volume 3
- `2.7:` => Part 7 of volume 2 until the last part in the series 
- `:3.5` => From the first part in the series until part 5 of volume 3
- `:` => The whole series
- `2` => All the parts of volume 2

### Rare Unicode characters

Originally, the tool copied into the EPUB the text obtained from J-Novel Club as is, simply adding a bit of styling through an external CSS. Depending on the font used by the ePub reader, some rare Unicode characters did not display. I noticed it in a series where the string used as the scene separator is [♱](https://emojipedia.org/emoji/%E2%99%B1/) (East Syriac Cross): My Kobo eBook reader would not show it with any of the fonts present on the device. Using [Crimson Text](https://www.typewolf.com/site-of-the-day/fonts/crimson-text), the font used by J-Novel Club for its web reader, gave the same result. It turns out it was only rendered in the web reader by a fallback font, which on my Mac is Menlo (a monospace font by Apple). This issue also happened with the Calibre EPUB reader. However, the iBooks reader app on macOS displayed the character.

To solve this issue (without having to mess with fonts), by default, this specific character is now replaced with "\*\*". This behaviour can be overridden with the `-n` switch. Both the characters to replace and the replacement string are hardcoded. If another character is unable to display properly, [an issue can be filed](https://github.com/gvellut/jncep/issues) and it will be processed by the tool in a later version.

### CSS

The default CSS used by the tool and embedded in the generated EPUB files can be found [in the repository](https://raw.githubusercontent.com/gvellut/jncep/master/jncep/res/style.css). It is possible to download it and customize it. Then you can tell the `epub` command to use your own version by passing the `-t/--css` option with the path to your custom CSS as value.

### Environment variables

Just like the login and password, other options that are shared between the `epub` and `update` subcommands can be set using an environment variable. These are:
- JNCEP_EMAIL
- JNCEP_PASSWORD
- JNCEP_OUTPUT
- JNCEP_CSS
- JNCEP_BYVOLUME
- JNCEP_IMAGES
- JNCEP_CONTENT
- JNCEP_NOREPLACE

The environment variables which set flags (JNCEP_BYVOLUME and below in the list above) should have a value like `1`.

## track

This command is used to manage series to track. It has 4 subcommands:
- `add`: Add a new series for tracking. After a series has been added, it can be updated using the `update` command.
- `rm`: Remove a series from tracking
- `list`: List tracked serie
- `sync`:  Update the list of series to track based on series followed on the J-Novel Club website (or the opposite using the `--reverse` flag)

In the cases of `add` and `rm`, a URL link to a part or volume or series on the J-Novel Club website must be passed and is used to specify the series. Credentials are also needed for them (but not for `list`, which doesn't communicate with the J-Novel Club API).

### Tracking configuration

The tracking is performed by updating the local config file `<home>/.jncep/tracked.json` (where `<home>` is either `/Users/<user>` on macOS, `C:\Users\<user>` on Windows or `/home/<user>` on Linux). That file will be created by the tool if it doesn't exist.

The `tracked.json` file can be updated manually with a text editor if needed. It is a JSON dictionary with keys the canonical URLs of the series and values another dictionary with keys "name", "part" and "part_date". The value for "part_date" is the launch date for the last downloaded part and is used for the `update` command to find out if new parts have been released. The value for "part" is a string in relative format (`<volume>.<part>`) that corresponds to the last downloaded part: It is only used in the `track list` subcommand.

### Options

To get some help about the arguments to the `track` command, just launch with the `--help` option:

```console
~$ jncep track --help
Usage: jncep track [OPTIONS] COMMAND [ARGS]...

  Track updates to a series

Options:
  --help  Show this message and exit.

Commands:
  add   Add a new series for tracking
  list  List tracked series
  rm    Remove a series from tracking
  sync  Sync list of series to track based on series followed on J-Novel...
```

In turn, the `add`, `rm`, `list` and `sync` subcommands can be called with `--help` to get details about their arguments.

### Examples

#### Tracking

The `add` subcommand sets up tracking for a series by passing a URL to either the series, a volume or a part:

```console
jncep track add https://j-novel.club/series/tearmoon-empire
```

An entry with key "https://j-novel.club/series/tearmoon-empire" will be added to the `tracked.json` file. Note that no Epub is generated by this command: Use the `epub` command to generate a file for the parts released until now.

#### Untracking

The `rm` subcommand disables tracking for a specific series by passing a URL, for example for "Tearmoon Empire" that was added above:

```console
jncep track rm https://j-novel.club/read/tearmoon-empire-volume-1-part-14
```

Note that the URL is different from before: It doesn't matter since it actually resolves to the same series.

It is also possible to pass the index of the series shown using the `list` subcommand (see below):

```console
jncep track rm 5
```

#### List tracked series

The `list` subcommand lists the tracked series:

```console
jncep track list --details
```

This will display something like:

```console
16 series are tracked:
[1] A Late-Start Tamer’s Laid-Back Life https://j-novel.club/series/a-late-start-tamer-s-laid-back-life 2.5 [Nov 04, 2021]
[2] Ascendance of a Bookworm https://j-novel.club/series/ascendance-of-a-bookworm 16.6 [Nov 08, 2021]
...
```

That subcommand doesn't need a login or password (it only reads the local `tracked.json` file).

Withouth the `--details` option, only the index and the series titles are shown.

The index inside the `[..]` can be used in the `rm` subcommnand instead of the URL.

#### Sync

Using the `sync`subcommand, `track` will update the list of series tracked by `jncep` based on series followed on the J-Novel Club website:

```console
jncep track sync
```

The `--reverse` flag can be used for the opposite: The list of series followed on the J-Novel Club website will be updated to add series that are tracked locally by the `jncep` tool. This can be useful since the Follow functionality of the website has been added just recently and the calendar of the website can be filtered with just the followed series.

By default, the `sync` subcommand doesn't do any deletion, it just adds missing entries. To make the list of tracked series and followed series identical, the `--delete` flag can be passed.

## update

This command is used to generate EPUB files for newly updated series that were previously added using the `track` command. Optionally, a URL link to a part or volume or series on the J-Novel Club website can be passed, in order to only update that series.

This command uses the launch date of the parts to find out if the series has been updated.

### Options

To get some help about the arguments to the `update` command, just launch with the `--help` option:

```console
~$ jncep update --help
Usage: jncep update [OPTIONS] (JNOVEL_CLUB_URL?)

  Generate EPUB files for new parts of all tracked series (or specific series
  if a URL argument is passed)

Options:
  -l, --email TEXT        Login email for J-Novel Club account  [required]
  -p, --password TEXT     Login password for J-Novel Club account  [required]
  -o, --output DIRECTORY  Existing folder to write the output [default: The
                          current directory]
  -v, --byvolume          Flag to indicate that the parts of different volumes
                          shoud be output in separate EPUBs
  -i, --images            Flag to indicate that the images of the novel should
                          be extracted into the output folder
  -c, --content           Flag to indicate that the raw content of the parts
                          should be extracted into the output folder
  -n, --no-replace        Flag to indicate that some unicode characters
                          unlikely to be in an EPUB reader font should NOT be
                          replaced and instead kept as is
  -t, --css FILE          Path to custom CSS file for the EPUBs [default: The
                          CSS provided by JNCEP]
  -s, --sync              Flag to sync tracked series based on series followed
                          on J-Novel Club and update the new ones from the
                          beginning of the series
  -w, --whole             Flag to indicate whether the whole volume should be
                          regenerated when a new part is detected during the
                          update
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

#### Sync

The `--sync` flag can be passed (together with the other options), in which case the list of tracked series is first updated based on the list of followed series on the J-Novel Club website (equivalent of `jncep track sync`), then, only for the newly added series, an EPUB is created with the parts from the beginning.

It can be useful for when a new series starts publishing: It can be set as Followed on the website then this `jncep update --sync` command can be launched to subscribe to the series and get all the newly released parts in one go, and without having to copy/paste a URL.

### Automation

The `update` command can be called in the background from launchd (on macOS) or a scheduled task (on Windows) or cron (on Linux) in order to regularly download new content if available and create EPUBs (for example, once a day). 

There is no notification built in the `jncep update` command but the text output can be combined with other tools to make something suitable. If there are updates, the `jncep update` command outputs something like `2 series sucessfully updated!`, which can be processed by another tool do create a notification.

# Issues

Report issues at https://github.com/gvellut/jncep/issues

# TODO (maybe)

- self-contained executable for macOS and Windows with PyInstaller
- config file for account
