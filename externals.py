import itertools
import urlparse
import os

from flask import Flask
from flask import abort
from flask import render_template

from flask.ext.cache import Cache

import html5lib
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
    per_url = {}

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
    return render_template("index.html")


@app.route("/<package>/")
@cache.cached(timeout=50)
def show_package(package):
    return render_template("detail.html",
                                    **process_package(package, sabort=True))


if __name__ == "__main__":
    app.run(debug=True)
