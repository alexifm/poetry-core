import os
import re

from poetry_core.semver import Version
from poetry_core.utils.patterns import wheel_file_re
from poetry_core.version.requirements import Requirement

from .dependency import Dependency
from .directory_dependency import DirectoryDependency
from .file_dependency import FileDependency
from .package import Package
from .project_package import ProjectPackage
from .url_dependency import URLDependency
from .utils.link import Link
from .utils.utils import convert_markers
from .utils.utils import group_markers
from .utils.utils import is_archive_file
from .utils.utils import is_installable_dir
from .utils.utils import is_url
from .utils.utils import path_to_url
from .utils.utils import strip_extras
from .vcs_dependency import VCSDependency


def dependency_from_pep_508(name):
    from poetry_core.vcs.git import ParsedUrl

    # Removing comments
    parts = name.split("#", 1)
    name = parts[0].strip()
    if len(parts) > 1:
        rest = parts[1]
        if ";" in rest:
            name += ";" + rest.split(";", 1)[1]

    req = Requirement(name)

    if req.marker:
        markers = convert_markers(req.marker)
    else:
        markers = {}

    name = req.name
    path = os.path.normpath(os.path.abspath(name))
    link = None

    if is_url(name):
        link = Link(name)
    elif req.url:
        link = Link(req.url)
    else:
        p, extras = strip_extras(path)
        if os.path.isdir(p) and (os.path.sep in name or name.startswith(".")):

            if not is_installable_dir(p):
                raise ValueError(
                    "Directory {!r} is not installable. File 'setup.py' "
                    "not found.".format(name)
                )
            link = Link(path_to_url(p))
        elif is_archive_file(p):
            link = Link(path_to_url(p))

    # it's a local file, dir, or url
    if link:
        # Handle relative file URLs
        if link.scheme == "file" and re.search(r"\.\./", link.url):
            link = Link(path_to_url(os.path.normpath(os.path.abspath(link.path))))
        # wheel file
        if link.is_wheel:
            m = wheel_file_re.match(link.filename)
            if not m:
                raise ValueError("Invalid wheel name: {}".format(link.filename))

            name = m.group("name")
            version = m.group("ver")
            dep = Dependency(name, version)
        else:
            name = req.name or link.egg_fragment

            if link.scheme.startswith("git+"):
                url = ParsedUrl.parse(link.url)
                dep = VCSDependency(name, "git", url.url, rev=url.rev)
            elif link.scheme == "git":
                dep = VCSDependency(name, "git", link.url_without_fragment)
            elif link.scheme in ["http", "https"]:
                dep = URLDependency(name, link.url_without_fragment)
            else:
                dep = Dependency(name, "*")
    else:
        if req.pretty_constraint:
            constraint = req.constraint
        else:
            constraint = "*"

        dep = Dependency(name, constraint)

    if "extra" in markers:
        # If we have extras, the dependency is optional
        dep.deactivate()

        for or_ in markers["extra"]:
            for _, extra in or_:
                dep.in_extras.append(extra)

    if "python_version" in markers:
        ors = []
        for or_ in markers["python_version"]:
            ands = []
            for op, version in or_:
                # Expand python version
                if op == "==":
                    version = "~" + version
                    op = ""
                elif op == "!=":
                    version += ".*"
                elif op in ("<=", ">"):
                    parsed_version = Version.parse(version)
                    if parsed_version.precision == 1:
                        if op == "<=":
                            op = "<"
                            version = parsed_version.next_major.text
                        elif op == ">":
                            op = ">="
                            version = parsed_version.next_major.text
                    elif parsed_version.precision == 2:
                        if op == "<=":
                            op = "<"
                            version = parsed_version.next_minor.text
                        elif op == ">":
                            op = ">="
                            version = parsed_version.next_minor.text
                elif op in ("in", "not in"):
                    versions = []
                    for v in re.split("[ ,]+", version):
                        split = v.split(".")
                        if len(split) in [1, 2]:
                            split.append("*")
                            op_ = "" if op == "in" else "!="
                        else:
                            op_ = "==" if op == "in" else "!="

                        versions.append(op_ + ".".join(split))

                    glue = " || " if op == "in" else ", "
                    if versions:
                        ands.append(glue.join(versions))

                    continue

                ands.append("{}{}".format(op, version))

            ors.append(" ".join(ands))

        dep.python_versions = " || ".join(ors)

    if req.marker:
        dep.marker = req.marker

    # Extras
    for extra in req.extras:
        dep.extras.append(extra)

    return dep
