import functools
import os

import click
import click_option_group as cog

from ..config import ENVVAR_PREFIX
from ..jncalts import AltCredentials, AltOrigin

credentials_group = cog.OptionGroup(
    "Credentials",
    help="At least one set of credentials must be filled",
)


login_option = credentials_group.option(
    "-l",
    "--email",
    envvar=f"{ENVVAR_PREFIX}EMAIL",
    help="Login email for J-Novel Club account",
)

password_option = credentials_group.option(
    "-p",
    "--password",
    envvar=f"{ENVVAR_PREFIX}PASSWORD",
    help="Login password for J-Novel Club account",
)

login_nina_option = credentials_group.option(
    "-ln",
    "--email-nina",
    envvar=f"{ENVVAR_PREFIX}EMAIL_NINA",
    help="Login email for JNC Nina account",
)

password_nina_option = credentials_group.option(
    "-pn",
    "--password-nina",
    envvar=f"{ENVVAR_PREFIX}PASSWORD_NINA",
    help="Login password for JNC Nina account",
)


def credentials_options(f):
    # applied in reverse so they are visible in the help in the order below
    for option in reversed(
        [
            login_option,
            password_option,
            login_nina_option,
            password_nina_option,
            process_credentials_options,
        ]
    ):
        f = option(f)
    return f


def process_credentials_options(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        # not generic : just main JNC + nina
        # options should always be present even if no value passed
        email = kwargs.pop("email")
        password = kwargs.pop("password")
        email_nina = kwargs.pop("email_nina")
        password_nina = kwargs.pop("password_nina")

        # if in there : possibly the cli commmand has be command using ctx.invoke
        # reuse and ignore the login, pw options (which will be empty)
        if "credentials" not in kwargs:
            if not email_nina and password_nina:
                email_nina = email

            j_novel_credentials = email and password
            nina_credentials = email_nina and password_nina

            if nina_credentials and email and not password:
                # assume the email only applies to nina
                email = None

            if not j_novel_credentials and not nina_credentials:
                raise click.UsageError(
                    "You must pass either J-Novel Club or JNC Nina credentials"
                )

            if bool(email) != bool(password):
                raise click.UsageError(
                    "You must pass both email and password for J-Novel Club account"
                )

            if bool(email_nina) != bool(password_nina):
                raise click.UsageError(
                    "You must pass both email and password for JNC Nina account"
                )

            credential_mapping = {}
            if j_novel_credentials:
                credential_mapping[AltOrigin.JNC_MAIN] = (email, password)
            if nina_credentials:
                credential_mapping[AltOrigin.JNC_NINA] = (email_nina, password_nina)

            kwargs["credentials"] = AltCredentials(credential_mapping)

        f(*args, **kwargs)

    return wrapper


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

subfolder_option = click.option(
    "-u",
    "--subfolder",
    "is_subfolder",
    is_flag=True,
    envvar=f"{ENVVAR_PREFIX}SUBFOLDER",
    help="Create subfolders with the series name inside the output folder",
)


namegen_option = click.option(
    "-g",
    "--namegen",
    "namegen_rules",
    envvar=f"{ENVVAR_PREFIX}NAMEGEN",
    help="Name generation rules (see GH for documentation)",
)
