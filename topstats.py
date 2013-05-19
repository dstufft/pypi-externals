#!/usr/bin/env python
import os
import json
import xmlrpclib

import redis

import externals


NUMBER = 20

data = []

xmlrpc = xmlrpclib.ServerProxy("https://pypi.python.org/pypi")
packages = xmlrpc.top_packages()

for package, _ in packages:
    print("Processing %s" % package)
    processed = externals.process_package(package, sabort=False)

    # Simple Guard against missing packages
    if processed is None:
        print("Skipping %s because a 404 was raised" % package)
        continue

    if len(processed["per_url"]) == 1:
        print("Skipping %s because it has no external scraping" % package)
        continue

    # Make a set into a list
    processed["per_url"] = list(processed["per_url"])

    # Add to our data set
    data.append(processed)

    # If we've reached the proper number, bail out
    if len(data) >= NUMBER:
        break

# Stick Our data into redis
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost"))
r.set("stats", json.dumps(data))
