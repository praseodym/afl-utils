"""
Copyright 2015 @_rc0r <hlt99@blinkenshell.org>

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import argparse
import os
import shutil
import subprocess
import sys

import afl_utils
from afl_utils import SampleIndex, afl_collect, afl_vcrash


def show_info():
    print("afl-minimize %s by %s" % (afl_utils.__version__, afl_utils.__author__))
    print("Corpus minimization utility for afl-fuzz corpora.")
    print("")


def invoke_cmin(input_dir, output_dir, target_cmd):
    success = True
    cmd = "afl-cmin -i %s -o %s -- %s" % (input_dir, output_dir, target_cmd)
    try:
        subprocess.check_call(cmd, shell=True)
    except subprocess.CalledProcessError as e:
        print("afl-cmin failed with exit code %d!" % e.returncode)
        success = False
    return success


def invoke_tmin(input_files, output_dir, target_cmd):
    num_samples = 0
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    for f in input_files:
        cmd = "afl-tmin -i %s -o %s -- %s" % (f, os.path.join(output_dir, os.path.basename(f)), target_cmd)
        try:
            subprocess.check_call(cmd, shell=True)
            num_samples += 1
        except subprocess.CalledProcessError as e:
            print("afl-tmin failed with exit code %d!" % e.returncode)
    return num_samples


def invoke_dryrun(input_files, crash_dir, target_cmd):
    # TODO: handle timeouts, if possible
    invalid_samples = afl_vcrash.verify_samples(1, input_files, target_cmd)

    invalid_sample_set = set(invalid_samples)
    input_sample_set = set(input_files)

    crashes_set = input_sample_set - invalid_sample_set
    crashes = list(crashes_set)

    if len(crashes) > 0:
        if not os.path.exists(crash_dir):
            os.makedirs(crash_dir, exist_ok=True)

        for c in crashes:
            shutil.move(c, os.path.join(crash_dir, os.path.basename(c)))

    print("Moved %d crash samples from the corpus to %s." % (len(crashes), crash_dir))
    return


def main(argv):
    show_info()

    parser = argparse.ArgumentParser(description="afl-minimize performs several optimization steps to reduce the size\n \
of an afl-fuzz corpus.",
                                     usage="afl-minimize [-c COLLECTION_DIR [--cmin] [--tmin]] [-d] [-h] sync_dir -- \
target_cmd\n")

    parser.add_argument("-c", "--collect", dest="collection_dir",
                        help="Collect all samples from the synchronisation dir and store them in the collection dir. \
Existing files in the collection directory will be overwritten!", default=None)
    parser.add_argument("--cmin", dest="invoke_cmin", action="store_const", const=True,
                        default=False, help="Run afl-cmin on collection dir. Has no effect without '-c'.")
    parser.add_argument("--tmin", dest="invoke_tmin", action="store_const", const=True,
                        default=False, help="Run afl-tmin on minimized collection dir if used together with '--cmin'\
or on unoptimized collection dir otherwise. Has no effect without '-c'.")
    parser.add_argument("-d", "--dry-run", dest="dry_run", action="store_const", const=True,
                        default=False, help="Perform dry-run on collection dir, if '-c' is provided or on \
synchronisation dir otherwise. Dry-run will move intermittent crashes out of the corpus.")
    parser.add_argument("sync_dir", help="afl synchronisation directory containing multiple fuzzers and their queues.")
    parser.add_argument("target_cmd", nargs="+", help="Path to the target binary and its command line arguments. \
Use '@@' to specify crash sample input file position (see afl-fuzz usage).")

    args = parser.parse_args(argv[1:])

    if not args.collection_dir and not args.dry_run:
        print("No operation requested. You should at least provide '-c'\nfor sample collection or '-d' for a dry-run. \
Use '--help' for\nusage instructions or checkout README.md for details.")
        return

    sync_dir = os.path.abspath(os.path.expanduser(args.sync_dir))
    if not os.path.exists(sync_dir):
        print("No valid directory provided for <SYNC_DIR>!")
        return

    args.target_cmd = " ".join(args.target_cmd).split()
    args.target_cmd[0] = os.path.abspath(os.path.expanduser(args.target_cmd[0]))
    if not os.path.exists(args.target_cmd[0]):
        print("Target binary not found!")
        return
    args.target_cmd = " ".join(args.target_cmd)

    print("Looking for fuzzing queues in '%s'." % sync_dir)
    fuzzers = afl_collect.get_fuzzer_instances(sync_dir, crash_dirs=False)

    if args.collection_dir:
        out_dir = os.path.abspath(os.path.expanduser(args.collection_dir))
        if not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)

        # collect samples from fuzzer queues
        print("Found %d fuzzers, collecting samples." % len(fuzzers))
        sample_index = afl_collect.build_sample_index(sync_dir, out_dir, fuzzers)

        print("Successfully indexed %d samples." % len(sample_index.index))
        print("Copying %d samples into collection directory..." % len(sample_index.index))
        afl_collect.copy_samples(sample_index)

        if args.invoke_cmin:
            # invoke cmin on collection
            print("Executing: afl-cmin -i %s -o %s.cmin -- %s" % (out_dir, out_dir, args.target_cmd))
            invoke_cmin(out_dir, "%s.cmin" % out_dir, args.target_cmd)
            if args.invoke_tmin:
                # invoke tmin on minimized collection
                print("Executing: afl-tmin -i %s.cmin/* -o %s.cmin.tmin/* -- %s" % (out_dir, out_dir, args.target_cmd))
                tmin_num_samples, tmin_samples = afl_collect.get_samples_from_dir("%s.cmin" % out_dir, abs_path=True)
                tmin_num_samples_processed = invoke_tmin(tmin_samples, "%s.cmin.tmin" % out_dir, args.target_cmd)
        elif args.invoke_tmin:
            # invoke tmin on collection
            print("Executing: afl-tmin -i %s/* -o %s.tmin/* -- %s" % (out_dir, out_dir, args.target_cmd))
            tmin_num_samples, tmin_samples = afl_collect.get_samples_from_dir(out_dir, abs_path=True)
            tmin_num_samples_processed = invoke_tmin(tmin_samples, "%s.tmin" % out_dir, args.target_cmd)
        if args.dry_run:
            # invoke dry-run on collected/minimized corpus
            if args.invoke_cmin and args.invoke_tmin:
                print("Performing dry-run in %s.cmin.tmin..." % out_dir)
                print("Be patient! Depending on the corpus size this step can take hours...")
                dryrun_num_samples, dryrun_samples = afl_collect.get_samples_from_dir("%s.cmin.tmin" % out_dir, abs_path=True)
                invoke_dryrun(dryrun_samples, "%s.cmin.tmin.crashes" % out_dir, args.target_cmd)
            elif args.invoke_cmin:
                print("Performing dry-run in %s.cmin..." % out_dir)
                print("Be patient! Depending on the corpus size this step can take hours...")
                dryrun_num_samples, dryrun_samples = afl_collect.get_samples_from_dir("%s.cmin" % out_dir, abs_path=True)
                invoke_dryrun(dryrun_samples, "%s.cmin.crashes" % out_dir, args.target_cmd)
            elif args.invoke_tmin:
                print("Performing dry-run in %s.tmin..." % out_dir)
                print("Be patient! Depending on the corpus size this step can take hours...")
                dryrun_num_samples, dryrun_samples = afl_collect.get_samples_from_dir("%s.tmin" % out_dir, abs_path=True)
                invoke_dryrun(dryrun_samples, "%s.tmin.crashes" % out_dir, args.target_cmd)
            else:
                print("Performing dry-run in %s..." % out_dir)
                print("Be patient! Depending on the corpus size this step can take hours...")
                dryrun_num_samples, dryrun_samples = afl_collect.get_samples_from_dir(out_dir, abs_path=True)
                invoke_dryrun(dryrun_samples, out_dir, args.target_cmd)
    else:
        if args.dry_run:
            print("Found %d fuzzers, performing dry run." % len(fuzzers))
            print("Be patient! Depending on the corpus size this step can take hours...")
            # invoke dry-run on original corpus
            for f in fuzzers:
                for q_dir in f[1]:
                    q_dir_complete = os.path.join(sync_dir, f[0], q_dir)
                    print("Processing %s..." % q_dir_complete)

                    dryrun_num_samples, dryrun_samples = afl_collect.get_samples_from_dir(q_dir_complete, abs_path=True)
                    invoke_dryrun(dryrun_samples, os.path.join(sync_dir, f[0], "crashes"), args.target_cmd)


if __name__ == "__main__":
    main(sys.argv)
