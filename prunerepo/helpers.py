#!/usr/bin/python3

import subprocess
import sys
import os
import re
import time
import shutil
import logging

log = logging.getLogger(__name__)


def is_srpm(package):
    return package.endswith(".src.rpm")


def rm_file(path, dry_run):
    """
    Remove file given its absolute path
    """
    log.info("Removing: " + path)
    if dry_run:
        return
    if os.path.exists(path) and os.path.isfile(path):
        os.remove(path)


def run_cmd(cmd, dry_run):
    """
    Run given command in a subprocess
    """
    log.debug("Executing: " + ' '.join(cmd))
    if dry_run:
        return
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (stdout, stderr) = process.communicate()
    sys.stderr.write(stderr.decode(encoding='utf-8'))
    if process.returncode != 0:
        sys.exit(1)
    return stdout.decode(encoding='utf-8').splitlines()


def get_package_build_time(package_path, dry_run):
    """
    Get build time by reading package metadata
    """
    query_cmd = ["/usr/bin/rpm", "-qp", "--queryformat", "%{BUILDTIME}"] + [package_path]
    stdout = run_cmd(query_cmd, dry_run)
    return int(stdout[0])


def get_rpms(repoquery_cmd, path, dry_run):
    """
    Get paths to rpm packages in the repository according to given repoquery_cmd
    """
    stdout = run_cmd(repoquery_cmd, dry_run)  # returns srpms as well
    rel_rpms_paths = [relpath for relpath in stdout if not is_srpm(relpath)]
    abs_rpms_paths = [os.path.abspath(os.path.join(path, relpath)) for relpath in rel_rpms_paths]
    return abs_rpms_paths


def get_srpm(rpm, get_all_packages_cmd, dry_run):
    """
    Get matching srpm in the same directory as given rpm (described by its absolute path)
    """
    get_srpm_cmd = get_all_packages_cmd + ["--srpm", os.path.splitext(os.path.basename(rpm))[0]]
    output = run_cmd(get_srpm_cmd, dry_run)
    if not output:
        return

    srpm_name = os.path.basename(output[0])
    srpm_path = os.path.abspath(os.path.join(os.path.dirname(rpm), srpm_name))
    return srpm_path


def prune_packages(path, days, log_level, dry_run):
    """
    Remove obsoleted packages
    """
    if not set_logging_level(log_level):
        sys.exit(1)
    log.debug('Removing obsoleted packages...')
    rpms = get_rpms_to_remove(path, log_level, days)
    was_deletion = False
    if not rpms:
        log.error("No RPMs available")
        return was_deletion
    for rpm in rpms:
        rm_file(rpm, dry_run)
        was_deletion = True
    return was_deletion


def recreate_repo(path, dry_run):
    """
    Recreate the repository by using createrepo_c
    """
    log.debug("Recreating repository...")
    createrepo_cmd = ['/usr/bin/createrepo_c', '--database', '--update', '--local-sqlite',
                      '--cachedir', '/tmp/', '--workers', '8'] + [path]
    return run_cmd(createrepo_cmd, dry_run)


def clean_copr(path, days, dry_run):
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
        shutil.rmtree(dir_path)

        # also remove the associated log in the main dir
        build_id = os.path.basename(dir_path).split('-')[0]
        buildlog_name = 'build-' + build_id + '.log'
        buildlog_path = os.path.abspath(os.path.join(path, buildlog_name))
        rm_file(os.path.join(path, buildlog_path), dry_run)


def set_logging_level(log_level):
    """
    Set logging level
    """
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    try:
        handler.setLevel(log_level.upper())
        log.addHandler(handler)
        log.setLevel(handler.level)
        return True
    except ValueError as error:
        print(str(error), file=sys.stderr)
    except TypeError as error:
        print(str(error), file=sys.stderr)
    return False


def get_rpms_to_remove(directory, log_level='INFO', days=0):
    """
    Returns a list of (s)rpm path names that should be removed.
    0 days means that (s)rpm will be removed regardless of when the package was built.

    :param directory: local path to a yum repository
    :param log_level: set logging to desired level (error, info or debug)
    :param days: how old are the packages to be removed, in the number of days
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
    if not log.handlers:
        if not set_logging_level(log_level):
            return []
    log.info("Checking '%s' directory for removal candidates older than %s days" % (os.path.abspath(directory), days))
    get_latest_packages_cmd = get_all_packages_cmd + ['--latest-limit=1']
    latest_rpms = get_rpms(get_latest_packages_cmd, directory, dry_run=False)
    if not latest_rpms:
        return []
    all_rpms = get_rpms(get_all_packages_cmd, directory, dry_run=False)
    to_remove_rpms = set(all_rpms) - set(latest_rpms)
    rpm_list = []
    for rpm in to_remove_rpms:
        log.debug("Checking age of the '%s' file" % os.path.split(rpm)[1])
        if time.time() - get_package_build_time(rpm, dry_run=False) > days * 24 * 3600:
            srpm = get_srpm(rpm, get_all_packages_cmd, dry_run=False)
            if srpm:
                rpm_list.append(srpm)
            rpm_list.append(rpm)
    return rpm_list
