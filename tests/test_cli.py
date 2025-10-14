import os
import shutil

from click.testing import CliRunner
import pytest

from jncep.cli import epub

creds_not_available = not (
    os.getenv("JCNEP_TEST_EMAIL") and os.getenv("JCNEP_TEST_PASSWORD")
)
nina_creds_not_available = not (
    os.getenv("JCNEP_TEST_EMAIL") and os.getenv("JCNEP_TEST_PASSWORD_NINA")
)


def delete_all_files_in_directory(directory_path):
    if not os.path.exists(directory_path):
        os.makedirs(directory_path)
        return
    for filename in os.listdir(directory_path):
        file_path = os.path.join(directory_path, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f"Failed to delete {file_path}. Reason: {e}")


@pytest.mark.skipif(creds_not_available, reason="JNC test credentials not provided")
def test_simple_fetch_epub():
    url = (
        "https://j-novel.club/read/long-story-short-i-m-living-in-the-"
        + "mountains-volume-1-part-1"
    )
    email = os.getenv("JCNEP_TEST_EMAIL")
    pwd = os.getenv("JCNEP_TEST_PASSWORD")
    output_dirpath = "test_output"

    delete_all_files_in_directory(output_dirpath)

    runner = CliRunner()
    result = runner.invoke(
        epub.generate_epub,
        [
            "--email",
            email,
            "--password",
            pwd,
            "--output",
            output_dirpath,
            "--namegen",
            "default",
            url,
        ],
    )
    assert result.exit_code == 0
    output_file = os.path.join(
        output_dirpath,
        "Long_Story_Short_I_m_Living_in_the_Mountains_Volume_1_Part_1.epub",
    )
    assert os.path.exists(output_file)
    assert os.path.getsize(output_file) > 0


@pytest.mark.skipif(
    nina_creds_not_available, reason="JNC Nina test credentials not provided"
)
def test_simple_fetch_epub_jna():
    url = "https://jnc-nina.eu/read/brunhild-die-drachenschlaechterin-teil-1"
    email = os.getenv("JCNEP_TEST_EMAIL")
    pwd = os.getenv("JCNEP_TEST_PASSWORD_NINA")
    output_dirpath = "test_output"

    delete_all_files_in_directory(output_dirpath)

    runner = CliRunner()
    result = runner.invoke(
        epub.generate_epub,
        [
            "--email",
            email,
            "--password-nina",
            pwd,
            "--output",
            output_dirpath,
            "--namegen",
            "default",
            url,
        ],
    )
    assert result.exit_code == 0
    output_file = os.path.join(
        output_dirpath,
        "Brunhild_die_Drachenschlachterin_Teil_1.epub",
    )
    assert os.path.exists(output_file)
    assert os.path.getsize(output_file) > 0
