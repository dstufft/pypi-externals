# Copyright 2013 Donald Stufft
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import collections
import itertools
import urlparse
import os
import json
import hashlib

from flask import Flask
from flask import abort
from flask import redirect
from flask import render_template
from flask import request

from flask.ext.cache import Cache

import html5lib
import redis
import requests

from pkg_resources import safe_name
from setuptools.package_index import distros_for_url


app = Flask(__name__)

cache_config = {}
if "REDIS_URL" in os.environ:
    cache_config["CACHE_TYPE"] = "redis"
    cache_config["CACHE_REDIS_URL"] = os.environ["REDIS_URL"]
else:
    cache_config["CACHE_TYPE"] = "simple"
cache = Cache(app, config=cache_config)

if "REDIS_URL" in os.environ:
    datastore = redis.Redis.from_url(os.environ["REDIS_URL"])
else:
    datastore = None


def installable(project, url):
    normalized = safe_name(project).lower()
    return bool([dist for dist in distros_for_url(url) if
                        safe_name(dist.project_name).lower() == normalized])


def version_for_url(project, url):
    normalized = safe_name(project).lower()
    return [dist for dist in distros_for_url(url) if
                safe_name(dist.project_name).lower() == normalized][0].version


def process_page(html, package, url):
    installable_ = set()
    for link in html.findall(".//a"):
        if "href" in link.attrib:
            try:
                absolute_link = urlparse.urljoin(url, link.attrib["href"])
            except Exception:
                continue

            if installable(package, absolute_link):
                installable_.add((url, absolute_link))
    return installable_


def process_package(package, sabort=False):
    session = requests.session()
    session.verify = False

    # Grab the page from PyPI
    url = "https://pypi.python.org/simple/%s/" % package
    resp = session.get(url)
    if resp.status_code == 404:
        if sabort:
            abort(404)
        else:
            return
    resp.raise_for_status()

    html = html5lib.parse(resp.content, namespaceHTMLElements=False)

    spider = set()
    installable_ = set()
    per_url = collections.OrderedDict()

    for link in itertools.chain(
                        html.findall(".//a[@rel='download']"),
                        html.findall(".//a[@rel='homepage']")):
        if "href" in link.attrib:
            try:
                absolute_link = urlparse.urljoin(url, link.attrib["href"])
            except Exception:
                continue

            if not installable(package, absolute_link):
                parsed = urlparse.urlparse(absolute_link)
                if parsed.scheme.lower() in ["http", "https"]:
                    spider.add(absolute_link)

    # Find installable links from the PyPI page
    per_url[url] = process_page(html, package, url)
    installable_ |= per_url[url]

    # Find installable links from pages we spider
    for link in spider:
        try:
            resp = session.get(link)
            resp.raise_for_status()
        except Exception:
            continue

        html = html5lib.parse(resp.content, namespaceHTMLElements=False)
        per_url[link] = process_page(html, package, link)
        installable_ |= per_url[link]

    # Find the ones only available externally
    internal = set()
    external = set()
    for candidate in installable_:
        version = version_for_url(package, candidate[1])
        if (candidate[0] == url and
                urlparse.urlparse(candidate[1]).netloc
                    == "pypi.python.org"):
            internal.add(version)
        else:
            external.add(version)

    external_only = []
    count = 0
    temp = []
    for v in (external - internal):
        if count < 4:
            temp.append(v)
            count += 1
        if count >= 4:
            external_only.append(temp)
            temp = []
            count = 0
    if temp:
        external_only.append(temp)

    return dict(package=package, per_url=per_url, external_only=external_only)


@app.route("/")
def index():
    stats = []
    if datastore is not None:
        encoded = datastore.get("stats")
        last_updated = datastore.get("stats.update")
        if encoded:
            stats = json.loads(encoded)
    return render_template("index.html",
                                stats=stats, last_updated=last_updated)


@app.route("/<package>/")
@cache.cached(timeout=50)
def show_package(package):
    data = process_package(package, sabort=True)
    hashed = {k: hashlib.md5(k).hexdigest() for k in data["per_url"]}
    data["hashed"] = hashed
    return render_template("detail.html", **data)


@app.route("/internal/package_redirect/")
def redirect_package():
    package = request.args.get("package")
    if package is None:
        return redirect("/")
    return redirect("/%s/" % package)


@app.route("/help/what/")
def help_what():
    return render_template("help/what.html")


if __name__ == "__main__":
    app.run(debug=True)
