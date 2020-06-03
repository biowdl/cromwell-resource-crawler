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
import abc
import os
import sys
from abc import abstractmethod
from pathlib import Path
from typing import Dict, Generator, Iterable, Union

CROMWELL_EXECUTION_FOLDER_RESERVED_FILES = {
    "stdout",
    "stderr",
    "stdout.submit",
    "stderr.submit",
    "script",
    "script.submit",
    "rc"
}


def get_files_from_dir_recursively(path: Union[os.PathLike, str]
                                   ) -> Generator[Path, None, None]:
    for path, dirs, files in os.walk(path):
        for file in files:
            yield Path(path, file)


class Job(abc.ABC):
    def __init__(self, path: Path):
        self.path: Path = path
        self.execution_folder: Path = path / "execution"
        self.inputs_folder: Path = path / "inputs"
        self.stdout_submit: Path = self.execution_folder / "stdout.submit"
        self.name = self._get_name()

    @abstractmethod
    def get_resources(self) -> Dict[str, Union[float, int]]:
        pass

    def outputs(self) -> Generator[Path, None, None]:
        for path, dirs, files in os.walk(self.execution_folder):
            for file in files:
                if file not in CROMWELL_EXECUTION_FOLDER_RESERVED_FILES:
                    yield Path(path, file)
            for dir in dirs:
                yield from get_files_from_dir_recursively(Path(path, dir))

    def inputs(self) -> Generator[Path, None, None]:
        return get_files_from_dir_recursively(self.inputs_folder)

    def get_input_filesizes(self) -> Dict[str, int]:
        return {
            str(path.relative_to(self.inputs_folder)): path.stat().st_size
            for path in self.inputs()
        }

    def get_output_filesizes(self) -> Dict[str, int]:
        return {
            str(path.relative_to(self.execution_folder)): path.stat().st_size
            for path in self.outputs()
        }

    def get_exit_code(self) -> int:
        return int(Path(self.execution_folder, "rc").read_text())

    def _get_name(self) -> str:
        for name in reversed(self.path.parts):
            if name.startswith("call-"):
                return name


class LocalJob(Job):
    def get_resources(self) -> Dict[str, Union[float, int]]:
        return {}


def crawl_workflow_folder(workflow_folder: Path, jobclass: Job = LocalJob
                          ) -> Generator[Job, None, None]:
    for uuid in workflow_folder.iterdir():
        for call_folder in uuid.iterdir():
            yield from crawl_call_folder(call_folder, jobclass)


def crawl_call_folder(call_folder: Path, jobclass: Job = LocalJob
                      ) -> Generator[Job, None, None]:
    if Path(call_folder, "execution").exists():
        yield jobclass(call_folder)
    elif Path(call_folder, "cacheCopy").exists():
        return
    else:
        for folder in call_folder.iterdir():
            if folder.name.startswith("shard-"):
                yield from crawl_call_folder(folder, jobclass)
            else:
                yield from crawl_workflow_folder(folder, jobclass)


def job_tree(jobs: Iterable[Job]) -> Dict:
    tree = {}
    for job in jobs:
        id = job.id
        if len(id) == 1:
            tree[id[0]] = job.get_resources()
        else:
            job.id = id[1:]
            tree[id[0]] = job_tree([job])
    return tree


def main():
    pipeline_folder = Path(sys.argv[1])
    for job in crawl_workflow_folder(pipeline_folder):
        print(job.path)


if __name__ == "__main__":
    main()
