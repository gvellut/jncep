#!/usr/bin/env bash

git tag -d "$1"
git push origin --delete "$1"
