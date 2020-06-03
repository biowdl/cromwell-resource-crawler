# Copyright (c) 2020 Leiden University Medical Center
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from pathlib import Path

from cromwell_resource_crawler import LocalJob

import pytest

from . import TEST_DATA


@pytest.fixture(scope="module")
def localjob() -> LocalJob:
    return LocalJob(TEST_DATA / "call-ConvertDockerTagsFile")


def test_exit_code_correct(localjob):
    assert localjob.get_exit_code() == 0


def test_input_filesizes(localjob):
    assert localjob.get_input_filesizes() == {
        "1599980398/dockerImages.yml": 1988
    }


def test_output_filesize(localjob):
    assert localjob.get_output_filesizes() == {
        "dockerImages.json": 1295,
        "nested_outputs/dummy_output": 34
    }


def test_name(localjob):
    assert localjob.name == "call-ConvertDockerTagsFile"
