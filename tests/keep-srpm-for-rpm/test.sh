#!/bin/bash

# The newer build contains only one RPM (subpackage), while the old bulid
# contains two RPMs.  So one RPM from the newer build obsoletes the build from
# older build, but the second RPM should stay, together with the source RPM.

export testdir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

export origrepo=$testdir/orig-repo
export testrepo=$testdir/repo-test

source $testdir/../testlib.sh

echo "============================ test --cleancopr --days ============================";

setup

persistent_files="
    subdir1/dummy-pkg-blah-1-1.fc34.x86_64.rpm
    subdir1/dummy-pkg-1-1.fc34.src.rpm
    subdir2/dummy-pkg-2-1.fc34.src.rpm
    subdir2/dummy-pkg-2-1.fc34.x86_64.rpm
"

removed_files="
    subdir1/dummy-pkg-1-1.fc34.x86_64.rpm
"

for i in $persistent_files $removed_files; do run "ls $i" || die ; done
runcmd --days 0 .
for i in $persistent_files; do run "ls $i" || die ; done
for i in $removed_files; do run "ls $i" && die;  done

cd ..
setup

cp ../dummy-pkg-blah-2-1.fc34.x86_64.rpm subdir2
createrepo_c .

persistent_files="
    subdir2/dummy-pkg-2-1.fc34.src.rpm
    subdir2/dummy-pkg-2-1.fc34.x86_64.rpm
    subdir2/dummy-pkg-blah-2-1.fc34.x86_64.rpm
"

removed_files="
    subdir1/dummy-pkg-1-1.fc34.src.rpm
    subdir1/dummy-pkg-1-1.fc34.x86_64.rpm
    subdir1/dummy-pkg-blah-1-1.fc34.x86_64.rpm
"

for i in $persistent_files $removed_files; do run "ls $i" || die ; done
runcmd --days 0 .
for i in $persistent_files; do run "ls $i" || die ; done
for i in $removed_files; do run "ls $i" && die;  done

echo success.

exit 0
