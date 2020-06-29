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
    """
    Return filenames which are used by cromwell itself.
    :return: A set of filenames
    """
    reserved_files: Set[str] = set()
    prefixes = ["stdout", "script", "stderr"]
    suffixes = ["", ".submit", ".check", ".background", ".kill"]
    for prefix in prefixes:
        for suffix in suffixes:
            reserved_files.add(prefix + suffix)
    reserved_files.add("rc")
    return reserved_files


CROMWELL_EXECUTION_FOLDER_RESERVED_FILES = \
    cromwell_execution_folder_reserved_files()


def get_files_from_dir_recursively(path: Union[os.PathLike, str]
                                   ) -> Generator[Path, None, None]:
    """
    Version of os.walk that yields only files.
    :param path: The path to search.
    :return: Path object for every file found.
    """
    for base_path, dirs, files in os.walk(path):
        for file in files:
            yield Path(base_path, file)


class Job(abc.ABC):
    """
    The base class for all Job-types. Implements all the basic methods for
    analyzing the output.
    """
    def __init__(self, path: Path):
        self.path: Path = path
        self.execution_folder: Path = path / "execution"
        self.inputs_folder: Path = path / "inputs"
        self.name = self._get_name()

    @abstractmethod
    def property_order(self) -> List[str]:
        """
        A list of fields that should be in the TSV header.
        """
        return ["Name", "ExitCode", "Inputs", "Outputs", "Path"]

    @abstractmethod
    def get_properties(self, human_readable: bool) -> Dict[str, Any]:
        """
        Get a dictionary of properties
        :param human_readable: Whether properties should be converted to a
        human-readable format or kept as raw values.
        :return: A dictionary
        """
        inputs = self.get_input_filesizes()
        outputs = self.get_output_filesizes()
        if human_readable:
            inputs = self._sizes_to_human_readable(inputs)
            outputs = self._sizes_to_human_readable(outputs)
        return {
            "Name": self.name,
            "Inputs": inputs,
            "Outputs": outputs,
            "ExitCode": self.get_exit_code(),
            "Path": str(self.path)
        }

    def tsv_properties(self, human_readable: bool
                       ) -> Generator[str, None, None]:
        """
        Convert all properties to a string value.
        :param human_readable: Whether properties should be converted to a
        human-readable format or kept as raw values.
        :return: A string generator
        """
        properties = self.get_properties(human_readable)
        for key in self.property_order():
            # Get prevents errors when a certain property is not present.
            # This can happen on cluster jobs.
            value = properties.get(key, "")
            # jsonify containers
            if not isinstance(value, str) and hasattr(value, "__getitem__"):
                yield json.dumps(value)
            else:
                yield str(value)

    def tsv_header(self) -> str:
        return "\t".join(self.property_order()) + '\n'

    def tsv_row(self, human_readable) -> str:
        return "\t".join(self.tsv_properties(human_readable)) + '\n'

    def outputs(self) -> Generator[Path, None, None]:
        """
        A generator of all outputs created by the job.
        """
        for path, folders, files in os.walk(self.execution_folder):
            for file in files:
                if file not in CROMWELL_EXECUTION_FOLDER_RESERVED_FILES:
                    yield Path(path, file)
            for folder in folders:
                yield from get_files_from_dir_recursively(Path(path, folder))

    def inputs(self) -> Generator[Path, None, None]:
        """
        A generator of all inputs used by the job.
        """
        return get_files_from_dir_recursively(self.inputs_folder)

    @staticmethod
    def _sizes_to_human_readable(sizes: Dict[str, int]):
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
    """A Job-type class for jobs that have been locally."""
    def property_order(self) -> List[str]:
        return super().property_order()

    def get_properties(self, human_readable: bool):
        return super().get_properties(human_readable)


DEFAULT_SLURM_JOB_REGEX = re.compile(r"Submitted batch job (\d+).*")

# SLURM uses a base of 1024
# https://github.com/SchedMD/slurm/blob/753db1d52c9bb91f970d83aa9418a6faddf93461/src/common/slurm_protocol_api.c#L3265
SLURM_SUFFIXES = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4,
                  "Kn": 1024, "Mn": 1024**2, "Gn": 1024**3, "Tn": 1024**4}


