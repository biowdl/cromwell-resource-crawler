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
import sys
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, Optional, Type

from .jobs import Job, LocalJob, SlurmJob

DEFAULT_OUTPUT = "/dev/stdout" if sys.platform in ["linux", "darwin"] else None


def is_uuid_folder(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    parts = folder.name.split("-")
    if not len(parts) == 5:
        return False
    if not [len(part) for part in parts] == [8, 4, 4, 4, 12]:
        return False
    # Each part is a hexadecimal number
    for part in parts:
        try:
            int(part, 16)
        except ValueError:
            return False
    return True


def crawl_folder(folder: Path, jobclass: Type[Job] = LocalJob
                 ) -> Generator[Job, None, None]:
    if not folder.is_dir():
        raise ValueError(f"{folder} is not a directory!")
    if folder.name == "cromwell-executions":
        for path in folder.iterdir():
            if not path.is_dir():
                continue
            if "-" not in path.name:
                yield from crawl_workflow_folder(path, jobclass)
    elif folder.name.startswith("call-"):
        yield from crawl_call_folder(folder, jobclass)
    elif Path(folder, "execution").exists():  # catches shard-X and attempt-X
        yield from crawl_call_folder(folder, jobclass)
    elif folder.name.startswith("shard-"):  # for shards with workflows
        for path in folder.iterdir():
            yield from crawl_workflow_folder(path)
    elif is_uuid_folder(folder):
        yield from crawl_uuid_folder(folder, jobclass)
    else:
        yield from crawl_workflow_folder(folder, jobclass)


def crawl_workflow_folder(workflow_folder: Path, jobclass: Type[Job] = LocalJob
                          ) -> Generator[Job, None, None]:
    for uuid_folder in workflow_folder.iterdir():
        yield from crawl_uuid_folder(uuid_folder, jobclass=jobclass)


def crawl_uuid_folder(uuid_folder: Path, jobclass: Type[Job] = LocalJob
                      ) -> Generator[Job, None, None]:
    for call_folder in uuid_folder.iterdir():
        yield from crawl_call_folder(call_folder, jobclass)


def crawl_call_folder(call_folder: Path, jobclass: Type[Job] = LocalJob
                      ) -> Generator[Job, None, None]:
    if Path(call_folder, "execution").exists():
        yield jobclass(call_folder)
        for folder in call_folder.iterdir():
            if folder.name.startswith("attempt-"):
                yield jobclass(folder)
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
                        default="local",
                        help="Which backend the jobs have been running on. "
                             "This determines how the resource usages are "
                             "acquired.")
    parser.add_argument("-f", "--output-format", type=str,
                        choices=["json", "tsv"], default="tsv")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT,
                        required=not bool(DEFAULT_OUTPUT),
                        help=f"Output file to use. Default: "
                             f"{str(DEFAULT_OUTPUT)}.")
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
