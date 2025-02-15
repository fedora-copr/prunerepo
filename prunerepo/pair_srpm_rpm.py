#! /usr/bin/python3

"""
When source RPM and the corresponding binary RPMs are put in the same result
directory, this script is able to parse the repository metadata and pair the
existing source RPM with set of binary RPMs.  Per discussion in:
https://pagure.io/prunerepo/issue/7
https://github.com/praiskup/dnf-hacks/blob/main/find-srpm-to-rpm-pairs.py
"""

import re
import os
from contextlib import contextmanager


try:
    import libdnf5
    DNF5_USED = True
except ImportError:
    # We can not import both, if we do - dnf query mechanism behaves
    # differently.
    DNF5_USED = False
    import dnf


def url_to_repoid(repo_url):
    """
    Taken from: https://pagure.io/copr/copr/blob/\
                0ea325a9249fd4570e2d380f30432ff8f90290e8/f/\
                frontend/coprs_frontend/coprs/helpers.py#_477-482
    """
    repo_url = re.sub("[^a-zA-Z0-9]", '_', repo_url)
    repo_url = re.sub("(__*)", '_', repo_url)
    repo_url = re.sub("(_*$)|^_*", '', repo_url)
    return repo_url


@contextmanager
def _get_dnf5_query(repo, cachedir, log):
    """
    Prepare and yield a prepared DNF5 query object pre-configured to work with
    the given REPO.  Make sure you run this in `with` context.
    """
    base = libdnf5.base.Base()
    base_config = base.get_config()
    base_config.plugins = False
    base_config.cachedir = cachedir
    base.load_config()
    base.setup()

    repo_sack = base.get_repo_sack()
    repo_obj = repo_sack.create_repo(url_to_repoid(repo))
    repo_obj.get_config().baseurl = repo
    repo_sack.load_repos(libdnf5.repo.Repo.Type_AVAILABLE)
    query = libdnf5.rpm.PackageQuery(base)
    try:
        yield query
    finally:
        pass

@contextmanager
def _get_dnf_query(repo, cachedir, log):
    """
    Prepare and yield a prepared DNF4 query object pre-configured to work with
    the given REPO.  Make sure you run this in `with` context.
    """
    base = dnf.Base()
    base.conf.cachedir = cachedir
    base.read_all_repos()

    # disable all pre-configured repos
    base.repos.get_matching('*').disable()

    found = 0
    reponame = url_to_repoid(repo)
    log.debug("Using repo ID %s => %s", reponame, repo)
    found += 1
    base.repos.add_new_repo(
        reponame,
        base.conf,
        baseurl=(repo,),
        metadata_expire=1,
        module_hotfixes=1,
    )

    # read the metadata
    base.fill_sack()
    try:
        query = base.sack.query()
        remote = query.filter(reponame__neq="@System")
        yield remote
    finally:
        base.close()


def _get_mapping(repo, cachedir, log):
    """
    Read the repository metadata and find what RPMs were built from which SRPMs,
    and map the source RPM name to SRPMs and vice versa.
    """
    get_query = _get_dnf5_query if DNF5_USED else _get_dnf_query
    with get_query(repo, cachedir, log) as query:
        available_packages = [_Pkg(p) for p in query]
        return _available_pkgs_to_mapping(available_packages, log)


class _Pkg:
    """
    Make the Package backward compatible with DNF4.  Remove once we have no
    DNF4 support (RHEL11+).
    """
    def __init__(self, pkg):
        self.pkg = pkg
    def __getattr__(self, attr):
        try:
            return getattr(self.pkg, attr)
        except AttributeError:
            if attr == "get_build_time":
                # get_build_time() was buildtime in DNF4
                return lambda: self.pkg.buildtime
            attr = attr[4:]
            return lambda: getattr(self.pkg, attr)


def _available_pkgs_to_mapping(available_packages, log):
    found_srpms = set()
    map_srpm_to_rpms = {}
    map_rpm_to_srpm = {}
    map_rpm_to_buildtime = {}

    # list all packages
    for package in available_packages:
        # remove leading ./ etc.
        normalized_pkg_path = os.path.normpath(package.get_location())

        map_rpm_to_buildtime[normalized_pkg_path] = package.get_build_time()

        if package.get_sourcerpm():
            # handling source RPMs only for now
            continue

        # handling source RPM
        found_srpms.add(normalized_pkg_path)

    # group the binary RPMs
    for package in available_packages:
        if not package.get_sourcerpm():
            continue  # only binary RPMs now..

        dirname = os.path.dirname(os.path.normpath(package.get_location()))
        expected_source_rpm = os.path.normpath(
                os.path.join(dirname, package.get_sourcerpm()))

        if not expected_source_rpm:
            log.error("%s has no SRPM header", package.get_location())
            continue

        if expected_source_rpm not in found_srpms:
            log.error("%s has no source RPM in the directory",
                      package.get_location())
            continue

        if not expected_source_rpm in map_srpm_to_rpms:
            map_srpm_to_rpms[expected_source_rpm] = set()

        rpm = os.path.normpath(package.get_location())
        map_srpm_to_rpms[expected_source_rpm].add(rpm)
        map_rpm_to_srpm[rpm] = expected_source_rpm

    return map_srpm_to_rpms, map_rpm_to_srpm, map_rpm_to_buildtime


class PruneRepoAnalyzer:  # pylint: disable=too-few-public-methods
    """
    Search/query MAP of "SRPM => RPMS", "RPM => SRPM", and "(S)RPM =>
    buildtime".  The paths we work with, and return are relative to the "repo"
    directory we get in the constructor.
    """

    def __init__(self, repo, cachedir, log):
        self.log = log
        self.repo = repo
        self.srpm_map, self.rpm_map, self.buildtime_map = _get_mapping(
                repo, cachedir, log)

    def srpm_to_be_removed_for_rpm(self, rpm):
        """
        Detect if we should remove also the SRPM for the given RPM.  We don't
        remove SRPM as long as there's at least one binary RPM (sub-package)
        generated from SRPM.  So, when we aim to remove an RPM, we call this
        method to check if it is the last RPM generated from the corresponding
        SRPM, and if yes - we return the relative path of SRPM.  So when we
        return string (not None), the SRPM should be removed.
        """
        rpm = os.path.normpath(rpm)
        if rpm not in self.rpm_map:
            return None

        srpm = self.rpm_map[rpm]
        self.log.debug("removing %s from set of RPMs in %s", rpm, srpm)

        # Drop the reference to RPM, as it is being removed.
        self.srpm_map[srpm].remove(rpm)

        if self.srpm_map[srpm]:
            # some RPM(s) still exist for the SRPM, we can't remove the SRPM
            return None

        # Return non-None value, to notify caller that the SRPM should be
        # removed.
        return srpm

    def get_build_time(self, rpm):
        """
        Get the BUILDTIME stored in RPM, per previous repository analysis.
        """
        return self.buildtime_map[rpm]
