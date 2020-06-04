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
import argparse
import json
import os
import re
import subprocess
import sys
from abc import abstractmethod
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, List, Optional, Type, Union

from humanize.filesize import naturalsize

DEFAULT_OUTPUT = "/dev/stdout" if sys.platform in ["linux", "darwin"] else None

CROMWELL_EXECUTION_FOLDER_RESERVED_FILES = {
    "stdout",
    "stderr",
    "stdout.submit",
    "stderr.submit",
    "script",
    "script.submit",
    "script.check",
    "stdout.check",
    "stderr.check",
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
        self.name = self._get_name()

    @abstractmethod
    def to_json(self) -> Dict[str, Any]:
        return {
            "inputs": self.get_input_filesizes(),
            "outputs": self.get_output_filesizes()
        }

    @classmethod
    @abstractmethod
    def tsv_header(cls) -> str:
        pass

    @abstractmethod
    def tsv_row(self) -> str:
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

    def get_input_filesizes(self) -> Dict[str, str]:
        return {
            str(path.relative_to(self.inputs_folder)):
                naturalsize(path.stat().st_size)
            for path in self.inputs()
        }

    def get_output_filesizes(self) -> Dict[str, int]:
        return {
            str(path.relative_to(self.execution_folder)):
                naturalsize(path.stat().st_size)
            for path in self.outputs()
        }

    def get_exit_code(self) -> int:
        return int(Path(self.execution_folder, "rc").read_text())

    def _get_name(self) -> str:
        for name in reversed(self.path.parts):
            if name.startswith("call-"):
                return name
        raise ValueError(f"No name found for job at path: {self.path}")


class LocalJob(Job):

    def to_json(self) -> Dict[str, Any]:
        return super().to_json()

    @classmethod
    def tsv_header(cls) -> str:
        raise NotImplementedError("TSV representation not implemented for "
                                  "local jobs.")

    def tsv_row(self) -> str:
        raise NotImplementedError("TSV representation not implemented for "
                                  "local jobs.")


DEFAULT_SLURM_JOB_REGEX = re.compile(r"Submitted batch job (\d+).*")

SLURM_SUFFIXES = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}


def slurm_number(value: str) -> int:
    for suffix, multiplier in SLURM_SUFFIXES.items():
        if value.endswith(suffix):

            return int(value.rstrip(suffix)) * multiplier
    return int(value)


def slurm_time(value: str) -> int:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds)


class SlurmJob(Job):
    def __init__(self, path: Path,
                 job_regex: re.Pattern = DEFAULT_SLURM_JOB_REGEX):
        super().__init__(path)
        self._job_regex = job_regex
        self.stdout_submit: Path = self.execution_folder / "stdout.submit"

    @classmethod
    def cluster_properties(cls) -> List[str]:
        return ["ReqCPUs", "Timelimit", "Elapsed", "CPUTime", "ReqMem",
                "MaxRSS", "MaxVMSize", "MaxDiskRead", "MaxDiskWrite"]

    def job_id(self) -> str:
        match = self._job_regex.match(self.stdout_submit.read_text())
        if match is None:
            raise ValueError(f"Could not get job id from {self.stdout_submit}")
        return match.group(1)

    def _cluster_account_command(self) -> str:
        args = ("sacct", "-j", self.job_id(), "-l", "--parsable2",
                "--format", ",".join(self.cluster_properties()))
        result = subprocess.run(args, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True)

        return result.stdout.decode()

    def get_cluster_accounting(self) -> Dict[str, str]:
        cluster_accounting = self._cluster_account_command()
        lines = cluster_accounting.splitlines(keepends=False)
        headers = lines[0].split("|")
        total_usage = lines[1].split("|")
        batch_usage = lines[2].split("|")
        total_dict = dict(zip(headers, total_usage))
        batch_dict = dict(zip(headers, batch_usage))
        batch_dict["Timelimit"] = total_dict["Timelimit"]
        return batch_dict

    def to_json(self) -> Dict[str, Any]:
        json_dict = self.get_cluster_accounting()
        json_dict.update(super().to_json())
        return json_dict

    @classmethod
    def tsv_header(cls):
        return ("\t".join(("Path", "Name", *cls.cluster_properties()))
                + os.linesep)

    def tsv_row(self):
        return ("\t".join((str(self.path), self.name,
                           *self.get_cluster_accounting().values()))
                + os.linesep)


def crawl_folder(folder: Path, jobclass: Type[Job] = LocalJob
                 ) -> Generator[Job, None, None]:
    if not folder.is_dir():
        raise ValueError(f"{folder} is not a directory!")
    if folder.name == "cromwell-executions":
        for path in os.scandir(folder):  # type: os.DirEntry
            if not path.is_dir():
                continue
            if "-" not in path.name:
                yield from crawl_workflow_folder(Path(path.name), jobclass)
    elif folder.name.startswith("call-"):
        yield from crawl_call_folder(folder, jobclass)
    else:
        yield from crawl_workflow_folder(folder, jobclass)


def crawl_workflow_folder(workflow_folder: Path, jobclass: Type[Job] = LocalJob
                          ) -> Generator[Job, None, None]:
    for uuid in workflow_folder.iterdir():
        for call_folder in uuid.iterdir():
            yield from crawl_call_folder(call_folder, jobclass)


def crawl_call_folder(call_folder: Path, jobclass: Type[Job] = LocalJob
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


def jobs_to_json_dict(jobs: Iterable[Job],
                      start_path: Optional[Path] = None) -> Dict:
    json_dict: Dict[str, Any] = {}
    for job in jobs:
        job_path = (job.path if start_path is None
                    else job.path.relative_to(start_path))
        part_dict = json_dict
        for part in job_path.parts[:-1]:
            if part not in part_dict:
                part_dict[part] = {}
            part_dict = part_dict[part]
        part_dict[job_path.parts[-1]] = job.to_json()
    return json_dict


def jobs_to_tsv(jobs: Iterable[Job]) -> Generator[str, None, None]:
    job_iter = iter(jobs)
    first_job = next(job_iter)
    yield first_job.tsv_header()
    yield first_job.tsv_row()
    for job in job_iter:
        yield job.tsv_row()


JOBS_DICT = dict(slurm=SlurmJob, local=LocalJob)


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("workflow_dir", type=str,
                        help="Workflow directory. Such as "
                             "cromwell-executions/WORKFLOW_DIR.")
    parser.add_argument("-b", "--backend", type=str, choices=JOBS_DICT.keys(),
                        default="local")
    parser.add_argument("-f", "--output-format", type=str,
                        choices=["json", "tsv"], default="json")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT,
                        required=bool(DEFAULT_OUTPUT))
    parser.add_argument("-n", "--name", required=False,
                        help="Select only jobs named 'call-NAME'.")
    parser.add_argument("-p", "--filter", metavar="STRING",
                        help="Select only jobs where STRING is part of the "
                             "path.")
    return parser


def main():
    args = argument_parser().parse_args()
    workflow_folder = Path(args.workflow_dir)
    jobs = crawl_folder(workflow_folder, jobclass=JOBS_DICT[args.backend])
    if args.name is not None:
        jobs = (job for job in jobs if job.name == "call-" + args.name)
    if args.filter is not None:
        jobs = (job for job in jobs if args.filter in str(job.path))
    with open(args.output, "wt") as output_h:
        if args.output_format == "json":
            json.dump(jobs_to_json_dict(jobs, workflow_folder), output_h)
        elif args.output_format == "tsv":
            for line in jobs_to_tsv(jobs):
                output_h.write(line)


if __name__ == "__main__":
    main()
