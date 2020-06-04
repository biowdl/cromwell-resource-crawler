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
from cromwell_resource_crawler import crawl_folder

import pytest

from . import TEST_DATA

FULL_CRAWL_PATH_PARTS = Path(
    "cromwell-executions", "MultisampleCalling",
    "49fed616-9748-4aca-bd2e-90c0ccb43116", "call-JointGenotyping",
    "JointGenotyping", "f24f616d-845b-40d0-8bd1-5441dcd033e7",
    "call-genotypeGvcfs", "shard-0", "execution").parts
CRAWL_FOLDER_TESTS = [
    (Path(TEST_DATA, *FULL_CRAWL_PATH_PARTS[:1]), 14),  # cromwell-executions
    (Path(TEST_DATA, *FULL_CRAWL_PATH_PARTS[:2]), 14),  # MultisampleCalling
    (Path(TEST_DATA, *FULL_CRAWL_PATH_PARTS[:3]), 14),  # 49fed616-9748-4aca-bd2e-90c0ccb43116 # noqa: E501
    (Path(TEST_DATA, *FULL_CRAWL_PATH_PARTS[:4]), 6),  # call-JointGenotyping
    (Path(TEST_DATA, *FULL_CRAWL_PATH_PARTS[:5]), 6),  # JointGenotyping
    (Path(TEST_DATA, *FULL_CRAWL_PATH_PARTS[:6]), 6),  # f24f616d-845b-40d0-8bd1-5441dcd033e7 # noqa: E501
    (Path(TEST_DATA, *FULL_CRAWL_PATH_PARTS[:7]), 3),  # call-genotypeGvcfs
    (Path(TEST_DATA, *FULL_CRAWL_PATH_PARTS[:8]), 1),  # shard-0
]


@pytest.mark.parametrize(["folder", "length"], CRAWL_FOLDER_TESTS)
def test_crawl_folder(folder, length):
    jobs = list(crawl_folder(folder))
    assert len(jobs) == length
