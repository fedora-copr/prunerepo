export libdir="$(builtin cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd)"
export PYTHONPATH="$libdir/../"

die() {
	echo "fail."; exit 1; 
}

function runcmd {
	python3 "$libdir/../prunerepo/main.py" "$@" --log-level "DEBUG"
}

function listpkgsbyrepo {
	dnf repoquery --repofrompath=test_prunerepo,$testrepo --repo=test_prunerepo --refresh --quiet --location --setopt='skip_if_unavailable=False' | sed 's|file://||' | sort
}

function listpkgsbyfs {
	find . -name '*.rpm' -exec realpath {} \; | sort
}

function run {
	echo '>' $@;
	eval $@;
}

function setup {
	rm -r $testrepo
	cp -r $origrepo $testrepo
	cd $testrepo
}
