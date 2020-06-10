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
import datetime
import json
import os
import re
import subprocess
from abc import abstractmethod
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, List, Set, Union

from humanize.filesize import naturalsize


def cromwell_execution_folder_reserved_files() -> Set[str]:
    reserved_files: Set[str] = set()
    prefixes = ["stdout", "script", "stderr"]
    suffixes = ["", ".submit", ".check", ".background"]
    for prefix in prefixes:
        for suffix in suffixes:
            reserved_files.add(prefix + suffix)
    reserved_files.add("rc")
    return reserved_files


CROMWELL_EXECUTION_FOLDER_RESERVED_FILES = \
    cromwell_execution_folder_reserved_files()


def get_files_from_dir_recursively(path: Union[os.PathLike, str]
                                   ) -> Generator[Path, None, None]:
    for base_path, dirs, files in os.walk(path):
        for file in files:
            yield Path(base_path, file)


class Job(abc.ABC):
    def __init__(self, path: Path):
        self.path: Path = path
        self.execution_folder: Path = path / "execution"
        self.inputs_folder: Path = path / "inputs"
        self.name = self._get_name()

    @abstractmethod
    def property_order(self) -> List[str]:
        return ["Name", "ExitCode", "Inputs", "Outputs", "Path"]

    @abstractmethod
    def get_properties(self, human_readable: bool) -> Dict[str, Any]:
        props: Dict[str, Any] = {
            "Name": self.name,
            "ExitCode": self.get_exit_code(),
            "Inputs": self.get_input_filesizes(),
            "Outputs": self.get_output_filesizes(),
            "Path": str(self.path)
        }
        if human_readable:
            props["Inputs"] = self.sizes_to_human_readable(props["Inputs"])
            props["Outputs"] = self.sizes_to_human_readable(props["Outputs"])
        return props

    def tsv_properties(self, human_readable: bool
                       ) -> Generator[str, None, None]:
        properties = self.get_properties(human_readable)
        for key in self.property_order():
            value = properties[key]
            # jsonify containers
            if not isinstance(value, str) and hasattr(value, "__getitem__"):
                yield json.dumps(value)
            else:
                yield str(value)

    def to_json(self, human_readable) -> Dict[str, Any]:
        return self.get_properties(human_readable)

    def tsv_header(self) -> str:
        return "\t".join(self.property_order()) + os.linesep

    def tsv_row(self, human_readable) -> str:
        return "\t".join(self.tsv_properties(human_readable)) + os.linesep

    def outputs(self) -> Generator[Path, None, None]:
        for path, folders, files in os.walk(self.execution_folder):
            for file in files:
                if file not in CROMWELL_EXECUTION_FOLDER_RESERVED_FILES:
                    yield Path(path, file)
            for folder in folders:
                yield from get_files_from_dir_recursively(Path(path, folder))

    def inputs(self) -> Generator[Path, None, None]:
        return get_files_from_dir_recursively(self.inputs_folder)

    @staticmethod
    def sizes_to_human_readable(sizes: Dict[str, int]):
        return {path: naturalsize(size, binary=True)
                for path, size in sizes.items()}

    def get_input_filesizes(self) -> Dict[str, int]:
        return self._size_calculation(self.inputs(), self.inputs_folder)

    def get_output_filesizes(self) -> Dict[str, int]:
        return self._size_calculation(self.outputs(), self.execution_folder)

    @staticmethod
    def _size_calculation(files: Iterable[Path], relative_to: Path
                          ) -> Dict[str, int]:
        return {str(path.relative_to(relative_to)): path.stat().st_size
                for path in files if path.exists()}

    def get_exit_code(self) -> int:
        return int(Path(self.execution_folder, "rc").read_text())

    def _get_name(self) -> str:
        for name in reversed(self.path.parts):
            if name.startswith("call-"):
                return name
        raise ValueError(f"No name found for job at path: {self.path}")


class LocalJob(Job):
    def property_order(self) -> List[str]:
        return super().property_order()

    def get_properties(self, human_readable: bool):
        return super().get_properties(human_readable)


