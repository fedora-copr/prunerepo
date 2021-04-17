#!/usr/bin/python3

""" /usr/bin/prunerepo script """

import argparse

from prunerepo.helpers import (
        prune_packages,
        recreate_repo,
        clean_copr,
        get_logger,
)


def _get_parser():
    parser = argparse.ArgumentParser(
        description='Remove old packages from rpm-md repository')
    parser.add_argument(
        'path', action='store',
        help='local path to a yum repository')
    parser.add_argument(
        '--days', type=int, action='store', default=0,
        help="Only remove packages (and build directories when --cleancopr is "
             "used) that are DAYS old or older (for packages by their build "
             "date, for directories the last modification time is considered"
    )
    parser.add_argument(
        '--cleancopr', action='store_true',
        help="additionaly remove whole copr build dirs and "
             "logs if the associated package gets deleted")
    parser.add_argument(
        '--alwayscreaterepo', action='store_true',
        help='Recreate repository even when there was no change in data.')
    parser.add_argument(
        '--nocreaterepo', action='store_true',
        help="repository is not automatically recreated (not even after data "
             "deletion).  Supresses --alwayscreaterepo.")
    parser.add_argument(
        '--log-level', type=str, default='INFO',
        help='set logging to desired level')
    parser.add_argument(
        '--dry-run', action='store_true',
        help='do not remove anything from the repository and print the actions instead. '
             'Verbose mode will be set.')
    parser.add_argument('-v', '--version', action='version', version='1.5',
                        help='print program version and exit')

    args = parser.parse_args()
    if args.dry_run:
        args.log_level = 'DEBUG'
    return args


def main():
    """ entrypoint """
    args = _get_parser()
    log = get_logger(args.log_level)

    was_deletion = prune_packages(args.path, args.days, args.dry_run, log)
    if (was_deletion or args.alwayscreaterepo) and not args.nocreaterepo:
        recreate_repo(args.path, args.dry_run, log)

    if args.cleancopr:
        clean_copr(args.path, args.days, args.dry_run, log)


if __name__ == "__main__":
    main()