class SlurmError(Exception):
    pass


class SlurmJob(Job):
    """A Job-type class with functions for querying the SLURM cluster for used
    resources."""
    def __init__(self, path: Path,
                 job_regex: re.Pattern = DEFAULT_SLURM_JOB_REGEX):
        super().__init__(path)
        self._job_regex = job_regex
        self.stdout_submit: Path = self.execution_folder / "stdout.submit"

    @property
    def _time_props(self):
        return ["Timelimit", "Elapsed", "CPUTime", "TotalCPU"]

    @property
    def _size_props(self):
        return ["ReqMem", "MaxRSS", "MaxVMSize", "MaxDiskRead",
                "MaxDiskWrite"]

    def cluster_properties(self) -> List[str]:
        """These values are queried from sacct and reported in this order."""
        return (["State", "NodeList"] + self._time_props + ["ReqCPUS"] +
                self._size_props)

    def property_order(self) -> List[str]:
        super_order = super().property_order()
        # Insert cluster properties after name and exit code.
        return super_order[:2] + self.cluster_properties() + super_order[2:]

    def get_properties(self, human_readable: bool):
        props = super().get_properties(human_readable)
        try:
            props.update(self.get_cluster_accounting())
        except SlurmError:
            # Don't crash if one of the jobs cannot be found.
            # Return basic properties instead.
            return props
        if human_readable:
            for key in self._size_props:
                size = props[key]
                props[key] = naturalsize(size, binary=True)
            for key in self._time_props:
                seconds = props[key]
                props[key] = str(datetime.timedelta(seconds=seconds))
        return props

    def job_id(self) -> str:
        match = self._job_regex.match(self.stdout_submit.read_text())
        if match is None:
            raise ValueError(f"Could not get job id from {self.stdout_submit}")
        return match.group(1)

    def _cluster_account_command(self) -> str:
        # --parsable2 is easiest to parse since it works well with the
        # string.split('|') method.
        args = ("sacct", "-j", self.job_id(), "--parsable2",
                "--format", ",".join(self.cluster_properties()))
        result = subprocess.run(args, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True)

        return result.stdout.decode()

    def get_cluster_accounting(self) -> Dict[str, Union[str, int]]:
        """
        Performs the cluster accounting command and returns a dict of
        properties
        """
        cluster_accounting = self._cluster_account_command()
        lines = cluster_accounting.splitlines(keepends=False)
        headers = lines[0].split("|")
        total_usage = lines[1].split("|")
        if len(lines) > 2:
            batch_usage = lines[2].split("|")
        else:
            raise SlurmError("Job has no batch properties.")
        total_dict = dict(zip(headers, total_usage))
        batch_dict = dict(zip(headers, batch_usage))
        new_dict: Dict[str, Union[str, int]] = {}
        for key in self._size_props:
            new_dict[key] = self.slurm_number(batch_dict.pop(key))
        # Timelimit is not set on the batch job level.
        batch_dict["Timelimit"] = total_dict["Timelimit"]
        for key in self._time_props:
            new_dict[key] = self.slurm_time(batch_dict.pop(key))
        # Add all remaining keys.
        new_dict.update(batch_dict)
        return new_dict

    @staticmethod
    def slurm_number(value: str) -> int:
        """Convert a slurm type number such as 120123K to true bytes."""
        for suffix, multiplier in SLURM_SUFFIXES.items():
            if value.endswith(suffix):
                return round(float(value.rstrip(suffix)) * multiplier)
        return int(value)

    @staticmethod
    def slurm_time(value: str) -> int:
        """Converts a slurm time such as 1-13:32:45 to seconds."""
        if "." in value:
            # When time is smaller than one second format will be:
            # MM:SS.microseconds
            minutes_seconds, microseconds = value.split(".")
            days = 0
            hours = 0
            minutes, seconds = (int(x) for x in minutes_seconds.split(":"))
        else:
            if "-" in value:
                days_time = value.split("-")
                days = int(days_time[0])
                time = days_time[1]
            else:
                days = 0
                time = value
            hours, minutes, seconds = (int(x) for x in time.split(":"))
        return days * 24 * 3600 + hours * 3600 + minutes * 60 + seconds
