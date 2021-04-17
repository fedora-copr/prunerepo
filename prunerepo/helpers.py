#!/usr/bin/python3

import subprocess
import sys
import os
import re
import time
import shutil
import logging

from prunerepo.pair_srpm_rpm import RPMToSRPMPairs


def is_srpm(package):
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
    log.debug("Executing: " + ' '.join(cmd))
    if dry_run:
        return []
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (stdout, stderr) = process.communicate()
    sys.stderr.write(stderr.decode(encoding='utf-8'))
    if process.returncode != 0:
        sys.exit(1)
    return stdout.decode(encoding='utf-8').splitlines()


def get_package_build_time(package_path, log):
    """
    Get build time by reading package metadata
    """
    query_cmd = ["/usr/bin/rpm", "-qp", "--queryformat", "%{BUILDTIME}"] + [package_path]
    stdout = run_cmd(query_cmd, log)
    return int(stdout[0])


def get_rpms(repoquery_cmd, path, log):
    """
    Get paths to rpm packages in the repository according to given repoquery_cmd
    """
    stdout = run_cmd(repoquery_cmd, log)  # returns srpms as well
    rel_rpms_paths = [relpath for relpath in stdout if not is_srpm(relpath)]
    abs_rpms_paths = [os.path.abspath(os.path.join(path, relpath)) for relpath in rel_rpms_paths]
    return abs_rpms_paths


def prune_packages(path, days, dry_run, log):
    """
    Remove obsoleted packages
    """
    log.debug('Removing obsoleted packages...')
    rpms = get_rpms_to_remove(path, days, log)
    was_deletion = False
    if not rpms:
        log.error("No RPMs available")
        return was_deletion
    for rpm in rpms:
        rm_file(rpm, dry_run, log)
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
    """
    get_all_packages_cmd = [
        "dnf",
        "repoquery",
        "--repofrompath=prunerepo_query," + os.path.abspath(directory),
        "--repo=prunerepo_query",
        "--refresh",
        "--queryformat=%{location}",
        "--quiet",
        "--setopt=skip_if_unavailable=False",
    ]

    if not log:
        log = get_logger()

    log.info("Checking '%s' repo for removal candidates older than %s days",
             os.path.abspath(directory), days)

    get_latest_packages_cmd = get_all_packages_cmd + ['--latest-limit=1']
    latest_rpms = get_rpms(get_latest_packages_cmd, directory, log)
    if not latest_rpms:
        return []

    all_rpms = get_rpms(get_all_packages_cmd, directory, log)

    repodir = os.path.abspath(directory)
    pair_lookup = RPMToSRPMPairs(repodir, log)

    to_remove_rpms = set(all_rpms) - set(latest_rpms)
    rpm_list = []
    for rpm in to_remove_rpms:
        log.debug("Checking age of the '%s' file", os.path.split(rpm)[1])
        if time.time() - get_package_build_time(rpm, log) < days * 24 * 3600:
            continue
        rpm_list.append(rpm)

        rel_rpm = os.path.normpath(os.path.relpath(rpm, repodir))
        rel_srpm = pair_lookup.srpm_to_be_removed_for_rpm(rel_rpm)
        if not rel_srpm:
            continue
        rpm_list.append(os.path.join(repodir, rel_srpm))

    return rpm_list
