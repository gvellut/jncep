# jncep

Simple tool to generate EPUB files for [J-Novel Club](https://j-novel.club/) pre-pub novels

# Install

The tool is compatible with Python 3.6+.

To install, launch :

```console
pip install jncep
```

# Usage

The `jncep` tool must be launched on the command-line.

### Example

The following command will create a single EPUB file with Parts 5 to 10 of Volume 1 of the 'Tearmoon Empire' novel (as long as the pre-pubs have not expired):

```console
jncep --email "user@example.com" --password "foo%bar666!" --parts 1.5:1.10 https://j-novel.club/c/tearmoon-empire-volume-1-part-1
```

Account credentials must be passed, as well as a URL link to a part or volume or series on the J-Novel Club website. Optionnally, a range of parts / volumes can be specified, in which case the URL simply indicates the series (even if it links to a part or volume). If no range is specified, whatever the URL links to is downloaded (single part or whole volume or whole series). 

The tool will then communicate with the J-Novel Club API using the permissions of the specified account and download the requested texts and images.

Optionnally, the JNCEP_EMAIL and JNCEP_PASSWORD env vars can be set instead of passing the --email and --password arguments when launching the tool.

### Help

To get some help about the arguments, just launch with the --help option:

```console
~$ jncep --help
Usage: jncep.py [OPTIONS] JNOVEL_CLUB_URL

  Generate EPUB files for the J-Novel Club pre-pubs

Options:
  -l, --email TEXT     Login email for J-Novel Club account  [required]
  -p, --password TEXT  Login password for J-Novel Club account  [required]
  -o, --output PATH    Output EPUB file or folder (must exist)
  -s, --parts TEXT     Specification of a range of parts to download in the
                       shape of <vol>[.part]:<vol>[.part]
  -a, --absolute       Indicates that the --parts option specifies part
                       numbers globally, instead of relative to a volume i.e.
                       <part>:<part>
  --help               Show this message and exit.
```

### Limitations

This tool only works with the J-Novel novels, not manga.

# Issues

Report issues at https://github.com/gvellut/jncep/issues

# TODO (maybe)

- split EPUBs by volume
- self-contained executable for macOS and Windows with PyInstaller
- config file for account
- keep track of past downloads for a series and automatically download new parts