#!/usr/bin/env bash

RELEASE_TAG="$1"

git tag -d "$RELEASE_TAG"
git push origin --delete "$RELEASE_TAG"
