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
from typing import Generator, List, Dict, Union, Tuple, Optional


def recursive_iterdir(path: Path) -> Generator[Path, None, None]:
    for sub_path in path.iterdir():
        if sub_path.is_dir():
            for sub_sub_path in recursive_iterdir(sub_path):
                yield sub_sub_path
        else:
            yield sub_path


class Job():
    def __init__(self, path: Path, id: Tuple[str]):
        self.path: Path = path
        self.id = id
        executions = path / "executions"
        self.stdout_submit: Path = executions / "stdout.submit"
        self.inputs: List[Path] = list(recursive_iterdir(path / "inputs"))
        self.resources: Dict[str, Union[float, int]] = self.get_resources()

    def get_resources(self):
        return {}


def crawl_workflow_folder(workflow_folder: Path, jobclass: Job = Job,
                          id: Optional[List[str]] = None
                          ) -> Generator[Job, None, None]:
    base_id = id or []
    for uuid in workflow_folder.iterdir():
        this_id = base_id + [uuid.name]
        for call_folder in uuid.iterdir():
            for job in crawl_call_folder(call_folder, jobclass, this_id):
                yield job


def crawl_call_folder(call_folder: Path, jobclass: Job = Job,
                      id: Optional[List[str]] = None
                      ) -> Generator[Job, None, None]:
    base_id = id or []
    this_id = base_id + [call_folder.name]
    if Path(call_folder, "cacheCopy").exists():
        return
    if Path(call_folder, "execution").exists():
        yield jobclass(call_folder, tuple(this_id))
    elif Path(call_folder, "shard-0").exists():
        for shard in call_folder.iterdir():
            for job in crawl_call_folder(shard, jobclass, this_id):
                yield job
    else:
        for workflow_folder in call_folder.iterdir():
            for job in crawl_workflow_folder(workflow_folder, jobclass, this_id):  # noqa: E502
                yield job
