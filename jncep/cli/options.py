import os

import click

from ..config import ENVVAR_PREFIX

login_option = click.option(
    "-l",
    "--email",
    required=True,
    envvar=f"{ENVVAR_PREFIX}EMAIL",
    help="Login email for J-Novel Club account",
)

password_option = click.option(
    "-p",
    "--password",
    required=True,
    envvar=f"{ENVVAR_PREFIX}PASSWORD",
    help="Login password for J-Novel Club account",
)

output_option = click.option(
    "-o",
    "--output",
    "output_dirpath",
    type=click.Path(resolve_path=True, file_okay=False, writable=True),
    default=os.getcwd(),
    envvar=f"{ENVVAR_PREFIX}OUTPUT",
    help="Folder to write the output files. It will be created if it doesn't exist "
    "[default: The current directory]",
)

byvolume_option = click.option(
    "-v",
    "--byvolume",
    "is_by_volume",
    is_flag=True,
    envvar=f"{ENVVAR_PREFIX}BYVOLUME",
    help=(
        "Flag to indicate that the parts of different volumes should be output in "
        "separate EPUBs"
    ),
)

images_option = click.option(
    "-i",
    "--images",
    "is_extract_images",
    is_flag=True,
    envvar=f"{ENVVAR_PREFIX}IMAGES",
    help=(
        "Flag to indicate that the images of the novel should be extracted into "
        "the output folder"
    ),
)

raw_content_option = click.option(
    "-c",
    "--content",
    "is_extract_content",
    is_flag=True,
    envvar=f"{ENVVAR_PREFIX}CONTENT",
    help=(
        "Flag to indicate that the raw content of the parts should be extracted into "
        "the output folder"
    ),
)

# TODO rename alias to --noreplace (like --byvolume) or the opposite
# provide backward compatibility
no_replace_chars_option = click.option(
    "-n",
    "--no-replace",
    "is_not_replace_chars",
    is_flag=True,
    envvar=f"{ENVVAR_PREFIX}NOREPLACE",
    help=(
        "Flag to indicate that some unicode characters unlikely to be in an EPUB "
        "reader font should NOT be replaced and instead kept as is"
    ),
)


css_option = click.option(
    "-t",
    "--css",
    "style_css_path",
    type=click.Path(exists=True, resolve_path=True, file_okay=True, dir_okay=False),
    envvar=f"{ENVVAR_PREFIX}CSS",
    help="Path to custom CSS file for the EPUBs [default: The CSS provided by JNCEP]",
)
