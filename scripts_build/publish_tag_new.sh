#!/usr/bin/env bash

git fetch --tags

# make sure all the local changes in master are pushed
local_master=$(git rev-parse master)
remote_master=$(git rev-parse origin/master)

if [ "$local_master" != "$remote_master" ]; then
  echo "Error: Local and remote master are not the same."
  exit 1
fi

version=$(uv version --short)
vtag="v$version"
nd=$(date '+%Y-%m-%dT%H-%M-%S')

git tag -a "$vtag" -m "$vtag $nd"
git push --tags

echo "Tag '$vtag' pushed"