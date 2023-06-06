#!/usr/bin/python3

"""
Set of helper methods for the /usr/bin/prunerepo command.  These methods are not
supposed to be library calls so please never import anything from this file.
"""

import subprocess
import sys
import os
import re
import time
import shutil
import logging
import tempfile

from prunerepo.pair_srpm_rpm import PruneRepoAnalyzer


class PrunerepoException(Exception):
    """ Returned upon failure """


def is_srpm(package):
    """ Check if the PACKAGE string ends with src.rpm """
    return package.endswith(".src.rpm")


def rm_file(path, dry_run, log):
    """
    Remove file given its absolute path
    """
    log.info("Removing: " + path)
    if dry_run:
        return
    if os.path.exists(path) and os.path.isfile(path):
        os.remove(path)


def run_cmd(cmd, log, dry_run=False):
    """
    Run given command in a subprocess
    """
    str_cmd = ' '.join(cmd)
    log.debug("Executing: %s", str_cmd)
    if dry_run:
        return []
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (stdout, stderr) = process.communicate()
    err_output = stderr.decode(encoding='utf-8')
    if err_output:
        log.debug("Command error output: %s", err_output)

    if process.returncode != 0:
        raise PrunerepoException("Command {} failed".format(str_cmd))
    return stdout.decode(encoding='utf-8').splitlines()


def get_rpms(repoquery_cmd, log):
    """
    Get paths to rpm packages in the repository according to given repoquery_cmd
    """
    stdout = run_cmd(repoquery_cmd, log)  # returns srpms as well

    # List in a format:
    # file:///some/path/python3-motionpaint-1.4-1.fc23.noarch.rpm
    rpm_paths = [path for path in stdout if not is_srpm(path)]
    abs_rpm_paths = []
    for path in rpm_paths:
        prefix = "file://"
        if not path.startswith(prefix):
            raise PrunerepoException(
                f"Repoquery output doesn't start with file:// - {path}"
            )
        abs_path = path[len(prefix):]
        if not abs_path.startswith("/"):
            raise PrunerepoException(
                f"Repoquery output doesn't provide absolute path: {path}"
            )
        abs_rpm_paths.append(abs_path)

    return abs_rpm_paths


def prune_packages(path, days, dry_run, log):
    """
    Remove obsoleted packages
    """
    log.debug('Removing obsoleted packages...')
    rpms = get_rpms_to_remove(path, days, log)
    was_deletion = False
    if not rpms:
        log.error("No outdated RPMs for removal.")
        return was_deletion
    for rpm in rpms:
        remove = os.path.abspath(os.path.join(path, rpm))
        rm_file(remove, dry_run, log)
        was_deletion = True
    return was_deletion


def recreate_repo(path, dry_run, log):
    """
    Recreate the repository by using createrepo_c
    """
    log.debug("Recreating repository...")
    createrepo_cmd = ['/usr/bin/createrepo_c', '--database', '--update', '--local-sqlite',
                      '--cachedir', '/tmp/', '--workers', '8'] + [path]
    return run_cmd(createrepo_cmd, log, dry_run)


def clean_copr(path, days, dry_run, log):
    """
    Remove whole copr build dirs if they no longer contain a srpm/rpm file
    """
    log.info("This feature is deprecated and will be removed in a future release. "
             "Please, use a custom solution instead.")
    log.info("Cleaning COPR repository...")
    for dir_name in os.listdir(path):
        dir_path = os.path.abspath(os.path.join(path, dir_name))

        if not os.path.isdir(dir_path):
            continue
        if not os.path.isfile(os.path.join(dir_path, 'build.info')):
            continue
        if [item for item in os.listdir(dir_path) if re.match(r'.*\.rpm$', item)]:
            continue
        if time.time() - os.stat(dir_path).st_mtime <= days * 24 * 3600:
            continue

        log.info('Removing: ' + dir_path)
        if not dry_run:
            shutil.rmtree(dir_path)

        # also remove the associated log in the main dir
        build_id = os.path.basename(dir_path).split('-')[0]
        buildlog_name = 'build-' + build_id + '.log'
        buildlog_path = os.path.abspath(os.path.join(path, buildlog_name))
        rm_file(os.path.join(path, buildlog_path), dry_run, log)


def get_logger(log_level="INFO", module=None):
    """
    Set logging level
    """
    log = logging.getLogger(module or __name__)
    if log.handlers:
        # repeated call
        return log

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.setLevel(log_level.upper())
    log.addHandler(handler)
    log.setLevel(handler.level)
    return log


def get_rpms_to_remove(directory, days=0, log=None):
    """
    Returns a list of (s)rpm path names that should be removed.
    0 days means that (s)rpm will be removed regardless of when the package was built.

    :param directory: local path to a yum repository
    :param days: how old are the packages to be removed, in the number of days
    :param log: logger to use, if not specified an INFO stderr logger is created
    :return: a list of (s)RPM path names that should be removed
    :raises PrunerepoException: Upon any failure that could provide bad results
        causing unwanted RPM removals.
    """

    with tempfile.TemporaryDirectory(prefix="prunerepo-dnf-cache") as cachedir:
        return _get_rpms_to_remove_internal(directory, days, log, cachedir)


def _get_rpms_to_remove_internal(directory, days, log, cachedir):
    get_all_packages_cmd = [
        "dnf-3",
        "repoquery",
        "--repofrompath=prunerepo_query," + os.path.abspath(directory),
        "--repo=prunerepo_query",
        "--refresh",
        "--location",
        "--quiet",
        "--setopt=skip_if_unavailable=False",
        f"--setopt=cachedir={cachedir}",
    ]

    if not log:
        log = get_logger()

    log.info("Checking '%s' repo for removal candidates older than %s days",
             os.path.abspath(directory), days)

    get_latest_packages_cmd = get_all_packages_cmd + ['--latest-limit=1']
    latest_rpms = get_rpms(get_latest_packages_cmd, log)
    if not latest_rpms:
        return []

    all_rpms = get_rpms(get_all_packages_cmd, log)

    repodir = os.path.abspath(directory)
    repo_analyzer = PruneRepoAnalyzer(repodir, log)

    to_remove_rpms = set(all_rpms) - set(latest_rpms)
    rpm_list = []

    time_now = time.time()
    for rpm in to_remove_rpms:
        log.debug("Checking age of the '%s' file", os.path.split(rpm)[1])
        rel_rpm = os.path.normpath(os.path.relpath(rpm, repodir))
        if time_now - repo_analyzer.get_build_time(rel_rpm) < days * 24 * 3600:
            continue

        rpm_list.append(rel_rpm)

        rel_srpm = repo_analyzer.srpm_to_be_removed_for_rpm(rel_rpm)
        if not rel_srpm:
            continue
        rpm_list.append(rel_srpm)

    return rpm_list