DEFAULT_SLURM_JOB_REGEX = re.compile(r"Submitted batch job (\d+).*")

# SLURM uses a base of 1024
# https://github.com/SchedMD/slurm/blob/753db1d52c9bb91f970d83aa9418a6faddf93461/src/common/slurm_protocol_api.c#L3265
SLURM_SUFFIXES = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4,
                  "Kn": 1024, "Mn": 1024**2, "Gn": 1024**3, "Tn": 1024**4}


def slurm_number(value: str) -> int:
    for suffix, multiplier in SLURM_SUFFIXES.items():
        if value.endswith(suffix):

            return round(float(value.rstrip(suffix)) * multiplier)
    return int(value)


def slurm_time(value: str) -> int:
    if "-" in value:
        days, time = value.split("-")
    else:
        days = "0"
        time = value
    hours, minutes, seconds = time.split(":")
    return (int(days) * 24 * 3600 +
            int(hours) * 3600 +
            int(minutes) * 60 +
            int(seconds))


class SlurmJob(Job):
    def __init__(self, path: Path,
                 job_regex: re.Pattern = DEFAULT_SLURM_JOB_REGEX):
        super().__init__(path)
        self._job_regex = job_regex
        self.stdout_submit: Path = self.execution_folder / "stdout.submit"

    @staticmethod
    def cluster_properties() -> List[str]:
        return ["State", "Timelimit", "Elapsed", "CPUTime", "ReqCPUS",
                "ReqMem", "MaxRSS", "MaxVMSize", "MaxDiskRead", "MaxDiskWrite"]

    def property_order(self) -> List[str]:
        super_order = super().property_order()
        # Insert cluster properties after name and exit code.
        return super_order[:2] + self.cluster_properties() + super_order[2:]

    def get_properties(self, human_readable: bool):
        props = super().get_properties(human_readable)
        props.update(self.get_cluster_accounting())
        if human_readable:
            for key in ["ReqMem", "MaxRSS", "MaxVMSize", "MaxDiskRead",
                        "MaxDiskWrite"]:
                size = props[key]
                props[key] = naturalsize(size, binary=True)
            for key in ["Timelimit", "Elapsed", "CPUTime"]:
                seconds = props[key]
                props[key] = str(datetime.timedelta(seconds=seconds))
        return props

    def job_id(self) -> str:
        match = self._job_regex.match(self.stdout_submit.read_text())
        if match is None:
            raise ValueError(f"Could not get job id from {self.stdout_submit}")
        return match.group(1)

    def _cluster_account_command(self) -> str:
        args = ("sacct", "-j", self.job_id(), "--parsable2",
                "--format", ",".join(self.cluster_properties()))
        result = subprocess.run(args, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True)

        return result.stdout.decode()

    def get_cluster_accounting(self) -> Dict[str, Union[str, int]]:
        cluster_accounting = self._cluster_account_command()
        lines = cluster_accounting.splitlines(keepends=False)
        headers = lines[0].split("|")
        total_usage = lines[1].split("|")
        batch_usage = lines[2].split("|")
        total_dict = dict(zip(headers, total_usage))
        batch_dict = dict(zip(headers, batch_usage))
        new_dict: Dict[str, Union[str, int]] = {}
        for key in ["ReqMem", "MaxRSS", "MaxVMSize", "MaxDiskRead",
                    "MaxDiskWrite"]:
            new_dict[key] = slurm_number(batch_dict.pop(key))
        # Remove timelimit from batch_dict so we don't accidently overwrite the
        # Timelimit value in new_dict later
        batch_dict.pop("Timelimit")
        # Timelimit is not set on the batch job level.
        new_dict["Timelimit"] = slurm_time(total_dict["Timelimit"])
        for key in ["Elapsed", "CPUTime"]:
            new_dict[key] = slurm_time(batch_dict.pop(key))
        # Add all remaining keys.
        new_dict.update(batch_dict)
        return new_dict
