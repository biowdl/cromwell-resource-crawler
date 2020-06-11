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
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, Optional, Type

from .jobs import Job, LocalJob, SlurmJob

DEFAULT_OUTPUT = "/dev/stdout" if sys.platform in ["linux", "darwin"] else None


def crawl_folder(folder: Path, jobclass: Type[Job] = LocalJob
                  ) -> Generator[Job, None, None]:
    if folder.name == "cacheCopy":
        # cacheCopy folders are not executed and do not contain the files to
        # calculate resource requirements
        return
    elif Path(folder, "execution").exists():
        yield jobclass(folder)
        for folder in folder.iterdir():
            if folder.name.startswith("attempt-"):
                yield jobclass(folder)
    else:
        for dir_entry in os.scandir(folder):  # type: os.DirEntry
            if dir_entry.is_dir():
                yield from crawl_folder(Path(folder, dir_entry.name))


def jobs_to_json_dict(jobs: Iterable[Job],
                      start_path: Optional[Path] = None,
                      human_readable: bool = True) -> Dict:
    json_dict: Dict[str, Any] = {}
    for job in jobs:
        job_path = (job.path if start_path is None
                    else job.path.relative_to(start_path))
        part_dict = json_dict
        for part in job_path.parts[:-1]:
            if part not in part_dict:
                part_dict[part] = {}
            part_dict = part_dict[part]
        part_dict[job_path.parts[-1]] = job.to_json(human_readable)
    return json_dict


def jobs_to_tsv(jobs: Iterable[Job], human_readable: bool = True
                ) -> Generator[str, None, None]:
    job_iter = iter(jobs)
    try:
        first_job = next(job_iter)
    except StopIteration:
        return
    yield first_job.tsv_header()
    yield first_job.tsv_row(human_readable)
    for job in job_iter:
        yield job.tsv_row(human_readable)


JOBS_DICT = dict(slurm=SlurmJob, local=LocalJob)


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("workflow_dir", type=str,
                        help="Workflow directory. Such as "
                             "cromwell-executions/WORKFLOW_DIR.")
    parser.add_argument("-b", "--backend", type=str, choices=JOBS_DICT.keys(),
                        default="local",
                        help="Which backend the jobs have been running on. "
                             "This determines how the resource usages are "
                             "acquired.")
    parser.add_argument("-f", "--format", type=str,
                        choices=["json", "tsv"], default="tsv")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT,
                        required=not bool(DEFAULT_OUTPUT),
                        help=f"Output file to use. Default: "
                             f"{str(DEFAULT_OUTPUT)}.")
    parser.add_argument("-n", "--name", required=False,
                        help="Select only jobs named 'call-NAME'.")
    parser.add_argument("-F", "--filter", metavar="STRING",
                        help="Select only jobs where STRING is part of the "
                             "path.")
    parser.add_argument("-r", "--raw", action="store_true",
                        help="Output in bytes and seconds instead of human "
                             "readable numbers.")
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
        if args.format == "json":
            json.dump(jobs_to_json_dict(jobs, workflow_folder, not args.raw
                                        ), output_h)
        elif args.format == "tsv":
            for line in jobs_to_tsv(jobs, not args.raw):
                output_h.write(line)


if __name__ == "__main__":
    main()
