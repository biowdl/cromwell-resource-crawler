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

import json
import os
import sys
import tempfile
from pathlib import Path

from cromwell_resource_crawler import main

from . import TEST_DATA

BASIC_ARGS = ["cromwell-resource-crawler",
              str(TEST_DATA / "cromwell-executions"),
              "--name", "mergeBeds"]


def test_tsv():
    out_file = tempfile.mktemp()
    sys.argv = BASIC_ARGS + ["--format", "tsv", "-o", out_file]
    main()
    output = Path(out_file).read_text()
    assert "Name\tExitCode" in output
    assert output.split("\n")[1].startswith("call-mergeBeds")
    assert len(output.split("\n")) == 3
    os.unlink(out_file)


def test_json():
    out_file = tempfile.mktemp()
    sys.argv = BASIC_ARGS + ["--format", "json", "-o", out_file]
    main()
    output = json.loads(Path(out_file).read_text())
    job = output["MultisampleCalling"]["49fed616-9748-4aca-bd2e-90c0ccb43116"][
        "call-calculateRegions"]["CalculateRegions"][
        "8b79bccf-6989-4068-8cb5-a811f0aff13f"]["call-mergeBeds"]
    assert job["ExitCode"] == "0"
    assert set(job["Inputs"].keys()) == {"1489649706/y_non_par.bed",
                                         "1489649706/x_non_par.bed"}
