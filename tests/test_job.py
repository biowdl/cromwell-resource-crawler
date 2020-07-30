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

import datetime
import os
import tempfile
import time
from pathlib import Path

from cromwell_resource_crawler.jobs import LocalJob, SlurmJob

import pytest

from . import TEST_DATA


@pytest.fixture(scope="module")
def localjob() -> LocalJob:
    return LocalJob(TEST_DATA / "call-ConvertDockerTagsFile")


@pytest.fixture(scope="module")
def slurmjob() -> SlurmJob:
    job = SlurmJob(TEST_DATA / "call-ConvertDockerTagsFile")

    def return_accounting() -> str:
        return """State|Timelimit|Elapsed|CPUTime|TotalCPU|ReqMem|MaxRSS|MaxVMSize|MaxDiskRead|MaxDiskWrite
COMPLETED|00:01:00|00:00:02|00:00:02|00:00.208|128Mn||||
COMPLETED||00:00:02|00:00:02|00:00.207|128Mn|1340K|344240K|0|0
COMPLETED||00:00:02|00:00:02|00:00:00|128Mn|984K|278348K|0|0
"""
    setattr(job, "_cluster_account_command", return_accounting)
    return job


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


def test_job_id(slurmjob):
    assert slurmjob.job_id() == "362781"


def test_properties_human_readable(slurmjob):
    props = slurmjob.get_properties(True)
    assert props["CPUTime"] == "0:00:02"
    assert props["MaxRSS"] == "1.3 MiB"


def test_properties_raw(slurmjob):
    props = slurmjob.get_properties(False)
    assert props["CPUTime"] == 2
    assert props["MaxRSS"] == 1372160


def test_local_runtime():
    # Create a temporary folder for the mock execution structure
    with tempfile.TemporaryDirectory(prefix="call-") as job:
        # Create the execution folder
        execution = os.path.join(job, "execution")
        os.mkdir(execution)

        # Create the script.submit file
        script_submit = os.path.join(execution, "script.submit")
        with open(script_submit, 'w') as fin:
            pass

        # Sleep for 1.5 seconds
        time.sleep(1.5)

        # Create the rc file
        rc = os.path.join(execution, "rc")
        with open(rc, 'w') as fin:
            print("0", file=fin)

        jobfolder = LocalJob(Path(job))

        props = jobfolder.get_properties(False)
        # If we slept for 1.5 seconds, time should at least be 1, independent
        # of what the OS has been doing in the mean time
        assert props["Elapsed"] >= 1

        # Get the runtime in human readable format
        props = jobfolder.get_properties(True)
        human_time = time.strptime(props["Elapsed"], '%H:%M:%S')
        # Convert it back to seconds
        seconds = datetime.timedelta(hours=human_time.tm_hour,
                                     minutes=human_time.tm_min,
                                     seconds=human_time.tm_sec).total_seconds()
        assert seconds >= 1
