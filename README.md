# jncep

Command-line tool to generate EPUB files for [J-Novel Club](https://j-novel.club/) pre-pub novels

# Install

The tool requires Python 3.6+.

To install, launch :

```console
pip install jncep
```

The command above will install the `jncep` Python library and its dependencies. The library includes a command-line script, also named `jncep`, whose functionality is described below.

# Limitations & disclaimer

This tool only works with J-Novel Club __novels__, not manga.

`jncep` is completely unaffiliated with J-Novel Club (it simply uses their API).

# Issues

Report issues at https://github.com/gvellut/jncep/issues

# Usage

The `jncep` tool must be launched on the command-line. It has 4 commands:

- [`epub`](#epub): To simply generate an EPUB file
- [`track`](#track): To tell the tool that a series is of interest
- [`update`](#update): To generate EPUB files for newly updated series of interest
- [`config`](#config): To manage an optional configuration file

## J-Novel Club account credentials

All the commands need some user credentials (email and password) in order to communicate with the J-Novel Club API. They are the same values as the ones used to log in to the J-Novel Club website with a browser (unless _Sign in with Google_ or _Sign in with Facebook_ is used: In that case, see the section just below).

Those credentials can be passed directly on the command line using the `--email` and `--password` arguments to the __command__ (or subcommand for `track`), not the `jncep` tool directly. For example, using the `epub` command:

```console
jncep epub --email user@example.com --password "foo%bar666!" https://j-novel.club/series/tearmoon-empire
```

### Passing the credentials indirectly

It is also possible to pass the credentials indirectly in one of 2 ways:
- configuration file
- environment variables

Then it is possible to omit the `--email` and `--password` options.

In order to make them more readable, all the examples in the rest of this documentation will assume that the credentials have been passed through one of the two methods above.

#### Configuration file

It is possible to set the login and password using the configuration file:

```console
jncep config set EMAIL "user@example.com"
jncep config set PASSWORD "foo%bar666!"
```

Then, the same command as above can be simply launched as follows:

```console
jncep epub https://j-novel.club/series/tearmoon-empire
```

See the [general documentation on managing the configuration](#config).

#### Environment variables

Optionally, the __JNCEP_EMAIL__ and __JNCEP_PASSWORD__ env vars can be set instead of passing the `--email` and `--password` arguments when launching the commands. For example, if they are set in the .bashrc in the following way:

```console
export JNCEP_EMAIL=user@example.com
export JNCEP_PASSWORD="foo%bar666!"
```

Then, the same command as above can be simply launched as follows:

```console
jncep epub https://j-novel.club/series/tearmoon-empire
```

See the [general documentation on environment variables](#environment-variables-1).

### Credentials when signing in at J-Novel Club with Google or Facebook

It is not possible to directly use Google credentials (if _Sign in with Google_ is used on the J-Novel Club website) or Facebook credentials (with _Sign in with Facebook_). Instead, a password specific to J-Novel Club must first be created: It is the same process as the one needed to be performed in order to log in to the official J-Novel Club mobile app, in case Google or Facebook was originally used to sign up.

Here is what needs to be done:
- Log in to the J-Novel Club website with Facebook or Google
- Go to the __Account__ page from the link at the top.
- Click on the __Password__ section on the left hand side.
- Set a password on that screen.

Then the login email of the Facebook or Google account, together with that new password, can be used as credentials for the `jncep` tool, either directly or using one of the indirect methods.

## Debugging mode

A `--debug` (or `-d`) option can be passed to the `jncep` tool, before the specific command. It will print out more information about what is happening, using the standard Python `logging` package.

For example:

```console
jncep --debug update
```

In case of an issue with `jncep`, it is recommended to launch with the `--debug` option and to include the output in the issue report (either inline or as a file attachment, if too long).

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
                          should be output in separate EPUBs
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

The tool will then communicate with the J-Novel Club API using the specified credentials and download the necessary parts (texts and images), as well as a book cover. The EPUB file will be created inside the specified (optional) output directory, `/Users/guilhem/Documents/jncbooks`. The directory will be created if it doesn't exist.

If the `--output` or `-o` switch is not present, the EPUB is output in the current directory. The `JNCEP_OUTPUT` env var can also be used instead of the switch to indicate a download directory.

##### URL

To get the URL to pass as argument, you should first go to the series page on the the J-Novel Club website. Then copy the URL found in the browser URL bar:
- For series: Simply use the URL of the series page on J-Novel Club. It will have a shape like `https://j-novel.club/series/redefining-the-meta-at-vrmmo-academy`.
- For volumes: Click on the volume you are interested in. The URL in the browser will change to something like `https://j-novel.club/series/redefining-the-meta-at-vrmmo-academy#volume-2`.
- For parts: Click on one of the available parts below a specific volume. The web reader will then open and the URL will be something like `https://j-novel.club/read/redefining-the-meta-at-vrmmo-academy-volume-1-part-1`.

It is also possible to pass the index of the series shown using the [`track list`](#list-tracked-series) command:

```console
jncep epub 5
```

It is equivalent to passing the URL of the corresponding series.

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
- `-1` => The last volume
- `-1.3:` => From the third part of the last volume until the last part in the series
- `:` => The whole series
- `2` => All the parts of volume 2

##### A note about volume numbers

The volume number used in the `--parts` option is the one used by J-Novel Club internally, for its website and API. For most series, it is identical to the volume number as written in the volume sections on the series pages of the J-Novel Club website: *Volume 7* means `7` can be passed to the `--parts` option.

However, for some series, the volume numbering scheme is different. For example:
- The volumes of *Ascendance of a Bookworm* are written as *Part x Volume y*. However, internally, J-Novel Club still uses a single number to describe a volume for this series.
- *Min-Maxing My TRPG Build* has *Volume 4 Canto I* and *Volume 4 Canto II*. Internally, J-Novel Club describes the first as volume `4` and the second as volume `5`.
- There are also some series with a side-stories volume that has been inserted in the normal series but which doesn't follow the volume numbering scheme: This volume will shift the internal numbering for the volumes that come after.

In order to get the volume number to use for the `--parts` option for those series, you should go to the series page on J-Nobel Club, then click on the volume you want. Then the URL in the brower will change with `#volume-xx` added at the end. This number `xx` can be used for `jncep`. For example, for *Ascendance of a Bookworm Part 4 Volume 8*, the URL in the browser will change to `https://j-novel.club/series/ascendance-of-a-bookworm#volume-20`. It means you should use `20` as the volume number for the command.

Alternatively, a negative volume counts from the last volume: `-1` is the last volume, `-2` the penultimate, etc ... So it might be easier to use that for series with many volumes and with an internal numbering that doesn't correspond to the external one.

### Rare Unicode characters

Originally, the tool copied into the EPUB the text obtained from J-Novel Club as is. Depending on the font used by the ePub reader, some rare Unicode characters did not display. I noticed it in a series where the string used as the scene separator is [♱](https://emojipedia.org/emoji/%E2%99%B1/) (East Syriac Cross): My Kobo eBook reader would not show it with any of the fonts present on the device. Using [Crimson Text](https://www.typewolf.com/site-of-the-day/fonts/crimson-text), the font used by J-Novel Club for its web reader, gave the same result. It turns out it was only rendered in the web reader by a fallback font, which on my Mac is Menlo (a monospace font by Apple). This issue also happened with the Calibre EPUB reader. However, the iBooks reader app on macOS displayed the character.

To solve this issue (without having to mess with fonts), by default, this specific character is now replaced with "\*\*". This behaviour can be overridden with the `-n` switch. Both the characters to replace and the replacement string are hardcoded. If another character is unable to display properly, [an issue can be filed](https://github.com/gvellut/jncep/issues) and it will be processed by the tool in a later version.

### CSS

The default CSS used by the tool and embedded in the generated EPUB files can be found [in the repository](https://raw.githubusercontent.com/gvellut/jncep/master/jncep/res/style.css). It is possible to download it and customize it. Then you can tell the `epub` command to use your own version by passing the `-t/--css` option with the path to your custom CSS as value.

### Configuration file

Just like the login and password, other options can be set in a configuration file. Here are the options that are used by the `epub` subcommand (and also by `update`):

- EMAIL
- PASSWORD
- OUTPUT
- CSS
- BYVOLUME
- IMAGES
- CONTENT
- NOREPLACE

To set an option, use the `jncep config set` command. For example:

```console
jncep config set OUTPUT "/user/gvellut/documents/jncepubs"
```

This will add a value for the OUTPUT configuration option. When the `jncep epub` command is run, the value of the `--output` option will be taken from the configuration file, unless the `--output` option is actually present on the command-line, in which case it will take priority.

**Note**: For `OUTPUT` or `CSS`, the values of which should be file paths, the `jncep config set` command doesn't process the `~` (user HOME directory, usually expanded by the shell) nor resolves a relative path to an absolute one. The output of the command will show what exact value will be used later by the `epub` and `update` commands: No additional transformation will be performed.

[See the paragraph about managing the configuration](#config) further in this page.

#### Flags

The options that set flags (BYVOLUME and below in the list above) should have one of the following values: `1`, `true`, `t`, `yes`, `y` or `on`. The value can be in upper case. 

For unsetting, the simplest is to use `config unset` to remove the configuration option (the default value for all those flags is `False`). If a value is set, it should be one of the following: `0`, `false`, `f`, `no`, `n` or `off`.

### Environment variables

The options can also be set using environment variables. They are the same as the configuration options, but with a `JNCEP_` prefix:

For example:
- JNCEP_PASSWORD
- JNCEP_OUTPUT
- JNCEP_CSS
- and so on ...

The specifig way of setting them will depend on your shell. For example, with Bash:

```console
export JNCEP_BYVOLUME=1
```

The names of the environment variables are __case-sensitive__.

### Priority order for option values

The priority order for option values is as follows:
1. If a value is passed on the command-line, it has the highest priority
2. If no value is passed, the value is taken from an environment variable if present
3. After that, the value is taken from the configuration file
4. Some options have a default value defined in the code: If no value has been explicitly passed using one of the 3 methods above, that default value will be used. Some options have no default values and are instead required: If no value is passed using one of the 3 methods just described, an error will be raised.

## track

This command is used to manage series to track. It has 4 subcommands:
- `add`: Add a new series for tracking. After a series has been added, it can be updated using the `update` command.
- `rm`: Remove a series from tracking
- `list`: List tracked serie
- `sync`:  Update the list of series to track based on series followed on the J-Novel Club website (or the opposite using the `--reverse` flag)

In the cases of `add` and `rm`, a URL link to a part or volume or series on the J-Novel Club website must be passed and is used to specify the series. Credentials are also needed for them (but not for `list`, which doesn't communicate with the J-Novel Club API).

### Tracking configuration

The tracking is performed by updating a local config file called `tracked.json` and located inside the configuration folder. The location of the folder will vary depending on the OS. See the [section dedicated to the configuration](#configuration-folder) for more details.

The configuration folder, as well the `tracked.json` file will be created by the tool if they don't exist.

The `tracked.json` file can be updated manually with a text editor if really needed but should generally be left alone (or `jncep` could malfunction).

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

An entry with key `https://j-novel.club/series/tearmoon-empire` will be added to the `tracked.json` file. Note that no Epub is generated by this command: Use the `epub` command to generate a file for the parts released until now.

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

The index inside the `[..]` can be used in the `rm` subcommand instead of the URL, as well as the `epub` command.

#### Sync

Using the `sync`subcommand, `track` will update the list of series tracked by `jncep` based on series followed on the J-Novel Club website:

```console
jncep track sync
```

The `--reverse` flag can be used for the opposite: The list of series followed on the J-Novel Club website will be updated to add series that are tracked locally by the `jncep` tool.

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
                          should be output in separate EPUBs
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
  -j, --jnc-managed       Flag to indicate whether to use the series followed
                          on the J-Novel Club website as the tracking
                          reference for updating (equivalent to running 'track
                          sync --delete --beginning' followed by 'update')
  -w, --whole             Flag to indicate whether the whole volume should be
                          regenerated when a new part is detected during the
                          update
  -f, --whole-final       Flag to indicate whether an EPUB with a complete
                          volume should also be generated when the final part
                          of the volume is included in the update
  -e, --use-events        Flag to use the events feed to check for updates
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

### Sync

The `--sync` flag can be passed (together with the other options), in which case the list of tracked series is first updated based on the list of followed series on the J-Novel Club website (equivalent of `jncep track sync`), then, only for the newly added series, an EPUB is created with the parts from the beginning.

It can be useful for when a new series starts publishing: It can be set as Followed on the website then this `jncep update --sync` command can be launched to subscribe to the series and get all the newly released parts in one go, and without having to copy/paste a URL.

### Events feed

If you have a lot of followed series and update often, the flag `--use-events` can be used. In that case, the `update` command will first check the events feed provided by J-Novel Club: It includes all the part releases and can be used to know which series will need to be downloaded. With this flag, the tool saves time by not checking all the series individually.

### Configuration & environment variables

Compared to the `epub` command, the `update` command understands the additional configuration options:
- USE_EVENTS
- WHOLE
- WHOLE_FINAL
- JNC_MANAGED

Since they are flags, they should have a value like `1`, `true`, `t`, `yes`, `y` or `on` (case insensitive) if set.

They are also available as environment variables:
- JNCEP_USE_EVENTS
- JNCEP_WHOLE
- JNCEP_WHOLE_FINAL
- JNCEP_JNC_MANAGED

### Automation

The `update` command can be called in the background from launchd (on macOS) or a scheduled task (on Windows) or cron (on Linux) in order to regularly download new content if available and create EPUBs (for example, once a day). 

There is no notification built in the `jncep update` command but the text output can be combined with other tools to make something suitable. If there are updates, the `jncep update` command outputs something like `2 series sucessfully updated!`, which can be processed by another tool do create a notification.

## config

This command is used to manage configuration options, as an alternative to passing values on the command line or through environment variables. 

It has 6 subcommands:
- `show`: Show some general info about the configuration (folder, actual configuration files, configuration values)
- `list`: Show available options that can be set
- `set`: Set the value of an option
- `unset`: Unset an option
- `init`: Create an empty `config.ini` file (for manual editing)
- `migrate`: Migrate configuration files to the post-v41 configuration folder

The configuration options are stored inside a `config.ini` file in the configuration folder. The file essentially uses the `.ini` file format for properties, except it doesn't support the `[...]` headers. When using the `set` command, the file will be created if needed.

### Options

To get some help about the `config` command, just launch with the `--help` option:

```console
~$ jncep config --help
Usage: jncep config [OPTIONS] COMMAND [ARGS]...

  Manage configuration

Options:
  --help  Show this message and exit.

Commands:
  init     Create configuration file
  list     List configuration options
  migrate  Migrate to standard configuration folder...
  set      Set configuration option
  show     List configuration details
  unset    Delete configuration option
```

In turn, the subcommands can be called with `--help` to get details about their arguments.

### Configuration folder

The configuation files are located inside the configuration folder that is either:
- `/Users/<user>/Library/Application Support/jncep` on macOS
- `C:\Users\<user>\AppData\Roaming\jncep` on Windows
- `/home/<user>/.config/jncep` on Linux

**Note**: On `jncep v41` and before, the configuration folder was created at `<HOME>/.jncep` (where `<HOME>` is either `/Users/<user>` on macOS, `C:\Users\<user>` on Windows or `/home/<user>` on Linux). If the folder was created at that location because such a version was previously used, it will stay there and `jncep` should keep working even if you update to a later version. The command `config migrate` can be used for migrating to the new location. The command `config show` can be used to make sure of the location of the configuration folder.

The folder contains both the `tracked.json` file used by the [`track`](#track) and [`update`](#update) commands, as well as the `config.ini` file that contains general configuration values used by all commands.

### show

The `show` subcommand shows some general info about the configuration:

```console
jncep config show
```

This will display something like:

```console
Configuration folder: C:\Users\gvellut\AppData\Roaming\jncep
Found config file: config.ini
Option: OUTPUT => output_test2
Option: BYVOLUME => Y
Found tracking file: tracked.json
13 series tracked
```

### list

The `list` subcommand shows available options that can be set:

```console
jncep config list
```

This will display something like:

```console
BYVOLUME       Flag to indicate that the parts of      
               different volumes should be output in
               separate EPUBs
CONTENT        Flag to indicate that the raw content of
               the parts should be extracted into the  
               output folder
CSS            Path to custom CSS file for the EPUBs   
EMAIL          Login email for J-Novel Club account
...
```

The same options can be set using environment variables (except there is a `JNCEP_` prefix).

### set

The `set` subcommand can be used to set the value for a configuration option:

```console
jncep config set EMAIL "jnclogin@aol.com"
```

The option names are case-insensitive so it could also be written as:

```console
jncep config set email "jnclogin@aol.com"
```

This will display something like:

```console
Option 'EMAIL' set to 'jnclogin@aol.com'
```

The `config.ini` file will be created if needed and will contain the following line:

```
EMAIL = jnclogin@aol.com
```

**Warning**: When using that command from the command-line, the shell may need some characters to be escaped. The rules vary depending on what shell is used. Also, for `OUTPUT` or `CSS`, the command doesn't process the `~` (user HOME directory, usually expanded by the shell) nor resolves a relative path to an absolute one. Please review the output to check if the option was set as intended. 

An alternative to using this command (as well as `unset`) is to edit the `config.ini` file with a text editor. The file must be saved in the **UTF-8 encoding**.

### unset

The `unset` subcommand can be used to remove a configuration option:

```console
jncep config unset OUTPUT
```

It will display something like:

```console
Option 'OUTPUT' unset
```

This will delete the `OUTPUT` option from the configuration file.

### init

The `init` subcommand creates an empty `config.ini` file:

```console
jncep config init
```

This will display something like:

```console
New empty config file created: C:\Users\gvellut\AppData\Roaming\jncep\config.ini
```

Then the file can be edited manually (or using the `set` and `unset` commands). After editing, the file must be saved using the **UTF-8 encoding**.

### migrate

The `migrate` subcommand can be used to migrate configuration files to the post-v41 standard configuration folder:

```console
jncep config migrate
```

This will display something like:

```console
The configuration is now in: C:\Users\gvellut\AppData\Roaming\jncep
You may delete: C:\Users\gvellut\.jncep
```

It creates the new folder and performs a simple copy of the files present in the old directory.

**Note**: `jncep` will keep functioning with the `<HOME>/.jncep` folder so it is not actually necessary to run this command.

# TODO (maybe)

- self-contained executable for macOS and Windows with PyInstaller
- simple GUI
