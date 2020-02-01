# jncep

Simple command-line tool to generate EPUB files for [J-Novel Club](https://j-novel.club/) pre-pub novels

# Install

The tool requires Python 3.6+.

To install, launch :

```console
pip install jncep
```

# Usage

The `jncep` tool must be launched on the command-line. It has 3 commands:

- `epub`: To simply generate an EPUB file
- `track`: To tell the tool that a series is of interest 
- `update`: To generate EPUB files for newly updated series of interest

## epub

The `epub` command is used for simple EPUB generation.

### Help

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

The following command will create a single EPUB file of part 1 of Volume 1 of the 'Tearmoon Empire' novel in the current directory:

```console
jncep epub --email "user@example.com" --password "foo%bar666!" https://j-novel.club/c/tearmoon-empire-volume-1-part-1
```

Account credentials must be passed, as well as a URL link to a part or volume or series on the J-Novel Club website. Whatever the URL links to is downloaded (single part or whole volume or whole series).

The tool will then communicate with the J-Novel Club API using the specified account and download the necessary parts (texts and images), as well as a book cover.

Optionnally, the JNCEP_EMAIL and JNCEP_PASSWORD env vars can be set instead of passing the --email and --password arguments when launching the tool.

#### Range of parts

The following command will create a single EPUB file with Parts 5 to 10 of Volume 1 of the 'Tearmoon Empire' novel (as long as the pre-pubs have not expired) in the current directory:

```console
jncep epub --email "user@example.com" --password "foo%bar666!" --parts 1.5:1.10 https://j-novel.club/c/tearmoon-empire-volume-1-part-1
```

Compared to the previous example, a range of parts / volumes has been specified, in which case the URL is simply used to indicate the series (even if it links to a part or volume).

The specified range is in the shape of `<volume>[.part]:<volume>[.part]`. The specific part numbers are optional and are relative to the volume. If the part number is not specified, it is equivalent to `<volume>.1` if on the left and, if on the right, until the last part of the volume.

Any of the 2 sides of the `:` range separator is optional, like `<volume>[.part]:`, which means 'every part starting with the specified part until the last in the series', or even `:`, which means 'every part in the series'. 

If the flag `--absolute` is passed, the range must of the form `<part>:<part>` where each part number refers to the part number from the beginning of the series i.e. if the first volume series has 11 parts, then `12` is the same as `2.1` without the `--absolute` flag.

## track

This command is used to tell the tool that it should track updates for a series.

TODO

## update

This command is used to generate EPUB files for newly updated series (previously added using the track command).

TODO

# Limitations

This tool only works with J-Novel *novels*, not manga.

# Issues

Report issues at https://github.com/gvellut/jncep/issues

# TODO (maybe)

- self-contained executable for macOS and Windows with PyInstaller
- config file for account
- keep track of past downloads for a series and automatically download new parts
- Async IO